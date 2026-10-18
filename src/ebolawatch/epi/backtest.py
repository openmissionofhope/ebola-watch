"""Retrospective forecast evaluation ("backtesting").

For each forecast origin, the model is refitted using only data with
observation dates up to the origin, and its forecast of new reported cases over
each horizon is compared with what was subsequently reported. Observed values
at target dates are linearly interpolated only between reports at most 16 days
apart (cumulative counts change smoothly over such gaps); otherwise the target
is skipped rather than evaluated against an invented value.

When data vintages exist, ``vintage_lookup`` reproduces exactly what was known at
each origin; otherwise the latest series truncated at the origin is used, which
ignores later backfill and is noted in the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from . import scoring
from .model import RegionInputs, run_region
from .series import CumulativeSeries

EVAL_HORIZONS = (7, 14, 28)


@dataclass
class BacktestResult:
    dataset: str
    is_synthetic: bool
    rows: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    expansion: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _observed_at(series: CumulativeSeries, d: date, max_gap: int = 16) -> float | None:
    pts = series.points
    for a, b in zip(pts, pts[1:], strict=False):
        if a.as_of <= d <= b.as_of:
            if a.as_of == d:
                return a.value
            if b.as_of == d:
                return b.value
            if (b.as_of - a.as_of).days > max_gap:
                return None
            return a.value + (b.value - a.value) * (d - a.as_of).days / (b.as_of - a.as_of).days
    return None


def backtest(cases: CumulativeSeries, deaths: CumulativeSeries, pathogen: str, dataset: str, is_synthetic: bool = False,
             origin_step_days: int = 7, min_weeks: int = 6, n_sims: int = 1000, sigma_override: float | None = None,
             affected_units: list[tuple[date, float]] | None = None) -> BacktestResult:
    res = BacktestResult(dataset, is_synthetic)
    if len(cases.points) < 3:
        res.notes.append("series too short for backtesting")
        return res
    start = cases.points[0].as_of + timedelta(days=7 * min_weeks)
    end = cases.points[-1].as_of
    origins = []
    d = start
    while d <= end - timedelta(days=min(EVAL_HORIZONS)):
        origins.append(d)
        d += timedelta(days=origin_step_days)
    rng = np.random.default_rng(7)
    seen_origins: set[date] = set()
    for o in origins:
        c_o = cases.truncated(o)
        if not c_o.points:
            continue
        # forecasts are issued from the last report available at the origin
        origin = c_o.last_date
        if origin in seen_origins:
            continue
        seen_origins.add(origin)
        inp = RegionInputs(region_code=dataset, pathogen=pathogen, confirmed_cases=c_o, confirmed_deaths=deaths.truncated(o),
                           today=origin, seed=int(rng.integers(1, 2**31)))
        if sigma_override is not None:
            from . import parameters

            params = parameters.load_parameters()
            old = params["common"]["rt_random_walk_sd_per_week"]["value"]
            params["common"]["rt_random_walk_sd_per_week"]["value"] = sigma_override
        try:
            out = run_region(inp, n_sims=n_sims, scenarios=("baseline",))
        finally:
            if sigma_override is not None:
                params["common"]["rt_random_walk_sd_per_week"]["value"] = old
        if out.status != "ok" or not out.forecasts:
            continue
        base_val = c_o.last_value
        for f in out.forecasts:
            if f.horizon_days not in EVAL_HORIZONS:
                continue
            target = origin + timedelta(days=f.horizon_days)
            obs_cum = _observed_at(cases, target)
            if obs_cum is None:
                continue
            y = max(obs_cum - base_val, 0.0)
            q = f.quantiles
            res.rows.append({
                "origin_date": origin, "horizon_days": f.horizon_days, "observed": y, "median": q["0.5"],
                "lower_50": q["0.25"], "upper_50": q["0.75"], "lower_90": q["0.05"], "upper_90": q["0.95"],
                "wis": scoring.wis(q, y), "pit": scoring.pit(f.samples, y, rng) if f.samples is not None else None,
            })
    res.summary = scoring.summarize(res.rows)
    if affected_units:
        res.expansion = _expansion_backtest(affected_units)
    if not is_synthetic:
        res.notes.append("evaluated against the latest available series truncated at each origin (real-time vintages not reconstructed)")
    return res


def _expansion_backtest(points: list[tuple[date, float]], horizon: int = 14) -> dict:
    from .expansion import forecast_expansion

    rng = np.random.default_rng(11)
    pts = sorted(points)
    probs, outcomes = [], []
    for i in range(2, len(pts)):
        o = pts[i - 1][0]
        hist = [p for p in pts if p[0] <= o]
        fut = [p for p in pts if o < p[0] <= o + timedelta(days=horizon)]
        if not fut:
            continue
        fx = forecast_expansion(hist, "units", rng, horizons=(horizon,))
        if fx.insufficient:
            continue
        probs.append(fx.p_new_unit[horizon])
        outcomes.append(int(max(v for _, v in fut) > hist[-1][1]))
    return {"horizon_days": horizon, "n": len(probs), "brier": scoring.brier(probs, outcomes),
            "base_rate": float(np.mean(outcomes)) if outcomes else None}


def calibrate_sigma(cases: CumulativeSeries, deaths: CumulativeSeries, pathogen: str, grid=(0.05, 0.1, 0.15, 0.2, 0.3)) -> dict:
    """Choose the R random-walk SD that minimises mean WIS at 14 days with 90% coverage >= 0.8."""
    results = {}
    for s in grid:
        bt = backtest(cases, deaths, pathogen, "calibration", n_sims=600, sigma_override=s)
        h = bt.summary.get("by_horizon", {}).get(14)
        if h:
            results[s] = {"mean_wis": h["mean_wis"], "coverage_90": h["coverage_90"], "n": h["n"]}
    ok = {s: r for s, r in results.items() if r["coverage_90"] >= 0.8}
    pool = ok or results
    best = min(pool, key=lambda s: pool[s]["mean_wis"]) if pool else None
    return {"grid": results, "selected": best}
