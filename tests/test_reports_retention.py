"""Reports, retention and the full analysis stage on SYNTHETIC data."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from ebolawatch.db.models import Document, SituationReport
from ebolawatch.domain.enums import SourceCategory
from ebolawatch.pipeline.ingest import store_item
from ebolawatch.pipeline.run import analyze, apply_retention
from ebolawatch.reports.generate import generate

from .helpers import add_series, outbreak, post, source

NOW = date.today()


def test_reports_contain_required_sections_and_no_invented_numbers(session):
    ob = outbreak(session, "TZA", NOW - timedelta(days=30), key="TEST-TZA")
    add_series(session, "TZA", NOW - timedelta(days=9), [2, 3], outbreak_id=ob.id)
    session.flush()
    res = analyze(session, NOW, n_sims=200, backtests=False, reports=False)
    assert res["model_runs"] >= 1
    rep = generate(session, "country", scope=["TZA"], today=NOW)
    md = rep.content_md
    for heading in ("What is known", "What is estimated", "What may happen next", "Major uncertainties", "Disclaimer"):
        assert heading in md
    assert "Insufficient evidence for a reliable numerical estimate." in md
    assert "insufficient for numerical forecasting" in md
    assert "SYNTHETIC" not in md or "SYNTHETIC DATA PRESENT" in md


def test_multicountry_and_weekly_reports_generate(session):
    for kind in ("daily", "weekly", "multicountry", "major_change"):
        rep = generate(session, kind, today=NOW)
        assert rep.content_md.startswith("# EBOLA WATCH")
    assert session.scalar(select(SituationReport).where(SituationReport.kind == "weekly"))


def test_retention_purges_expired_text(session):
    src = source(session, "test_social", SourceCategory.SOCIAL_MEDIA)
    from ebolawatch.config import get_settings

    store_item(session, src, post("ret-1", "Ebola rumours in Goma", datetime.now(UTC)), get_settings())
    doc = session.scalar(select(Document).where(Document.external_id == "ret-1"))
    doc.retain_text_until = datetime.now(UTC) - timedelta(days=1)
    session.flush()
    out = apply_retention(session)
    session.refresh(doc)
    assert out["texts_purged"] >= 1 and doc.text_minimized is None
