"""Ingestion: connector runs -> documents, vintages and validated observations.

Guarantees:
* every observation keeps source, publication date, observation date, retrieval
  time, jurisdiction, case-definition category, vintage and citation;
* historical observations are never overwritten: a changed value for the same
  (source, unit, metric, class, date) is a new row that supersedes the old one;
* fetched text is sanitised, PII-redacted, length-limited and given a retention
  deadline; social-media authors are reduced to keyed pseudonyms;
* machine-extracted figures that fail consistency checks, or are ambiguous, are
  held for human review and excluded from public outputs until verified.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.base import utcnow
from ..db.models import ConnectorRun, DataVintage, Document, Observation, Outbreak, Region, Source
from ..domain.enums import (
    ConnectorStatus,
    Metric,
    TransmissionType,
    ValidationStatus,
    ValueType,
)
from ..nlp.gazetteer import load_gazetteer
from ..privacy.redaction import pseudonymize, redact
from ..review.queue import enqueue
from ..safety.untrusted import sanitize
from ..sources.base import Connector, FetchedItem, ObservationCandidate
from ..sources.http import HttpClient
from .seed import ensure_health_zone

MAX_STORED_TEXT = 4000
SOCIAL_PLATFORMS = {"reddit", "youtube", "x", "facebook", "telegram"}


def _hash(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def resolve_region(session: Session, ref: str, level_hint: int | None = None) -> Region | None:
    r = session.scalar(select(Region).where(Region.code == ref))
    if r:
        return r
    if ref.startswith("HZ:"):
        return ensure_health_zone(session, ref)
    g = load_gazetteer()
    hit = g.lookup(ref)
    if hit:
        return session.scalar(select(Region).where(Region.code == hit[0]))
    return None


def _outbreak_for(session: Session, region: Region, as_of, pathogen: str | None, transmission: str = "all",
                  source_key: str | None = None) -> int | None:
    """Link an observation to an outbreak; auto-register an unlisted outbreak for review.

    Imported and medically evacuated cases are not attributed to an outbreak in
    the receiving country.
    """
    if transmission in ("imported", "medevac"):
        return None
    best = None
    for ob in session.scalars(select(Outbreak).where(Outbreak.primary_iso3 == region.iso3)):
        if pathogen and ob.pathogen not in (pathogen, "unknown_orthoebolavirus"):
            continue
        if ob.declared_on is None:
            continue
        start = ob.declared_on - timedelta(days=60)
        end = ob.ended_on + timedelta(days=60) if ob.ended_on else ob.declared_on + timedelta(days=730)
        if start <= as_of <= end:
            best = ob.id
    if best is None and pathogen:
        ob = Outbreak(key=f"AUTO-{region.iso3}-{pathogen}-{as_of:%Y%m%d}", name=f"Ebola disease ({pathogen}), {region.iso3} (auto-detected)",
                      pathogen=pathogen, primary_iso3=region.iso3, declared_on=as_of,
                      notes=f"Auto-registered from {source_key or 'official source'} on first linked observation; "
                            "declaration and end dates must be verified")
        session.add(ob)
        session.flush()
        enqueue(session, "outbreak", ob.id, "outbreak auto-registered from official bulletin; verify dates and pathogen", priority=2)
        best = ob.id
    return best


def _pathogen_from_title(title: str | None) -> str | None:
    t = (title or "").lower()
    if "bundibugyo" in t:
        return "BDBV"
    if "sudan" in t:
        return "SUDV"
    if "ebola virus disease" in t or "zaire" in t:
        return "EBOV"
    return None


def run_connector(session: Session, connector: Connector, client: HttpClient, settings: Settings | None = None,
                  since: datetime | None = None) -> ConnectorRun:
    settings = settings or get_settings()
    src = session.scalar(select(Source).where(Source.key == connector.info.key))
    run = ConnectorRun(source_key=connector.info.key, status="running")
    session.add(run)
    session.flush()
    problem = connector.configuration_problem(settings)
    now = utcnow()
    if src:
        src.last_attempt_at = now
    if problem:
        run.status, run.message, run.finished_at = problem[0].value, problem[1], utcnow()
        if src:
            src.status, src.status_message = problem[0].value, problem[1]
        return run
    try:
        result = connector.fetch(client, settings, since)
    except Exception as e:  # a failing connector must not stop the pipeline
        run.status, run.message, run.finished_at = ConnectorStatus.ERROR.value, f"{e.__class__.__name__}: {e}"[:1000], utcnow()
        if src:
            src.status, src.status_message = run.status, run.message
        return run
    new_docs = new_obs = 0
    # chronological order, so outbreaks are registered from their earliest bulletin
    for item in sorted(result.items, key=lambda i: (i.published_at is None, i.published_at or datetime.min.replace(tzinfo=UTC))):
        doc, created, n_obs = store_item(session, src, item, settings)
        new_docs += int(created)
        new_obs += n_obs
    if connector.info.key == "worldbank_population":
        apply_populations(session, result.items)
    if connector.info.key == "osm_overpass":
        apply_overpass_checks(session, result.items)
    run.status, run.message = result.status.value, result.message[:1000]
    run.items_fetched, run.items_new, run.finished_at = len(result.items), new_docs + new_obs, utcnow()
    if src:
        src.status, src.status_message = result.status.value, result.message[:1000]
        if result.status in (ConnectorStatus.OK, ConnectorStatus.PARTIAL):
            src.last_success_at = utcnow()
    session.flush()
    return run


def store_item(session: Session, src: Source, item: FetchedItem, settings: Settings) -> tuple[Document, bool, int]:
    st = sanitize(item.text or "", is_html=item.is_html)
    redacted, removed = redact(st.text)
    content_hash = _hash(item.title, st.text, item.content_version)
    doc = session.scalar(select(Document).where(Document.source_id == src.id, Document.external_id == item.external_id))
    created = False
    if doc is not None and doc.content_hash == content_hash:
        return doc, False, 0
    is_social = (item.platform or "") in SOCIAL_PLATFORMS
    retain = settings.raw_content_retention_days if is_social or not item.is_official else max(settings.raw_content_retention_days, 3650)
    flags = sorted(set(st.flags) | {f"pii_removed:{r}" for r in removed} | set(item.meta.get("safety_flags", [])))
    if doc is None:
        doc = Document(source_id=src.id, external_id=item.external_id[:255])
        session.add(doc)
        created = True
    doc.url = None if is_social else item.url  # links to individual social posts are not kept
    doc.title = sanitize(item.title or "").text[:1000] or None
    doc.language = item.language
    doc.published_at = item.published_at
    doc.retrieved_at = utcnow()
    doc.content_hash = content_hash
    doc.text_minimized = redacted[:MAX_STORED_TEXT] or None
    doc.retain_text_until = utcnow() + timedelta(days=retain)
    doc.author_pseudonym = pseudonymize(item.platform or src.key, item.author_id)
    doc.platform = item.platform
    doc.safety_flags = flags
    doc.meta = {k: v for k, v in item.meta.items() if k not in ("populations", "checks")} | {"is_official": item.is_official}
    doc.is_synthetic = item.is_synthetic
    session.flush()
    n_obs = 0
    if item.observations:
        vintage = DataVintage(source_id=src.id, document_id=doc.id, label=f"{src.key}:{item.external_id}:{item.content_version or ''}"[:255],
                              published_at=item.published_at, content_hash=content_hash)
        session.add(vintage)
        session.flush()
        n_obs = store_observations(session, src, doc, vintage, item)
    return doc, created, n_obs


def _existing_latest(session: Session, src_id: int, region_id: int, c: ObservationCandidate) -> Observation | None:
    q = (select(Observation).where(
        Observation.source_id == src_id, Observation.region_id == region_id, Observation.metric == c.metric.value,
        Observation.case_class == c.case_class.value, Observation.value_type == c.value_type.value,
        Observation.transmission == c.transmission.value, Observation.as_of == c.as_of,
        Observation.period_start == c.period_start).order_by(Observation.id.desc()))
    return session.scalars(q).first()


def validate(c: ObservationCandidate, ctx: dict) -> tuple[ValidationStatus, list[str]]:
    """Consistency checks for one candidate within its document context."""
    notes: list[str] = []
    status = ValidationStatus.AUTO_VALIDATED
    if c.extraction_method == "manual":
        return (ValidationStatus.VERIFIED if ctx.get("reviewer") else ValidationStatus.PENDING_REVIEW), ["manual import"]
    if c.confidence == "low" or c.extraction_method == "derived":
        status = ValidationStatus.PENDING_REVIEW
        notes.append(f"extraction confidence {c.confidence} ({c.extraction_method})")
    if c.value < 0:
        return ValidationStatus.DISPUTED, ["negative value"]
    if c.metric == Metric.DEATHS and c.value_type == ValueType.CUMULATIVE:
        cases = ctx["by_key"].get((c.region_ref, Metric.CASES, c.case_class, c.as_of))
        if cases is not None and c.value > cases:
            status = ValidationStatus.PENDING_REVIEW
            notes.append("deaths exceed cases for the same category and date")
        stated = ctx.get("stated_cfr") or []
        if cases and stated and c.region_ref == ctx.get("primary_region"):
            cfr = 100 * c.value / cases
            if any(abs(cfr - s) <= 0.6 for s in stated):
                notes.append(f"crude CFR {cfr:.1f}% matches the CFR stated in the bulletin")
            elif c.extraction_method == "text_pattern":
                notes.append(f"crude CFR {cfr:.1f}% does not match stated CFR values {stated}")
    if c.metric == Metric.CASES and c.value_type == ValueType.CUMULATIVE and len(c.region_ref) > 3:
        country = load_gazetteer().country_of(c.region_ref)
        parent_total = ctx["national"].get((country, c.case_class, c.as_of))
        if parent_total is not None and c.value > parent_total:
            status = ValidationStatus.PENDING_REVIEW
            notes.append("sub-national value exceeds the national total")
    if c.transmission == TransmissionType.MEDEVAC:
        status = ValidationStatus.PENDING_REVIEW
        notes.append("medically evacuated case: verify receiving country")
    return status, notes


def store_observations(session: Session, src: Source, doc: Document, vintage: DataVintage, item: FetchedItem) -> int:
    by_key = {(c.region_ref, c.metric, c.case_class, c.as_of): c.value for c in item.observations}
    national = {(c.region_ref, c.case_class, c.as_of): c.value for c in item.observations
                if c.metric == Metric.CASES and len(c.region_ref) == 3 and c.transmission == TransmissionType.ALL}
    countries = item.meta.get("countries_in_title") or []
    ctx = {"by_key": by_key, "national": national, "stated_cfr": item.meta.get("stated_cfr_percent"),
           "primary_region": countries[0] if len(countries) == 1 else None, "reviewer": item.meta.get("reviewer")}
    pathogen = _pathogen_from_title(item.title)
    region_cache: dict[str, Region | None] = {}
    n = 0
    for c in item.observations:
        if c.region_ref not in region_cache:
            region_cache[c.region_ref] = resolve_region(session, c.region_ref, c.region_level_hint)
        region = region_cache[c.region_ref]
        if region is None:
            continue
        status, notes = validate(c, ctx)
        prev = _existing_latest(session, src.id, region.id, c)
        if prev is not None and abs(prev.value - c.value) < 1e-9:
            continue
        if prev is not None:
            notes.append(f"revises an earlier vintage value {prev.value:g} -> {c.value:g}")
            if prev.value and abs(c.value - prev.value) / prev.value > 0.05:
                status = ValidationStatus.PENDING_REVIEW
                notes.append("revision larger than 5%: significant source correction, review required")
        obs = Observation(
            outbreak_id=_outbreak_for(session, region, c.as_of, pathogen, c.transmission.value, src.key), region_id=region.id, metric=c.metric.value,
            case_class=c.case_class.value, value_type=c.value_type.value, transmission=c.transmission.value,
            as_of=c.as_of, period_start=c.period_start, value=float(c.value), source_id=src.id, document_id=doc.id,
            vintage_id=vintage.id, published_at=item.published_at, citation=_citation(src, item), quote=c.quote,
            extraction_method=c.extraction_method, validation_status=status.value, validation_notes=notes + list(c.notes),
            attributes=c.attributes, supersedes_id=prev.id if prev else None, is_synthetic=item.is_synthetic,
        )
        session.add(obs)
        session.flush()
        n += 1
        if c.metric == Metric.OUTBREAK_END_DECLARED and obs.outbreak_id and status != ValidationStatus.PENDING_REVIEW:
            ob = session.get(Outbreak, obs.outbreak_id)
            if ob and ob.key.startswith("AUTO-") and ob.ended_on is None and ob.declared_on and c.as_of >= ob.declared_on:
                ob.ended_on = c.as_of
        if status == ValidationStatus.PENDING_REVIEW:
            enqueue(session, "observation", obs.id, "; ".join(notes) or "requires verification", priority=2)
    return n


def _citation(src: Source, item: FetchedItem) -> str:
    when = item.published_at.date().isoformat() if item.published_at else "undated"
    ident = item.meta.get("don_id") or item.external_id
    return f"{src.attribution or src.name}, {ident} ({when}){' ' + item.url if item.url else ''}"


def apply_populations(session: Session, items: list[FetchedItem]) -> int:
    n = 0
    for it in items:
        for iso3, rec in (it.meta.get("populations") or {}).items():
            r = session.scalar(select(Region).where(Region.code == iso3, Region.level == 0))
            if r:
                r.population, r.population_year = rec["population"], rec["year"]
                r.population_source = "World Bank WDI SP.POP.TOTL (CC BY 4.0)"
                n += 1
    return n


def apply_overpass_checks(session: Session, items: list[FetchedItem]) -> int:
    from ..db.models import TransportEdge

    n = 0
    for it in items:
        for key, res in (it.meta.get("checks") or {}).items():
            e = session.scalar(select(TransportEdge).where(TransportEdge.key == key))
            if not e:
                continue
            note = f"OSM Overpass check {res['checked_at'][:10]}: {res['mapped_features']} mapped feature(s) for {res['selector']}"
            e.sources = [s for s in (e.sources or []) if not s.startswith("OSM Overpass check")] + [note]
            if res["mapped_features"] > 0 and e.physical_status == "unverified":
                e.physical_status = "documented"
                if e.verification == "unverified":
                    e.verification = "mapped_only"
            n += 1
    return n


def group_by(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[key(r)].append(r)
    return out


FAILING = (ConnectorStatus.UNAVAILABLE.value, ConnectorStatus.ERROR.value)
FAILING_RETRY_HOURS = 24


def is_due(session: Session, connector, now: datetime | None = None) -> bool:
    """Whether a source should run in a scheduled pass: reference data at most
    every ``refresh_hours``; a source that failed its last three runs (e.g. it
    blocks automated clients) at most once a day instead of every pass."""
    now = now or utcnow()
    recent = list(session.scalars(select(ConnectorRun).where(ConnectorRun.source_key == connector.info.key)
                                  .order_by(ConnectorRun.started_at.desc()).limit(3)))
    if not recent:
        return True
    if len(recent) == 3 and all(r.status in FAILING for r in recent):
        return now - recent[0].started_at >= timedelta(hours=FAILING_RETRY_HOURS)
    if connector.info.refresh_hours:
        ok = next((r for r in recent if r.status in (ConnectorStatus.OK.value, ConnectorStatus.PARTIAL.value)), None)
        if ok is not None:
            return now - ok.started_at >= timedelta(hours=connector.info.refresh_hours)
    return True


def ingest_all(session: Session, settings: Settings | None = None, only: list[str] | None = None,
               client: HttpClient | None = None, due_only: bool = False) -> list[ConnectorRun]:
    from ..sources.registry import all_connectors

    settings = settings or get_settings()
    client = client or HttpClient()
    runs = []
    for c in all_connectors(settings):
        if only and c.info.key not in only:
            continue
        if due_only and not is_due(session, c):
            continue
        since = None
        src = session.scalar(select(Source).where(Source.key == c.info.key))
        if src and src.last_success_at and c.info.key not in ("who_don", "hdx_cod_ebola", "worldbank_population", "osm_overpass"):
            since = src.last_success_at - timedelta(days=2)
        runs.append(run_connector(session, c, client, settings, since))
        session.commit()
    return runs


def now_utc() -> datetime:
    return datetime.now(UTC)
