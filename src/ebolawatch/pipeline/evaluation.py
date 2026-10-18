"""Backtesting stage: evaluates past forecasts on real series and on synthetic
outbreaks with known truth. Results (good or bad) are stored and shown."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ForecastEvaluation, ModelRun, Region
from ..epi.backtest import backtest
from ..epi.parameters import MODEL_VERSION
from ..sources.synthetic import simulate_outbreak, to_series
from .modeling import _rows, pathogen_for, series_for


def run_backtests(session: Session, today: date | None = None, include_synthetic: bool = True) -> list[ModelRun]:
    today = today or date.today()
    runs = []
    eval_id = uuid.uuid4().hex[:12]
    for region in session.scalars(select(Region).where(Region.level == 0)):
        cases = series_for(session, region)
        if len(cases.points) < 8:
            continue
        deaths = series_for(session, region, "deaths", "confirmed")
        pathogen, _ = pathogen_for(session, region.iso3, today)
        units = [(r["as_of"], r["value"]) for r in _rows(session, [region.id], "affected_admin2_units", "confirmed")
                 if r["validation_status"] in ("auto_validated", "verified")]
        bt = backtest(cases, deaths, pathogen, dataset=f"official:{region.code}", affected_units=sorted(set(units)))
        runs.append(_store(session, bt, region.code, eval_id, region.id))
    if include_synthetic:
        for i, r_path in enumerate([None, [1.3] * 30, [0.9] * 30]):
            syn = simulate_outbreak(weeks=30, r_path=r_path, seed=100 + i, seed_cases=40 if r_path == [0.9] * 30 else 5)
            bt = backtest(to_series(syn.weekly_cases, syn.start), to_series(syn.weekly_deaths, syn.start), "BDBV",
                          dataset=f"synthetic:scenario-{i + 1}", is_synthetic=True)
            runs.append(_store(session, bt, f"SYNTHETIC-{i + 1}", eval_id, None))
    return runs


def _store(session: Session, bt, code: str, eval_id: str, region_id: int | None) -> ModelRun:
    for r in bt.rows:
        session.add(ForecastEvaluation(evaluation_run=eval_id, region_code=code, dataset=bt.dataset, is_synthetic=bt.is_synthetic,
                                       origin_date=r["origin_date"], horizon_days=r["horizon_days"], observed=r["observed"],
                                       median=r["median"], lower_50=r["lower_50"], upper_50=r["upper_50"], lower_90=r["lower_90"],
                                       upper_90=r["upper_90"], wis=r["wis"], pit=r["pit"], model_version=MODEL_VERSION))
    run = ModelRun(model_name="backtest", model_version=MODEL_VERSION, region_id=region_id, status="ok" if bt.rows else "insufficient_data",
                   parameters={"evaluation_run": eval_id, "dataset": bt.dataset},
                   diagnostics={"summary": bt.summary, "expansion": bt.expansion, "notes": bt.notes, "dataset": bt.dataset},
                   is_synthetic=bt.is_synthetic)
    session.add(run)
    session.flush()
    return run
