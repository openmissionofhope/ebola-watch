"""Pipeline orchestration and the background scheduler."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.base import utcnow
from ..db.models import Document, Signal
from ..db.session import session_scope
from ..reports.generate import generate
from ..review.queue import audit
from .evaluation import run_backtests
from .ingest import ingest_all
from .modeling import run_models
from .seed import seed_all
from .signals import assess_clusters, cluster_alerts, extract_signals

log = logging.getLogger("ebolawatch.pipeline")


def analyze(session: Session, today: date | None = None, n_sims: int = 2000, backtests: bool = True, reports: bool = True) -> dict:
    today = today or date.today()
    n_sig = extract_signals(session, today)
    clusters = assess_clusters(session, today)
    alerts = cluster_alerts(session, clusters)
    session.commit()
    runs = run_models(session, today, n_sims=n_sims)
    session.commit()
    bt = run_backtests(session, today) if backtests else []
    session.commit()
    reps = []
    if reports:
        reps.append(generate(session, "daily", today=today))
        if today.weekday() == 0 or not reps:
            reps.append(generate(session, "weekly", today=today))
        reps.append(generate(session, "major_change", today=today))
    session.commit()
    return {"signals": n_sig, "clusters": len(clusters), "cluster_alerts": len(alerts), "model_runs": len(runs),
            "backtests": len(bt), "reports": len(reps)}


def apply_retention(session: Session, settings: Settings | None = None) -> dict:
    """Delete stored text past its retention deadline and old signal rows (aggregated clusters remain)."""
    settings = settings or get_settings()
    now = utcnow()
    r1 = session.execute(update(Document).where(Document.retain_text_until.is_not(None), Document.retain_text_until < now,
                                                Document.text_minimized.is_not(None)).values(text_minimized=None))
    cutoff = now - timedelta(days=settings.signal_retention_days)
    r2 = session.execute(delete(Signal).where(Signal.created_at < cutoff))
    audit(session, "system", "retention", details={"count": (r1.rowcount or 0) + (r2.rowcount or 0)})
    return {"texts_purged": r1.rowcount or 0, "signals_deleted": r2.rowcount or 0}


def run_all(settings: Settings | None = None, only_sources: list[str] | None = None, skip_ingest: bool = False, n_sims: int = 2000) -> dict:
    settings = settings or get_settings()
    with session_scope() as s:
        seed_all(s, settings)
    result: dict = {}
    if not skip_ingest:
        with session_scope() as s:
            runs = ingest_all(s, settings, only=only_sources)
            result["ingest"] = [{"source": r.source_key, "status": r.status, "message": r.message, "new": r.items_new} for r in runs]
    with session_scope() as s:
        result["analysis"] = analyze(s, n_sims=n_sims)
    with session_scope() as s:
        result["retention"] = apply_retention(s, settings)
    return result


def scheduler(settings: Settings | None = None) -> None:  # pragma: no cover - long-running loop
    settings = settings or get_settings()
    next_ingest = next_retention = 0.0
    while True:
        now = time.monotonic()
        try:
            if now >= next_ingest:
                log.info("scheduled pipeline run: %s", run_all(settings))
                next_ingest = now + settings.ingest_interval_s
            if now >= next_retention:
                with session_scope() as s:
                    apply_retention(s, settings)
                next_retention = now + settings.retention_interval_s
        except Exception:
            log.exception("scheduled run failed; will retry at next interval")
            next_ingest = now + min(settings.ingest_interval_s, 1800)
        time.sleep(60)


def pending_reviews(session: Session) -> int:
    from ..db.models import ReviewItem

    return len(list(session.scalars(select(ReviewItem).where(ReviewItem.status == "pending"))))
