"""Statistical components on SYNTHETIC outbreaks with known truth."""

from datetime import date, timedelta

import numpy as np

from ebolawatch.epi.backtest import backtest
from ebolawatch.epi.burden import BurdenEstimate, combine, deaths_backcalculation, exportation_estimate
from ebolawatch.epi.model import RegionInputs, run_region
from ebolawatch.epi.renewal import estimate_rt
from ebolawatch.epi.scoring import wis
from ebolawatch.epi.series import Point, build_cumulative, weekly_incidence
from ebolawatch.sources.synthetic import simulate_outbreak, to_series

RNG = np.random.default_rng(0)


def test_rt_recovers_known_reproduction_number():
    syn = simulate_outbreak(weeks=26, r_path=[1.4] * 12 + [0.8] * 14, seed=5, seed_cases=20)
    rt = estimate_rt(syn.weekly_cases, 15.3, 9.3, (13.0, 17.5), RNG)
    assert not rt.insufficient
    assert rt.lower_90 <= 0.8 * 1.15 and rt.upper_90 >= 0.8 * 0.85  # covers the true late-phase R
    assert rt.p_above_one < 0.2


def test_series_keeps_latest_vintage_and_flags_downward_revision():
    rows = [
        {"as_of": date(2031, 1, 7), "value": 100, "source_key": "s", "published_at": 1, "id": 1, "validation_status": "verified"},
        {"as_of": date(2031, 1, 14), "value": 150, "source_key": "s", "published_at": 2, "id": 2, "validation_status": "verified"},
        {"as_of": date(2031, 1, 14), "value": 140, "source_key": "s", "published_at": 3, "id": 3, "validation_status": "verified"},
        {"as_of": date(2031, 1, 21), "value": 130, "source_key": "s", "published_at": 4, "id": 4, "validation_status": "verified"},
        {"as_of": date(2031, 1, 28), "value": 999, "source_key": "s", "published_at": 5, "id": 5, "validation_status": "pending_review"},
    ]
    s = build_cumulative(rows)
    assert [p.value for p in s.points] == [100, 140, 130]  # revised 14 Jan value used; pending row excluded
    assert s.revisions and s.revisions[0]["change"] == -10


def test_missing_reports_are_not_zero_filled():
    s = build_cumulative([{"as_of": date(2031, 1, 1), "value": 10, "source_key": "s", "id": 1, "validation_status": "verified"},
                          {"as_of": date(2031, 1, 29), "value": 38, "source_key": "s", "id": 2, "validation_status": "verified"}])
    w = weekly_incidence(s)
    assert len(w) == 4 and abs(w.counts.sum() - 28) < 1e-9 and w.interpolated_days.sum() == 28


def test_deaths_backcalculation_recovers_ascertainment():
    syn = simulate_outbreak(weeks=24, seed=11, ascertainment=0.5, ifr=0.35, seed_cases=10)
    est = deaths_backcalculation(to_series(syn.weekly_cases, syn.start), to_series(syn.weekly_deaths, syn.start),
                                 (0.25, 0.45), (0.7, 0.9), (6.0, 9.0), (2.0, 5.0), RNG)
    assert not est.insufficient
    true_total = syn.weekly_infections.sum()
    assert est.lower_90 <= true_total * 1.25 and est.upper_90 >= true_total * 0.75
    assert est.ascertainment["lower_90"] <= 0.5 * 1.3 and est.ascertainment["upper_90"] >= 0.5 * 0.7


def test_deaths_backcalculation_insufficient_with_few_deaths():
    c = to_series(np.array([2, 3, 4.0]), date(2031, 1, 1))
    d = to_series(np.array([0, 1, 1.0]), date(2031, 1, 1))
    est = deaths_backcalculation(c, d, (0.2, 0.5), (0.5, 0.95), (7, 12), (3, 10), RNG)
    assert est.insufficient and "deaths" in est.reason


def test_exportation_requires_sourced_mobility():
    est = exportation_estimate(2, 0, (0, 0, 0), (11, 18), (0.5, 1.0), RNG)
    assert est.insufficient
    est2 = exportation_estimate(2, 5_000_000, (500, 1000, 2000), (11, 18), (0.5, 1.0), RNG, citation="SYNTHETIC")
    assert not est2.insufficient and est2.lower_90 < est2.median < est2.upper_90


def test_scenario_14_disagreeing_models_are_shown_not_averaged():
    a = BurdenEstimate("deaths_backcalculation", "q", False, median=1000, lower_90=800, upper_90=1300)
    b = BurdenEstimate("exportation", "q", False, median=9000, lower_90=6000, upper_90=14000)
    h = combine([a, b], data_age_days=3, weeks_of_data=10)
    assert h["disagreement"]["substantial"] and h["confidence"] == "low"
    assert h["lower_90"] == 800 and h["upper_90"] == 14000  # envelope, not an average
    # forecast models: an abrupt change makes renewal and log-linear trend disagree
    inc = np.array([5, 8, 12, 20, 35, 60, 100, 160, 260, 400, 30, 25], dtype=float)
    syn_cases = to_series(inc, date(2031, 1, 1))
    syn_deaths = to_series(inc * 0.3, date(2031, 1, 1))
    out = run_region(RegionInputs("ZZZ", "BDBV", syn_cases, syn_deaths, today=date(2031, 3, 27)), n_sims=600)
    assert out.model_comparison.get("compared")
    assert "substantial_disagreement" in out.model_comparison


def test_scenario_13_insufficient_observations_for_forecasting():
    c = to_series(np.array([1, 2.0]), date(2031, 1, 1))
    d = to_series(np.array([0, 1.0]), date(2031, 1, 1))
    out = run_region(RegionInputs("ZZZ", "BDBV", c, d, today=date(2031, 1, 16)), n_sims=200)
    assert not out.forecasts and out.status == "insufficient_data"
    assert out.burden_headline["insufficient"]
    assert out.burden_headline["message"] == "Insufficient evidence for a reliable numerical estimate."


def test_scenario_01_two_week_reporting_delay_widens_nowcast():
    syn = simulate_outbreak(weeks=20, seed=4, seed_cases=10)
    c, d = to_series(syn.weekly_cases, syn.start), to_series(syn.weekly_deaths, syn.start)
    last = c.last_date
    current = run_region(RegionInputs("ZZZ", "BDBV", c, d, today=last + timedelta(days=1)), n_sims=800)
    delayed = run_region(RegionInputs("ZZZ", "BDBV", c, d, today=last + timedelta(days=14)), n_sims=800)
    assert delayed.data_age_days == 14 and delayed.nowcast_reported["gap_days"] == 14
    w_cur = current.nowcast_reported["upper_90"] - current.nowcast_reported["lower_90"]
    w_del = delayed.nowcast_reported["upper_90"] - delayed.nowcast_reported["lower_90"]
    assert w_del > w_cur
    assert delayed.nowcast_reported["median"] > c.last_value  # unpublished cases are projected, not assumed zero


def test_forecast_intervals_cover_truth_on_synthetic_backtest():
    syn = simulate_outbreak(weeks=30, seed=21, seed_cases=10)
    bt = backtest(to_series(syn.weekly_cases, syn.start), to_series(syn.weekly_deaths, syn.start), "BDBV", "synthetic:test",
                  is_synthetic=True, n_sims=500)
    h14 = bt.summary["by_horizon"][14]
    assert h14["n"] >= 10 and h14["coverage_90"] >= 0.7


def test_wis_is_zero_for_perfect_point_forecast_and_grows_with_error():
    q = {"0.05": 10, "0.25": 10, "0.5": 10, "0.75": 10, "0.95": 10}
    assert wis(q, 10) == 0
    assert wis(q, 30) > wis(q, 15) > 0


def test_small_outbreak_can_go_extinct_in_simulation():
    inc = np.array([2, 3, 2, 4, 3, 2, 1, 1], dtype=float)
    c = to_series(inc, date(2031, 1, 1))
    d = to_series(np.array([0, 1, 1, 1, 2, 1, 0, 0], dtype=float), date(2031, 1, 1))
    out = run_region(RegionInputs("ZZZ", "SUDV", c, d, today=date(2031, 2, 27)), n_sims=1000)
    p = [f.p_continued_transmission for f in out.forecasts if f.scenario == "baseline" and f.horizon_days == 56]
    assert p and p[0] < 0.95


def test_point_dataclass_roundtrip():
    p = Point(date(2031, 1, 1), 5.0, "s")
    assert p.value == 5.0
