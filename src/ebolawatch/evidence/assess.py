"""Event-level evidence assessment for unofficial (and official narrative) signals.

Pipeline for a batch of signals:

1. **Origin grouping** – near-duplicates (MinHash similarity >= ``DUP_THRESHOLD``)
   and explicit reposts are one *origin*: 100 reposts of a rumour are one report.
2. **Event clustering** – signals describing an epidemiological event in the same
   administrative unit within an event window are grouped across languages using
   language-independent concepts (region, claim type, date), so a French and a
   Lingala post about the same event are linked.
3. **Independence** – an origin counts as independent corroboration only if it is
   first-hand, professional or official reporting, from a distinct author, and
   not part of a suspected coordinated burst.
4. **Coordination** – bursts of near-identical posts from many pseudonymous
   accounts with no posting history, in a short window, are flagged as possible
   manipulation and excluded from corroboration.
5. **Staleness** – an origin whose text matches a document published long before,
   or which states an old event date, is treated as recirculated.
6. **Cross-check with official data** – explicit official negative statements
   contradict a cluster; officially confirmed cases in the unit are consistent.

Social-media volume is never converted into case counts.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from ..domain.enums import (
    EPIDEMIOLOGICAL_CLAIMS,
    ClaimType,
    Corroboration,
    ReportKind,
    SignalAssessment,
)
from .fingerprint import similarity

DUP_THRESHOLD = 0.6
EVENT_WINDOW_DAYS = 14
STALE_DAYS = 45
COORD_MIN_DOCS = 8
COORD_WINDOW_H = 6
NEW_ACCOUNT_DAYS = 14

FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)
INDEPENDENT_KINDS = {ReportKind.FIRSTHAND_OBSERVATION, ReportKind.PROFESSIONAL_REPORTING, ReportKind.OFFICIAL_ANNOUNCEMENT}


@dataclass
class SignalRecord:
    """Minimal view of a stored signal used by the assessment (no raw text)."""

    id: int
    document_id: int
    published_at: datetime | None
    event_date: date | None
    region_code: str | None  # admin unit at the finest resolved level
    admin1_code: str | None
    country_code: str | None
    claim_type: ClaimType
    report_kind: ReportKind
    relevance: str
    fingerprint: list[int]
    author: str | None
    author_first_seen: datetime | None
    is_repost: bool
    languages: list[str]
    stale_indicators: list[str]
    official_attribution: bool
    disputes_claim: bool
    ebola_negated: bool
    injection_suspected: bool
    is_official_source: bool
    urgency: bool
    platform: str | None = None
    claimed_cases: int | None = None


@dataclass
class OfficialContext:
    """What official sources say about a unit (confirmed counts, explicit negatives)."""

    # unit (admin-1 or country code) -> latest as_of with confirmed cases > 0
    confirmed_units: dict[str, date] = field(default_factory=dict)
    first_confirmed: dict[str, date] = field(default_factory=dict)  # unit -> first as_of with confirmed cases
    official_zero_statements: dict[str, date] = field(default_factory=dict)  # explicit zero/negative statements
    confirmed_counts: dict[str, float] = field(default_factory=dict)  # unit -> latest official cumulative confirmed (incl. imported)


@dataclass
class ClusterResult:
    key: str
    unit: str | None
    claim_type: ClaimType
    signal_ids: list[int]
    origin_groups: dict[str, list[int]]
    n_documents: int
    n_origins: int
    n_independent: int
    languages: list[str]
    first_seen: datetime | None
    last_seen: datetime | None
    window: tuple[date | None, date | None]
    corroboration: Corroboration
    assessment: SignalAssessment
    coordination_suspected: bool
    stale: bool
    evidence: dict
    summary: str
    needs_review: bool


def group_origins(signals: list[SignalRecord], history: list[tuple[int, list[int], datetime | None]] = ()) -> tuple[dict[int, str], dict[int, list[str]]]:
    """Assign each signal an origin-group id. ``history`` holds (doc_id, fingerprint,
    published_at) for older documents used to detect recirculation."""
    order = sorted(signals, key=lambda s: (s.published_at or FAR_FUTURE, s.id))
    origin: dict[int, str] = {}
    reps: list[tuple[str, list[int], datetime | None]] = []
    stale_flags: dict[int, list[str]] = defaultdict(list)
    for s in order:
        assigned = None
        for gid, fp, _ in reps:
            if similarity(s.fingerprint, fp) >= DUP_THRESHOLD:
                assigned = gid
                break
        if assigned is None:
            assigned = f"o{s.document_id}"
            reps.append((assigned, s.fingerprint, s.published_at))
        origin[s.id] = assigned
        for _doc_id, fp, pub in history:
            if pub and s.published_at and (s.published_at - pub).days > STALE_DAYS and similarity(s.fingerprint, fp) >= DUP_THRESHOLD:
                stale_flags[s.id].append(f"matches a document first seen {pub.date()} ({(s.published_at - pub).days} days earlier)")
                break
    return origin, stale_flags


def detect_coordination(signals: list[SignalRecord], origin: dict[int, str]) -> set[str]:
    """Origin groups that look like coordinated amplification."""
    by_origin: dict[str, list[SignalRecord]] = defaultdict(list)
    for s in signals:
        by_origin[origin[s.id]].append(s)
    flagged: set[str] = set()
    for gid, group in by_origin.items():
        if len(group) < COORD_MIN_DOCS:
            continue
        times = sorted(s.published_at for s in group if s.published_at)
        if not times:
            continue
        # densest window
        best = 0
        j = 0
        for i in range(len(times)):
            while times[i] - times[j] > timedelta(hours=COORD_WINDOW_H):
                j += 1
            best = max(best, i - j + 1)
        authors = {s.author for s in group if s.author}
        new_accounts = sum(
            1 for s in group
            if s.author_first_seen and s.published_at and (s.published_at - s.author_first_seen).days <= NEW_ACCOUNT_DAYS
        )
        firsthand = sum(1 for s in group if s.report_kind == ReportKind.FIRSTHAND_OBSERVATION)
        burst = best >= COORD_MIN_DOCS
        many_authors = len(authors) >= COORD_MIN_DOCS * 0.75
        mostly_new = new_accounts >= 0.6 * len(group)
        urgency = sum(1 for s in group if s.urgency) >= 0.5 * len(group)
        if burst and many_authors and (mostly_new or urgency) and firsthand <= 0.2 * len(group):
            flagged.add(gid)
    return flagged


def _unit(s: SignalRecord) -> str | None:
    return s.admin1_code or s.country_code


def cluster(signals: list[SignalRecord], official: OfficialContext, history=(), today: date | None = None) -> list[ClusterResult]:
    today = today or date.today()
    epi = [s for s in signals if s.claim_type in EPIDEMIOLOGICAL_CLAIMS and s.relevance != "unlikely" and s.report_kind != ReportKind.SATIRE]
    if not epi:
        return []
    origin, stale_flags = group_origins(epi, history)
    coordinated = detect_coordination(epi, origin)

    # Event clustering: same unit, overlapping window. Signals without a unit are
    # clustered only with other unit-less signals of the same origin.
    def anchor(s: SignalRecord) -> date:
        return s.event_date or (s.published_at.date() if s.published_at else today)

    buckets: dict[str, list[list[SignalRecord]]] = defaultdict(list)
    for s in sorted(epi, key=anchor):
        key = _unit(s) or f"nounit:{origin[s.id]}"
        placed = False
        for group in buckets[key]:
            if abs((anchor(s) - anchor(group[-1])).days) <= EVENT_WINDOW_DAYS:
                group.append(s)
                placed = True
                break
        if not placed:
            buckets[key].append([s])

    results: list[ClusterResult] = []
    for unit_key, groups in buckets.items():
        unit = None if unit_key.startswith("nounit:") else unit_key
        for group in groups:
            results.append(_assess(unit, group, origin, coordinated, stale_flags, official, today))
    return results


def _assess(unit, group: list[SignalRecord], origin, coordinated, stale_flags, official: OfficialContext, today: date) -> ClusterResult:
    origins: dict[str, list[SignalRecord]] = defaultdict(list)
    for s in group:
        origins[origin[s.id]].append(s)

    def origin_head(items: list[SignalRecord]) -> SignalRecord:
        return min(items, key=lambda s: (s.published_at or FAR_FUTURE, s.id))

    stale_origins = {gid for gid, items in origins.items()
                     if any(stale_flags.get(s.id) for s in items) or any(len(s.stale_indicators) >= 1 and s.event_date and (today - s.event_date).days > STALE_DAYS for s in items)}
    independent_authors: set[str] = set()
    n_independent = 0
    for gid, items in origins.items():
        head = origin_head(items)
        if gid in coordinated or gid in stale_origins or head.is_repost:
            continue
        if head.report_kind not in INDEPENDENT_KINDS:
            continue
        a = head.author or f"doc{head.document_id}"
        if a in independent_authors:
            continue
        independent_authors.add(a)
        n_independent += 1

    claim_types = {s.claim_type for s in group}
    claim = ClaimType.EBOLA_CASES if ClaimType.EBOLA_CASES in claim_types else sorted(claim_types)[0]
    dates = [s.event_date or (s.published_at.date() if s.published_at else None) for s in group]
    dates = [d for d in dates if d]
    window = (min(dates) if dates else None, max(dates) if dates else None)
    pubs = [s.published_at for s in group if s.published_at]
    langs = sorted({lang for s in group for lang in s.languages})
    coordination = bool(coordinated & set(origins))
    stale = bool(stale_origins) and len(stale_origins) == len(origins)
    official_sources = [s for s in group if s.is_official_source]

    contradicted = any(s.is_official_source and (s.ebola_negated or s.disputes_claim) for s in group)
    if unit and unit in official.official_zero_statements and window[1] and official.official_zero_statements[unit] >= window[0]:
        contradicted = True
    confirmed_as_of = official.confirmed_units.get(unit) if unit else None
    first_confirmed = official.first_confirmed.get(unit) if unit else None
    officially_active = bool(confirmed_as_of and window[1] and (window[1] - confirmed_as_of).days <= 42)

    # Corroboration level
    if contradicted:
        corr = Corroboration.CONTRADICTED
    elif officially_active or official_sources:
        corr = Corroboration.OFFICIAL_CONFIRMED
    elif n_independent >= 2 and any(origin_head(v).report_kind == ReportKind.PROFESSIONAL_REPORTING for g, v in origins.items() if g not in coordinated):
        corr = Corroboration.PROFESSIONAL_CORROBORATED
    elif n_independent >= 2:
        corr = Corroboration.INDEPENDENT_UNOFFICIAL
    elif len(group) > 1 and len(origins) == 1:
        corr = Corroboration.SINGLE_ORIGIN_AMPLIFIED
    else:
        corr = Corroboration.UNCORROBORATED

    # Assessment
    if coordination and n_independent < 2:
        assessment = SignalAssessment.COORDINATED_AMPLIFICATION
    elif stale:
        assessment = SignalAssessment.STALE_RECIRCULATION
    elif corr == Corroboration.CONTRADICTED:
        assessment = SignalAssessment.INSUFFICIENT_EVIDENCE
    elif corr == Corroboration.OFFICIAL_CONFIRMED:
        assessment = SignalAssessment.CONSISTENT_WITH_OFFICIAL
        claimed = max((s.claimed_cases or 0 for s in group if not s.is_official_source), default=0)
        official_count = official.confirmed_counts.get(unit) if unit else None
        if n_independent >= 2 and not official_sources and first_confirmed is None:
            assessment = SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE
        elif n_independent >= 2 and official_count is not None and claimed > official_count:
            # independent reports describe more cases than the official data currently hold
            assessment = SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE
    elif corr in (Corroboration.INDEPENDENT_UNOFFICIAL, Corroboration.PROFESSIONAL_CORROBORATED):
        assessment = SignalAssessment.POSSIBLE_EMERGING
        country = next((s.country_code for s in group if s.country_code), None)
        if country and country in official.confirmed_units:
            assessment = SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE
    elif corr == Corroboration.SINGLE_ORIGIN_AMPLIFIED:
        assessment = SignalAssessment.INFORMATION_EVENT
    else:
        assessment = SignalAssessment.INSUFFICIENT_EVIDENCE

    needs_review = (
        assessment in (SignalAssessment.POSSIBLE_EMERGING, SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE, SignalAssessment.COORDINATED_AMPLIFICATION)
        or any(s.injection_suspected for s in group)
    )
    evidence = {
        "origins": len(origins),
        "independent_origins": n_independent,
        "coordinated_origins": len(coordinated & set(origins)),
        "stale_origins": len(stale_origins),
        "report_kinds": sorted({s.report_kind.value for s in group}),
        "platforms": sorted({s.platform for s in group if s.platform}),
        "official_documents": len(official_sources),
        "contradicted_by_official": contradicted,
        "unit_has_confirmed_cases": bool(confirmed_as_of),
        "max_claimed_cases": max((s.claimed_cases or 0 for s in group), default=0) or None,
        "official_confirmed_count": official.confirmed_counts.get(unit) if unit else None,
        "injection_flagged_documents": sum(1 for s in group if s.injection_suspected),
    }
    summary = _summary(claim, unit, len(group), len(origins), n_independent, langs)
    key = f"{unit or 'unknown'}:{claim.value}:{window[0]}"
    return ClusterResult(
        key=key, unit=unit, claim_type=claim, signal_ids=[s.id for s in group],
        origin_groups={g: [s.id for s in v] for g, v in origins.items()}, n_documents=len(group), n_origins=len(origins),
        n_independent=n_independent, languages=langs, first_seen=min(pubs) if pubs else None, last_seen=max(pubs) if pubs else None,
        window=window, corroboration=corr, assessment=assessment, coordination_suspected=coordination, stale=stale,
        evidence=evidence, summary=summary, needs_review=needs_review,
    )


CLAIM_PHRASES = {
    ClaimType.EBOLA_CASES: "possible Ebola cases",
    ClaimType.VHF_CLUSTER: "illness with haemorrhagic-fever features",
    ClaimType.UNEXPLAINED_DEATHS: "unexplained deaths",
    ClaimType.ILLNESS_CLUSTER: "a cluster of illness",
    ClaimType.SUSPECTED_OUTBREAK: "a suspected outbreak",
}


def _summary(claim, unit, n_docs, n_origins, n_indep, langs) -> str:
    """Paraphrased, non-identifying description. Never quotes posts or names people."""
    where = f"in {unit}" if unit else "in an unresolved location"
    return (
        f"Reports describe {CLAIM_PHRASES.get(claim, 'a health event')} {where}: {n_docs} item(s) from "
        f"{n_origins} distinct origin(s), {n_indep} assessed as independent; languages: {', '.join(langs) or 'unknown'}."
    )
