"""Region-level modelling: nowcast, R_t, burden, forecasts and expansion.

``run_region`` is pure (no database access) so it can be unit-tested and reused
by the backtesting harness on truncated series.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .burden import BurdenEstimate, combine, deaths_backcalculation, exportation_estimate, reported_floor
from .expansion import ExpansionForecast, forecast_expansion
from .forecast import (
    SCENARIOS,
    HorizonForecast,
    compare_models,
    loglinear_forecast,
    simulate,
    summarize,
)
from .parameters import MODEL_VERSION, load_parameters, pathogen_params
from .renewal import RtResult, estimate_rt, growth_rate, weekly_si
from .series import CumulativeSeries, weekly_incidence

MIN_WEEKS_FOR_FORECAST = 4
MIN_CASES_FOR_FORECAST = 10
MAX_DATA_AGE_FOR_FORECAST = 28


@dataclass
class RegionInputs:
    region_code: str
    pathogen: str
    confirmed_cases: CumulativeSeries
    confirmed_deaths: CumulativeSeries
    probable_cases: CumulativeSeries | None = None
    affected_units: list[tuple[date, float]] = field(default_factory=list)
    affected_unit_label: str = "health zones"
    exported_cases: int = 0
    mobility: dict | None = None
    today: date | None = None
    seed: int = 20261018


@dataclass
class RegionModelOutput:
    region_code: str
    status: str  # ok | insufficient_data
    data_as_of: date | None
    data_age_days: int | None
    weeks_of_data: int
    reasons: list[str]
    rt: RtResult | None
    growth: dict | None
    nowcast_reported: dict | None
    forecasts: list[HorizonForecast]
    infection_forecasts: list[HorizonForecast]
    model_comparison: dict
    burden: list[BurdenEstimate]
    burden_headline: dict
    recent_infections: dict | None
    expansion: ExpansionForecast | None
    weekly: dict
    parameters: dict
    inputs_hash: str
    model_version: str = MODEL_VERSION


def _hash_inputs(inp: RegionInputs) -> str:
    payload = {
        "c": [(p.as_of.isoformat(), p.value) for p in inp.confirmed_cases.points],
        "d": [(p.as_of.isoformat(), p.value) for p in inp.confirmed_deaths.points],
        "u": [(d.isoformat(), v) for d, v in inp.affected_units], "x": inp.exported_cases, "p": inp.pathogen,
        "t": inp.today.isoformat() if inp.today else None, "v": MODEL_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run_region(inp: RegionInputs, n_sims: int = 2000, scenarios: tuple[str, ...] = ("improving", "baseline", "deteriorating")) -> RegionModelOutput:
    rng = np.random.default_rng(inp.seed)
    params = load_parameters()
    common = params["common"]
    pp = pathogen_params(inp.pathogen, params)
    today = inp.today or date.today()
    cases = inp.confirmed_cases
    reasons: list[str] = []
    as_of = cases.last_date
    age = (today - as_of).days if as_of else None

    weekly = weekly_incidence(cases)
    inc = weekly.counts
    n_weeks = len(weekly)
    weekly_out = {
        "week_ends": [d.isoformat() for d in weekly.week_ends],
        "reported_confirmed": [float(x) for x in inc],
        "interpolated_days": [int(x) for x in weekly.interpolated_days],
        "max_reporting_gap_days": weekly.max_gap_days,
    }

    si = common["serial_interval"]
    recent_pts = [p for p in cases.points if as_of and (as_of - p.as_of).days <= 42]
    gaps = [(b.as_of - a.as_of).days for a, b in zip(recent_pts, recent_pts[1:], strict=False)]
    reporting_interval = float(np.mean(gaps)) if gaps else 7.0
    weekly_out["mean_recent_reporting_interval_days"] = reporting_interval
    rt = RtResult(True, "no incidence data")
    if n_weeks:
        # Small outbreaks: pool over a longer window rather than declare R_t unidentifiable at once
        for window in (2, 4, 6):
            rt = estimate_rt(inc, si["mean"], si["sd"], tuple(si["mean_range"]), rng, window=window,
                             extra_dispersion=reporting_interval / 7)
            if not rt.insufficient:
                break
    if rt.history:
        for h in rt.history:
            h["week_end"] = weekly.week_ends[h.pop("index")].isoformat()
    gr = growth_rate(inc) if n_weeks else None
    growth = None
    if gr:
        r, se = gr
        growth = {"weekly_log_growth": r, "se": se,
                  "doubling_or_halving_weeks": float(np.log(2) / abs(r)) if abs(r) > 1e-6 else None,
                  "direction": "growing" if r - 1.64 * se > 0 else "declining" if r + 1.64 * se < 0 else "uncertain"}

    forecasts: list[HorizonForecast] = []
    infection_forecasts: list[HorizonForecast] = []
    comparison: dict = {"compared": False}
    nowcast = None
    recent_inf = None

    total_cases = cases.last_value or 0
    can_forecast = True
    if n_weeks < MIN_WEEKS_FOR_FORECAST:
        can_forecast = False
        reasons.append(f"fewer than {MIN_WEEKS_FOR_FORECAST} weeks of reported data")
    if total_cases < MIN_CASES_FOR_FORECAST:
        can_forecast = False
        reasons.append(f"fewer than {MIN_CASES_FOR_FORECAST} cumulative reported cases")
    if age is not None and age > MAX_DATA_AGE_FOR_FORECAST:
        can_forecast = False
        reasons.append(f"latest data are {age} days old (> {MAX_DATA_AGE_FOR_FORECAST}); no current forecast")
    if rt.insufficient:
        can_forecast = False
        reasons.append(f"R_t: {rt.reason}")

    w = weekly_si(si["mean"], si["sd"])
    sigma = common["rt_random_walk_sd_per_week"]["value"]
    k_obs = max(5.0, min(200.0, float(np.mean(inc[-8:])) / max(rt.dispersion - 1, 0.05))) if n_weeks else 10.0
    k_off = common["offspring_dispersion_k"]["central"]

    # Burden (needed for infection-scale outputs)
    burden: list[BurdenEstimate] = []
    burden.append(deaths_backcalculation(
        cases, inp.confirmed_deaths, tuple(pp["ifr_symptomatic"]["range"]), tuple(common["death_ascertainment"]["range"]),
        tuple(common["onset_to_death"]["mean_range"]), tuple(common["onset_to_report"]["mean_range"]), rng))
    if inp.mobility:
        m = inp.mobility
        burden.append(exportation_estimate(
            inp.exported_cases, m["catchment_population"],
            (m["daily_travellers"]["low"], m["daily_travellers"]["central"], m["daily_travellers"]["high"]),
            (common["incubation_mean_days"]["value"], common["incubation_mean_days"]["value"] + 7),
            tuple(m.get("destination_detection_probability", [0.5, 1.0])), rng, citation=m.get("citation")))
    else:
        burden.append(BurdenEstimate("exportation", "cumulative_symptomatic_infections", True,
                                     "no sourced mobility data configured; exportation method not applied",
                                     diagnostics={"exported_cases_detected": inp.exported_cases}))
    probable = inp.probable_cases.last_value if inp.probable_cases and inp.probable_cases.points else None
    burden.append(reported_floor(cases.last_value, probable))
    headline = combine(burden, age, n_weeks)
    rho_samples = None
    db = burden[0]
    if not db.insufficient and db.samples is not None and cases.last_value:
        rho_samples = np.clip(cases.last_value / db.samples, 1e-3, 1.0)

    if can_forecast:
        delay_weeks = int(round((common["incubation_mean_days"]["value"] + common["onset_to_report"]["mean"]) / 7))
        sims_by_scenario = {}
        for sc in scenarios:
            sims = simulate(inc, rt.samples, w, weeks=12 + delay_weeks + 2, drift=SCENARIOS[sc], sigma_rw=sigma,
                            k_obs=k_obs, k_offspring=k_off, rng=rng, n_sims=n_sims)
            sims_by_scenario[sc] = sims
            forecasts.extend(summarize(sims, sc))
            if rho_samples is not None:
                scale = rng.choice(rho_samples, size=sims.shape[0])
                infection_forecasts.extend(summarize(sims, sc, target="new_symptomatic_infections", scale=scale, shift_weeks=delay_weeks))
        comparison = compare_models([f for f in forecasts if f.scenario == "baseline"], loglinear_forecast(inc, rng))
        base = sims_by_scenario.get("baseline")
        # Publication-delay nowcast: reported cases between the data date and today
        if base is not None and age is not None and age > 0:
            wk = max(1, int(np.ceil(age / 7)))
            frac = age / (7 * wk)
            add = base[:, :wk].sum(axis=1) * frac
            q = np.quantile(cases.last_value + add, [0.05, 0.5, 0.95])
            nowcast = {"as_of": today.isoformat(), "data_as_of": as_of.isoformat(), "gap_days": age,
                       "median": float(q[1]), "lower_90": float(q[0]), "upper_90": float(q[2]),
                       "note": "projected cumulative reported confirmed cases up to today, accounting for the reporting gap"}
        if base is not None and rho_samples is not None:
            seg = base[:, delay_weeks:delay_weeks + 2].sum(axis=1)
            scale = rng.choice(rho_samples, size=seg.shape[0])
            q = np.quantile(seg / scale, [0.05, 0.25, 0.5, 0.75, 0.95])
            recent_inf = {"period_days": 14, "median": float(q[2]), "lower_90": float(q[0]), "upper_90": float(q[4]),
                          "lower_50": float(q[1]), "upper_50": float(q[3]),
                          "method": "renewal projection of cases to be reported over the next infection-to-report delay, divided by estimated ascertainment",
                          "note": "infections in the last 14 days are mostly not yet reported; this is a model estimate"}

    expansion = None
    if inp.affected_units:
        expansion = forecast_expansion(inp.affected_units, inp.affected_unit_label, rng)

    status = "ok" if (can_forecast or not headline.get("insufficient")) else "insufficient_data"
    used_params = {
        "serial_interval": si, "onset_to_death": common["onset_to_death"], "onset_to_report": common["onset_to_report"],
        "death_ascertainment": common["death_ascertainment"], "ifr_symptomatic": pp["ifr_symptomatic"],
        "cfr_reported": pp["cfr_reported"], "rt_random_walk_sd_per_week": sigma, "k_obs": k_obs,
        "offspring_dispersion_k": k_off, "scenario_weekly_drift": SCENARIOS, "parameters_version": params["version"],
    }
    return RegionModelOutput(
        region_code=inp.region_code, status=status, data_as_of=as_of, data_age_days=age, weeks_of_data=n_weeks,
        reasons=reasons, rt=rt, growth=growth, nowcast_reported=nowcast, forecasts=forecasts,
        infection_forecasts=infection_forecasts, model_comparison=comparison, burden=burden, burden_headline=headline,
        recent_infections=recent_inf, expansion=expansion, weekly=weekly_out, parameters=used_params,
        inputs_hash=_hash_inputs(inp),
    )


def forecast_confidence(horizon_days: int, data_age_days: int | None, weeks: int, rt: RtResult | None,
                        calibration: dict | None = None) -> str:
    if horizon_days > 28 or data_age_days is None or data_age_days > 14 or weeks < 6:
        return "low"
    if rt is None or rt.insufficient or (rt.upper_90 and rt.lower_90 and rt.upper_90 / max(rt.lower_90, 1e-3) > 2.5):
        return "low"
    cov = None
    if calibration:
        cov = (calibration.get("by_horizon", {}).get(horizon_days) or calibration.get("by_horizon", {}).get(str(horizon_days)) or {}).get("coverage_90")
    if horizon_days <= 14 and data_age_days <= 7 and cov is not None and 0.8 <= cov <= 0.98:
        return "high"
    return "moderate"
