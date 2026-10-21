"""Event-based surveillance stage: documents -> signals -> event clusters -> alerts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Alert, Document, Observation, Region, Signal, SignalCluster, Source
from ..domain.enums import (
    OFFICIAL_CATEGORIES,
    ClaimType,
    ReportKind,
    SignalAssessment,
    SourceCategory,
)
from ..evidence.assess import OfficialContext, SignalRecord, cluster
from ..evidence.fingerprint import minhash
from ..nlp.classifier import CLASSIFIER_VERSION, analyze
from ..nlp.gazetteer import load_gazetteer
from ..review.queue import enqueue

LOOKBACK_DAYS = 60


def extract_signals(session: Session, today: date | None = None) -> int:
    """Create a Signal for each document with text that has none yet, and re-analyse
    recent documents whose signal came from an earlier version of the classifier."""
    today = today or date.today()
    g = load_gazetteer()
    existing = {s.document_id: s for s in session.scalars(select(Signal))}
    recent = set(session.scalars(select(Document.id).where(Document.published_at >= datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS))))
    q = select(Document, Source).join(Source, Document.source_id == Source.id).where(Document.text_minimized.is_not(None))
    n = 0
    for doc, src in session.execute(q):
        sig = existing.get(doc.id)
        if sig is not None and ((sig.features or {}).get("classifier_version") == CLASSIFIER_VERSION or doc.id not in recent):
            continue
        cat = SourceCategory(src.category)
        official = cat in OFFICIAL_CATEGORIES
        pub = doc.published_at.date() if doc.published_at else today
        a = analyze((doc.title or "") + "\n" + (doc.text_minimized or ""), pub, cat, g=g,
                    injection_suspected=any(f.startswith("injection:") for f in doc.safety_flags or []),
                    is_official_source=official)
        region = None
        if a.region_code:
            region = session.scalar(select(Region).where(Region.code == a.region_code))
        is_repost = bool(doc.meta.get("is_crosspost")) or "retweeted" in (doc.meta.get("referenced") or [])
        reasons = list(a.review_reasons)
        new = sig is None
        if new:
            sig = Signal(document_id=doc.id, origin_group=f"o{doc.id}")
            session.add(sig)
        sig.languages = [x.code for x in a.languages]
        sig.claim_type = a.claim_type.value
        sig.report_kind = (ReportKind.REPOST if is_repost else a.report_kind).value
        sig.relevance, sig.event_date, sig.event_date_basis, sig.published_at = a.relevance, a.event_date, a.event_date_basis, doc.published_at
        sig.region_id = region.id if region else None
        sig.location_precision = {0: "country", 1: "admin1", 2: "admin2"}.get(a.region_level)
        sig.counts_claimed = a.counts
        sig.features = _jsonable(a.features) | {"stale_indicators": a.stale_indicators, "classifier_version": CLASSIFIER_VERSION,
                                                 "injection_suspected": any(f.startswith("injection:") for f in doc.safety_flags or [])}
        sig.concept_signature = a.concepts
        sig.fingerprint = minhash((doc.title or "") + " " + (doc.text_minimized or ""))
        sig.translation_quality, sig.stale, sig.needs_review = a.translation_quality, bool(a.stale_indicators), a.needs_review
        sig.review_reasons = reasons
        sig.is_synthetic = doc.is_synthetic
        session.flush()
        n += 1
        if new and a.needs_review and a.claim_type.value not in ("not_relevant", "general_discussion"):
            enqueue(session, "signal", sig.id, "; ".join(reasons) or "signal requires review", priority=3)
    return n


def _jsonable(d: dict) -> dict:
    return {k: (list(v) if isinstance(v, (set, tuple)) else v) for k, v in d.items()}


def official_context(session: Session) -> OfficialContext:
    ctx = OfficialContext()
    g = load_gazetteer()
    q = (select(Observation, Region).join(Region, Observation.region_id == Region.id)
         .where(Observation.metric == "cases", Observation.case_class == "confirmed", Observation.value > 0,
                Observation.validation_status.in_(("auto_validated", "verified"))))
    for obs, reg in session.execute(q):
        units = {reg.code}
        if reg.level == 2:
            units.add(g.parents.get(reg.code, reg.code))
        if reg.level >= 1:
            units.add(reg.iso3)
        for u in units:
            if obs.value_type == "cumulative" and u == reg.code:
                ctx.confirmed_counts[u] = max(ctx.confirmed_counts.get(u, 0), obs.value)
            if obs.value_type == "cumulative":
                if u not in ctx.confirmed_units or obs.as_of > ctx.confirmed_units[u]:
                    ctx.confirmed_units[u] = obs.as_of
                if u not in ctx.first_confirmed or obs.as_of < ctx.first_confirmed[u]:
                    ctx.first_confirmed[u] = obs.as_of
    return ctx


def assess_clusters(session: Session, today: date | None = None) -> list[SignalCluster]:
    today = today or date.today()
    g = load_gazetteer()
    since = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    rows = session.execute(
        select(Signal, Document, Source, Region)
        .join(Document, Signal.document_id == Document.id)
        .join(Source, Document.source_id == Source.id)
        .outerjoin(Region, Signal.region_id == Region.id)
        .where((Signal.published_at.is_(None)) | (Signal.published_at >= since))
    ).all()
    first_seen: dict[str, datetime] = {}
    for doc in session.scalars(select(Document).where(Document.author_pseudonym.is_not(None))):
        p = doc.author_pseudonym
        if doc.published_at and (p not in first_seen or doc.published_at < first_seen[p]):
            first_seen[p] = doc.published_at
    records: list[SignalRecord] = []
    for sig, doc, src, reg in rows:
        f = sig.features or {}
        code = reg.code if reg else None
        admin1 = g.admin1_of(code) if code else None
        country = g.country_of(code) if code else None
        records.append(SignalRecord(
            id=sig.id, document_id=doc.id, published_at=sig.published_at, event_date=sig.event_date, region_code=code,
            admin1_code=admin1, country_code=country, claim_type=ClaimType(sig.claim_type), report_kind=ReportKind(sig.report_kind),
            relevance=sig.relevance, fingerprint=sig.fingerprint or [], author=doc.author_pseudonym,
            author_first_seen=first_seen.get(doc.author_pseudonym) if doc.author_pseudonym else None,
            is_repost=sig.report_kind == ReportKind.REPOST.value, languages=sig.languages or [],
            stale_indicators=f.get("stale_indicators", []), official_attribution=bool(f.get("official_body")),
            disputes_claim=bool(f.get("disputes_claim")), ebola_negated=bool(f.get("ebola_negated")),
            injection_suspected=bool(f.get("injection_suspected")), is_official_source=SourceCategory(src.category) in OFFICIAL_CATEGORIES,
            urgency=bool(f.get("urgency")), platform=doc.platform or ("news" if src.category == "news" else src.key),
            claimed_cases=(sig.counts_claimed or {}).get("ill"),
        ))
    history = [(d.id, s.fingerprint, d.published_at) for s, d, _, _ in rows if d.published_at]
    results = cluster(records, official_context(session), history=history, today=today)
    out = []
    for res in results:
        key = f"c{min(res.signal_ids)}"
        cl = session.scalar(select(SignalCluster).where(SignalCluster.cluster_key == key))
        region = session.scalar(select(Region).where(Region.code == res.unit)) if res.unit else None
        if cl is None:
            cl = SignalCluster(cluster_key=key, claim_type=res.claim_type.value, summary=res.summary,
                               corroboration=res.corroboration.value, assessment=res.assessment.value)
            session.add(cl)
        cl.region_id = region.id if region else None
        cl.claim_type = res.claim_type.value
        cl.summary = res.summary
        cl.first_seen, cl.last_seen = res.first_seen, res.last_seen
        cl.event_window_start, cl.event_window_end = res.window
        cl.n_documents, cl.n_origins, cl.n_independent_origins = res.n_documents, res.n_origins, res.n_independent
        cl.languages = res.languages
        cl.corroboration, cl.assessment = res.corroboration.value, res.assessment.value
        cl.coordination_suspected, cl.stale = res.coordination_suspected, res.stale
        cl.evidence = res.evidence | {"key": key}
        cl.is_synthetic = any(s.is_synthetic for s, *_ in rows if s.id in res.signal_ids)
        session.flush()
        for sid in res.signal_ids:
            s = session.get(Signal, sid)
            s.cluster_id = cl.id
        for gid, sids in res.origin_groups.items():
            for sid in sids:
                session.get(Signal, sid).origin_group = gid
        if res.needs_review and cl.status == "open":
            enqueue(session, "cluster", cl.id, res.assessment.value, priority=1 if res.assessment in (
                SignalAssessment.POSSIBLE_EMERGING, SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE) else 2)
        out.append(cl)
    # A cluster this run did not reproduce (its reports aged out of the window, were re-analysed,
    # or now belong to another cluster) no longer supports a current signal.
    current = {cl.id for cl in out}
    for old in session.scalars(select(SignalCluster).where(
            SignalCluster.id.not_in(current or {-1}),
            SignalCluster.assessment.in_([SignalAssessment.POSSIBLE_EMERGING.value, SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE.value]))):
        old.evidence = (old.evidence or {}) | {"superseded_on": today.isoformat(), "previous_assessment": old.assessment}
        old.assessment = SignalAssessment.INSUFFICIENT_EVIDENCE.value
    return out


def cluster_alerts(session: Session, clusters: list[SignalCluster]) -> list[Alert]:
    """Alerts from unofficial evidence are never published without human approval."""
    made = []
    for cl in clusters:
        if cl.assessment not in (SignalAssessment.POSSIBLE_EMERGING.value, SignalAssessment.OFFICIAL_MAY_BE_INCOMPLETE.value):
            continue
        if cl.status == "reviewed_not_credible":
            continue
        key = f"cluster:{cl.id}:{cl.assessment}"
        if session.scalar(select(Alert).where(Alert.dedupe_key == key)):
            continue
        a = Alert(region_id=cl.region_id, kind="unofficial_signal", message=cl.assessment, severity_level=1,
                  confidence="low", relies_on_unofficial=True, review_status="pending", published=False, dedupe_key=key,
                  evidence={"cluster_id": cl.id, "independent_origins": cl.n_independent_origins, "summary": cl.summary,
                            "languages": cl.languages, "corroboration": cl.corroboration},
                  is_synthetic=cl.is_synthetic)
        session.add(a)
        session.flush()
        enqueue(session, "alert", a.id, "alert relies on unofficial reports; human review required before publication", priority=1)
        made.append(a)
    return made
