"""Extraction of official figures from WHO Disease Outbreak News (DON) narrative text.

WHO DON items are prose, not tables. This extractor is deliberately
conservative: it only emits a figure when the sentence pattern unambiguously
states a cumulative count with a case-definition category and a date, and it
records the supporting sentence as a quote. Anything ambiguous (multi-country
totals, derived arithmetic, figures without a stated date) is emitted with low
extraction confidence so that it is routed to human review instead of being
published automatically.

Counts introduced as "additional", "new", "weekly" or "per day" are increments
over periods that the text does not state precisely; they are skipped rather
than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.enums import CaseClass, Metric, TransmissionType, ValueType
from ..nlp.gazetteer import Gazetteer, fold
from ..sources.base import ObservationCandidate
from .textnum import NUM_PATTERN, ORDINAL_WORDS, find_dates, parse_number, sentences

N = NUM_PATTERN
CLASS_WORDS = {
    "laboratory-confirmed": CaseClass.CONFIRMED,
    "laboratory confirmed": CaseClass.CONFIRMED,
    "lab-confirmed": CaseClass.CONFIRMED,
    "confirmed": CaseClass.CONFIRMED,
    "probable": CaseClass.PROBABLE,
    "suspected": CaseClass.SUSPECTED,
    "suspect": CaseClass.SUSPECTED,
}
_CLASS_ALT = r"laboratory[- ]confirmed|lab-confirmed|confirmed|probable|suspected|suspect"
_DISEASE = r"(?:(?:BVD|EVD|SVD|Ebola|Bundibugyo|Sudan virus|Ebola virus)\s+(?:disease\s+)?)?"

CASES_RE = re.compile(rf"(?P<n>{N})\s+(?:cumulative\s+)?(?P<cls>{_CLASS_ALT})\s+{_DISEASE}cases?\b", re.I)
CASES_CUMUL_RE = re.compile(rf"(?:cumulative\s+(?:total\s+)?(?:of\s+)?|a\s+total\s+of\s+)(?P<n>{N})\s+(?P<cls>{_CLASS_ALT})\s+{_DISEASE}cases?\b", re.I)
DEATHS_AMONG_RE = re.compile(rf"(?P<n>{N})\s+deaths?\s+among\s+(?:these\s+|the\s+)?(?P<cls>{_CLASS_ALT})\s+cases", re.I)
DEATHS_CLASSED_RE = re.compile(rf"(?P<n>{N})\s+(?P<cls>{_CLASS_ALT})\s+deaths?\b", re.I)
DEATHS_INCLUDING_RE = re.compile(rf"(?:including|with)\s+(?P<n>{N})\s+deaths?\b(?!\s+among)", re.I)
DEATHS_PLAIN_RE = re.compile(rf"(?:and|,)\s+(?P<n>{N})\s+deaths?\b(?!\s+among)", re.I)
PROBABLE_DIED_RE = re.compile(rf"(?P<n>{N})\s+probable\s+cases?\s+(?:who\s+(?:has|have)\s+died|\(died\)|,?\s+(?:all\s+)?deceased)", re.I)
INCLUDING_IN_COUNTRY_RE = re.compile(rf"(?:including\s+|\()(?P<n>{N})\s+in\s+(?P<place>[A-Z][\w' -]+?)(?=[,;.)]|\s+with|\s+and)", re.I)
INCREMENT_CUES = re.compile(r"\b(additional|new|weekly|daily|per day|average|24-hour|preceding|previous \d+|past \w+ (days|weeks)|in the last|since the (last|previous))\b", re.I)
MULTI_COUNTRY_CUES = re.compile(r"\b(both countries|the two countries|across (all|the) (affected )?countries|combined|in total)\b", re.I)
AS_OF_RE = re.compile(r"\bas of\b", re.I)
WINDOW_RE = re.compile(r"\b(?:last|past|preceding|previous)\s+(\d{1,2})\s+days\b", re.I)
HEALTH_ZONE_CLAUSE = re.compile(r"\bhealth zones?\b|\bzones? de santé\b", re.I)
HZ_RE = re.compile(rf"(?P<hz>{N})\s+(?:affected\s+)?health zones\s+(?:across|in|from)\s+(?P<prov>{N})\s+(?:out of \d+ )?provinces", re.I)
HZ_TO_RE = re.compile(rf"(?:spread|expanded)\s+(?:from\s+{N}\s+)?to\s+(?P<hz>{N})\s+health zones", re.I)
CONTACTS_RE = re.compile(rf"(?P<seen>{N})\s+(?:contacts\s+(?:seen|reached|followed(?: up)?)\s+)?(?:of|out of)\s+(?P<listed>{N})\s+(?:contacts|requiring follow)", re.I)
COMMUNITY_DEATHS_RE = re.compile(rf"(?P<n>{N})\s+of\s+(?:the\s+)?(?P<d>{N})\s+(?:reported\s+)?deaths\s+occurred\s+in\s+(?:the\s+)?communit", re.I)
NO_NEW_SINCE_RE = re.compile(r"\b(?:has not reported any new cases|no new (?:confirmed )?cases have been reported|no new cases (?:have been )?reported)\s+since\s+", re.I)
END_DECLARED_RE = re.compile(r"\b(declared|announced)\s+the\s+end\s+of\s+the\s+(?:\w+\s+){0,4}outbreak", re.I)
IMPORTED_RE = re.compile(rf"(?P<q>(?:a|an|one|the\s+(?:first|second|third)|(?:first|second|third)|{N}))\s+(?:laboratory[- ]confirmed\s+|confirmed\s+)?imported\s+cases?\b", re.I)
MEDEVAC_RE = re.compile(r"\b(medical(?:ly)? evacuat\w+|medevac\w*|repatriat\w+)\b", re.I)
POSITIVE_RE = re.compile(r"\b(tested positive|laboratory[- ]confirmed|confirmed case|positive by PCR)\b", re.I)
CFR_RE = re.compile(r"(?:CFR|case fatality (?:ratio|rate))[^.%]{0,40}?(\d{1,2}(?:\.\d+)?)\s?%", re.I)
DEMONYMS = {"german": "DEU", "french": "FRA", "dutch": "NLD", "american": "USA", "british": "GBR", "belgian": "BEL",
            "ugandan": "UGA", "kenyan": "KEN", "rwandan": "RWA", "congolese": None}


@dataclass
class DonExtraction:
    candidates: list[ObservationCandidate] = field(default_factory=list)
    stated_cfr: list[float] = field(default_factory=list)
    primary_countries: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _countries(g: Gazetteer, text: str) -> list[str]:
    seen: list[str] = []
    for m in g.find(text):
        code = m.code if m.level == 0 else g.country_of(m.code)
        if code not in seen:
            seen.append(code)
    return seen


def _admin1(g: Gazetteer, text: str) -> list[tuple[str, int]]:
    return [(m.code, m.start) for m in g.find(text) if m.level == 1]


def _quote(s: str, limit: int = 400) -> str:
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _preceded_by_increment(clause: str, start: int) -> bool:
    return bool(INCREMENT_CUES.search(clause[max(0, start - 40): start]))


def _clauses(sentence: str) -> list[str]:
    """Split a sentence on ';' and on a second 'As of' so each clause carries one jurisdiction."""
    parts: list[str] = []
    for chunk in sentence.split(";"):
        idxs = [m.start() for m in AS_OF_RE.finditer(chunk)]
        if len(idxs) > 1:
            bounds = [0] + idxs[1:] + [len(chunk)]
            parts.extend(chunk[a:b] for a, b in zip(bounds, bounds[1:], strict=False))
        else:
            parts.append(chunk)
    return [p.strip() for p in parts if p.strip()]


def extract(title: str, text: str, published: date, g: Gazetteer) -> DonExtraction:
    out = DonExtraction()
    out.primary_countries = _countries(g, title)
    primary = out.primary_countries[0] if len(out.primary_countries) == 1 else None
    out.stated_cfr = [float(m.group(1)) for m in CFR_RE.finditer(text)]

    seen_keys: set[tuple] = set()

    def emit(c: ObservationCandidate) -> None:
        key = (c.region_ref, c.metric, c.case_class, c.value_type, c.as_of, c.transmission, c.value)
        if key not in seen_keys:
            seen_keys.add(key)
            out.candidates.append(c)

    doc_as_of: date | None = None
    for _, sent in sentences(text):
        dates = find_dates(sent, published)
        if AS_OF_RE.search(sent) and dates:
            cand = max(d for _, _, d, _ in dates)
            if doc_as_of is None or cand > doc_as_of:
                doc_as_of = cand

    last_as_of: date | None = None
    prev_sentence_had_as_of = False
    for _, sent in sentences(text):
        sent_dates = find_dates(sent, published)
        carried = prev_sentence_had_as_of
        prev_sentence_had_as_of = bool(AS_OF_RE.search(sent) and sent_dates)
        for clause in _clauses(sent):
            dates = find_dates(clause, published)
            as_of_m = AS_OF_RE.search(clause)
            as_of: date | None = None
            date_conf = "high"
            if as_of_m:
                after = [d for s, _, d, _ in dates if s >= as_of_m.start()]
                as_of = after[0] if after else None
            if as_of is None and AS_OF_RE.search(sent) and sent_dates:
                as_of, date_conf = sent_dates[0][2], "medium"
            if as_of:
                last_as_of = as_of

            _extract_events(out, emit, clause, dates, published, g, primary)

            countries = _countries(g, clause)
            admin1 = _admin1(g, clause)
            multi = bool(MULTI_COUNTRY_CUES.search(clause))

            # Determine jurisdiction
            region: str | None = None
            conf = "high"
            if admin1 and not multi:
                # the admin-1 unit mentioned closest before the first count
                first_num = CASES_RE.search(clause)
                pos = first_num.start() if first_num else len(clause)
                before = [code for code, start in admin1 if start <= pos] or [admin1[0][0]]
                region = before[-1]
            elif multi:
                region = None
            elif len(countries) == 1:
                region = countries[0]
            elif not countries and primary and re.search(r"\b(the country|nationally|national level|have been reported|has reported|has recorded|were reported)\b", clause, re.I):
                region = primary
                conf = "medium"
            elif len(countries) > 1:
                # e.g. "a doctor returning from the DRC to France": not a jurisdiction total
                out.skipped.append(_quote(clause, 160))
                continue

            country_region = countries[0] if len(countries) == 1 else primary
            cases = _cumulative_cases(clause)
            if not cases:
                _extract_context_metrics(out, emit, clause, country_region, as_of or last_as_of or doc_as_of, conf)
                continue
            # Figures for a single health zone are not province totals.
            if HEALTH_ZONE_CLAUSE.search(clause):
                out.skipped.append(_quote(clause, 160))
                continue
            if as_of is None:
                if region and admin1:
                    as_of = last_as_of or doc_as_of
                    date_conf = "medium" if carried and last_as_of else "low"
                else:
                    out.skipped.append(_quote(clause, 160))
                    continue
            if as_of is None:
                continue

            deaths = _deaths(clause, cases)
            confidence = min((conf, date_conf), key=["low", "medium", "high"].index)

            if multi:
                _decompose_multicountry(out, emit, clause, cases, deaths, as_of, g)
                continue
            if region is None:
                out.skipped.append(_quote(clause, 160))
                continue
            for cls, n in cases.items():
                emit(ObservationCandidate(region, Metric.CASES, cls, ValueType.CUMULATIVE, as_of, n,
                                          quote=_quote(clause), extraction_method="text_pattern", confidence=confidence))
            for cls, n in deaths.items():
                emit(ObservationCandidate(region, Metric.DEATHS, cls, ValueType.CUMULATIVE, as_of, n,
                                          quote=_quote(clause), extraction_method="text_pattern", confidence=confidence))
            _extract_context_metrics(out, emit, clause, country_region, as_of, confidence)
    return out


def _cumulative_cases(clause: str) -> dict[CaseClass, int]:
    found: dict[CaseClass, int] = {}
    for rx in (CASES_CUMUL_RE, CASES_RE):
        for m in rx.finditer(clause):
            if _preceded_by_increment(clause, m.start()):
                continue
            n = parse_number(m.group("n"))
            cls = CLASS_WORDS[m.group("cls").lower().replace("–", "-")]
            if n is not None and cls not in found:
                found[cls] = n
    m = PROBABLE_DIED_RE.search(clause)
    if m and CaseClass.PROBABLE not in found and (n := parse_number(m.group("n"))) is not None:
        found[CaseClass.PROBABLE] = n
    return found


def _deaths(clause: str, cases: dict[CaseClass, int]) -> dict[CaseClass, int]:
    deaths: dict[CaseClass, int] = {}
    for m in DEATHS_AMONG_RE.finditer(clause):
        if not _preceded_by_increment(clause, m.start()):
            deaths[CLASS_WORDS[m.group("cls").lower()]] = parse_number(m.group("n"))
    for m in DEATHS_CLASSED_RE.finditer(clause):
        if not _preceded_by_increment(clause, m.start()):
            deaths.setdefault(CLASS_WORDS[m.group("cls").lower()], parse_number(m.group("n")))
    if len(cases) == 1:
        (only_cls,) = cases
        for rx in (DEATHS_INCLUDING_RE, DEATHS_PLAIN_RE):
            m = rx.search(clause)
            if m and only_cls not in deaths and not _preceded_by_increment(clause, m.start()):
                deaths[only_cls] = parse_number(m.group("n"))
    m = PROBABLE_DIED_RE.search(clause)
    if m:
        deaths.setdefault(CaseClass.PROBABLE, parse_number(m.group("n")))
    return {k: v for k, v in deaths.items() if v is not None}


def _decompose_multicountry(out: DonExtraction, emit, clause, cases, deaths, as_of, g: Gazetteer) -> None:
    """Totals across countries: assign the stated sub-count; derive the remainder only for review."""
    note = "multi-country total in source; sub-national split derived by subtraction"
    for m in INCLUDING_IN_COUNTRY_RE.finditer(clause):
        place = g.lookup(m.group("place").strip())
        n = parse_number(m.group("n"))
        if not place or n is None:
            continue
        code = place[0] if place[1] == 0 else g.country_of(place[0])
        cls = CaseClass.CONFIRMED if CaseClass.CONFIRMED in cases else next(iter(cases))
        emit(ObservationCandidate(code, Metric.CASES, cls, ValueType.CUMULATIVE, as_of, n, quote=_quote(clause),
                                  extraction_method="text_pattern", confidence="medium",
                                  notes=["stated as a component of a multi-country total"]))
        others = [c for c in out.primary_countries if c != code]
        if len(others) == 1 and cls in cases:
            emit(ObservationCandidate(others[0], Metric.CASES, cls, ValueType.CUMULATIVE, as_of, cases[cls] - n,
                                      quote=_quote(clause), extraction_method="derived", confidence="low", notes=[note]))
        break
    else:
        out.skipped.append(_quote(clause, 160))


def _extract_context_metrics(out, emit, clause, region, as_of, confidence) -> None:
    if not region or not as_of:
        return
    hz_matches = list(HZ_RE.finditer(clause))
    for i, m in enumerate(hz_matches):
        hz, prov = parse_number(m.group("hz")), parse_number(m.group("prov"))
        seg_end = hz_matches[i + 1].start() if i + 1 < len(hz_matches) else len(clause)
        window = WINDOW_RE.search(clause, m.end(), min(seg_end, m.end() + 90))
        vt = ValueType.INCIDENT if window else ValueType.CUMULATIVE
        period_start = as_of - timedelta(days=int(window.group(1))) if window else None
        attrs = {"window_days": int(window.group(1))} if window else {}
        if hz is not None:
            emit(ObservationCandidate(region, Metric.AFFECTED_ADMIN2, CaseClass.CONFIRMED, vt, as_of, hz, period_start=period_start,
                                      quote=_quote(clause), extraction_method="text_pattern", confidence=confidence,
                                      attributes={"unit": "health_zone", **attrs}))
        if prov is not None:
            emit(ObservationCandidate(region, Metric.AFFECTED_ADMIN1, CaseClass.CONFIRMED, vt, as_of, prov, period_start=period_start,
                                      quote=_quote(clause), extraction_method="text_pattern", confidence=confidence,
                                      attributes={"unit": "province", **attrs}))
    if not HZ_RE.search(clause):
        m = HZ_TO_RE.search(clause)
        if m and (hz := parse_number(m.group("hz"))) is not None:
            emit(ObservationCandidate(region, Metric.AFFECTED_ADMIN2, CaseClass.CONFIRMED, ValueType.CUMULATIVE, as_of, hz,
                                      quote=_quote(clause), extraction_method="text_pattern", confidence="medium",
                                      attributes={"unit": "health_zone"}))
    for m in CONTACTS_RE.finditer(clause):
        seen, listed = parse_number(m.group("seen")), parse_number(m.group("listed"))
        if seen is not None and listed and seen <= listed:
            emit(ObservationCandidate(region, Metric.CONTACTS_SEEN, CaseClass.NOT_APPLICABLE, ValueType.INCIDENT, as_of, seen,
                                      period_start=as_of, quote=_quote(clause), extraction_method="text_pattern",
                                      confidence=confidence, attributes={"denominator": listed}))
    m = COMMUNITY_DEATHS_RE.search(clause)
    if m:
        n, d = parse_number(m.group("n")), parse_number(m.group("d"))
        if n is not None and d and n <= d:
            emit(ObservationCandidate(region, Metric.COMMUNITY_DEATHS, CaseClass.NOT_APPLICABLE, ValueType.INCIDENT, as_of, n,
                                      quote=_quote(clause), extraction_method="text_pattern", confidence="medium",
                                      attributes={"denominator": d, "period": "since previous bulletin"}))


def _extract_events(out, emit, clause, dates, published, g: Gazetteer, primary) -> None:
    """Narrative events: imported cases, medical evacuations, explicit zero reports, end declarations."""
    event_date = dates[0][2] if dates else published
    countries = _countries(g, clause)
    m = IMPORTED_RE.search(clause)
    if m and countries and not re.search(r"\bno\s+(?:new\s+)?imported\b", clause, re.I):
        q = m.group("q").lower().replace("the ", "").strip()
        n = ORDINAL_WORDS.get(q) or parse_number(q) or 1
        dest = next((c for c in countries if c != primary), None)
        origin = primary if primary and primary != dest else next((c for c in countries if c != dest), None)
        if dest:
            emit(ObservationCandidate(dest, Metric.CASES, CaseClass.CONFIRMED, ValueType.CUMULATIVE, event_date, n,
                                      transmission=TransmissionType.IMPORTED, quote=_quote(clause),
                                      extraction_method="text_pattern", confidence="medium",
                                      notes=["narrative statement; value is a lower bound (at least this many imported cases)"],
                                      attributes={"origin_iso3": origin} if origin else {}))
    if MEDEVAC_RE.search(clause) and POSITIVE_RE.search(clause):
        dest = None
        for word, code in DEMONYMS.items():
            if code and re.search(rf"\b{word}\s+(authorities|health authorities|ministry)", clause, re.I):
                dest = code
                break
        if dest is None:
            m2 = re.search(r"\b(?:to|in)\s+(the\s+)?([A-Z][\w ]+?)\s+(?:for care|for treatment|under strict)", clause)
            if m2 and (p := g.lookup(m2.group(2))):
                dest = p[0]
        if dest is None:
            rep = re.match(r"\s*(?:On [^,]+,\s*)?(the\s+)?([A-Z][\w ]+?)\s+(?:reported|notified|informed)", clause)
            if rep and (p := g.lookup(rep.group(2))):
                dest = p[0] if p[1] == 0 else g.country_of(p[0])
        if dest and dest != primary:
            emit(ObservationCandidate(dest, Metric.CASES, CaseClass.CONFIRMED, ValueType.CUMULATIVE, event_date, 1,
                                      transmission=TransmissionType.MEDEVAC, quote=_quote(clause),
                                      extraction_method="text_pattern", confidence="low",
                                      notes=["medically evacuated / repatriated patient; not a local case and not an exportation signal",
                                             "value is a lower bound"]))
    m = NO_NEW_SINCE_RE.search(clause)
    if m:
        after = [d for s, _, d, _ in dates if s >= m.end() - 1]
        target = countries[0] if countries else primary
        if after and target:
            emit(ObservationCandidate(target, Metric.CASES, CaseClass.CONFIRMED, ValueType.INCIDENT, published, 0,
                                      period_start=after[0], quote=_quote(clause), extraction_method="text_pattern",
                                      confidence="medium", notes=["explicit statement of zero new cases over the period"]))
    if END_DECLARED_RE.search(clause):
        target = countries[0] if countries else primary
        if target:
            emit(ObservationCandidate(target, Metric.OUTBREAK_END_DECLARED, CaseClass.NOT_APPLICABLE, ValueType.CUMULATIVE,
                                      event_date, 1, quote=_quote(clause), extraction_method="text_pattern", confidence="medium"))


def fold_title(title: str) -> str:
    return fold(title)
