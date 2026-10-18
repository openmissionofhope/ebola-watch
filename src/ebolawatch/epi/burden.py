"""Estimation of true epidemic size beyond reported counts.

Every method returns a distribution together with the assumptions that produce
it, or an explicit *insufficient evidence* result. No method applies an
arbitrary multiplier for "weak surveillance": under-ascertainment is inferred
from deaths, exportations or published estimates, or not at all.

Methods
-------
``deaths_backcalculation``
    Reported deaths at time t reflect fatal symptomatic infections with onset
    about one onset-to-death delay earlier. With a death-ascertainment fraction
    p_D and a symptomatic infection-fatality ratio IFR (species-specific prior),
    symptomatic infections with onset by t - d are D(t) / (p_D * IFR). Comparing
    with cases reported by then gives the case-ascertainment fraction rho, which
    is applied to cases reported by t. Draws where the assumptions imply fewer
    infections than reported cases are counted and reported as inconsistent
    (rho is capped at 1 in those draws).

``exportation``
    Cases detected after travel to places with strong surveillance, divided by
    the per-case probability of travel and detection (daily travellers /
    catchment population x detection window x detection probability). Requires a
    sourced mobility entry; otherwise insufficient. Medically evacuated patients
    are never counted as exportations.

``reported_floor``
    Confirmed (+ probable) reported cases: a floor, not an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .parameters import beta_from_range
from .series import CumulativeSeries

MIN_DEATHS = 20
MIN_POINTS = 3


@dataclass
class BurdenEstimate:
    method: str
    quantity: str
    insufficient: bool
    reason: str | None = None
    median: float | None = None
    lower_90: float | None = None
    upper_90: float | None = None
    lower_50: float | None = None
    upper_50: float | None = None
    ascertainment: dict | None = None
    assumptions: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    samples: np.ndarray | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "samples"}
        return d


def _q(x: np.ndarray) -> dict:
    q = np.quantile(x, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {"lower_90": float(q[0]), "lower_50": float(q[1]), "median": float(q[2]), "upper_50": float(q[3]), "upper_90": float(q[4])}


def deaths_backcalculation(cases: CumulativeSeries, deaths: CumulativeSeries, ifr_range: tuple[float, float],
                           death_ascertainment: tuple[float, float], onset_to_death_mean_range: tuple[float, float],
                           onset_to_report_mean_range: tuple[float, float], rng: np.random.Generator,
                           n: int = 4000, quantity: str = "cumulative_symptomatic_infections") -> BurdenEstimate:
    assumptions = [
        f"Symptomatic infection-fatality ratio between {ifr_range[0]:.0%} and {ifr_range[1]:.0%} (species-specific prior)",
        f"Between {death_ascertainment[0]:.0%} and {death_ascertainment[1]:.0%} of fatal infections appear in reported deaths",
        f"Mean onset-to-death delay {onset_to_death_mean_range[0]:g}-{onset_to_death_mean_range[1]:g} days; "
        f"mean onset-to-report delay {onset_to_report_mean_range[0]:g}-{onset_to_report_mean_range[1]:g} days",
        "Reported deaths and cases use the same case definition (e.g. confirmed deaths among confirmed cases)",
    ]
    if len(cases.points) < MIN_POINTS or len(deaths.points) < MIN_POINTS:
        return BurdenEstimate("deaths_backcalculation", quantity, True, "fewer than three reports of cases and deaths", assumptions=assumptions)
    t_end = min(cases.last_date, deaths.last_date)
    d_now = deaths.value_at(t_end)
    c_now = cases.value_at(t_end)
    if d_now is None or c_now is None or d_now < MIN_DEATHS:
        return BurdenEstimate("deaths_backcalculation", quantity, True,
                              f"fewer than {MIN_DEATHS} reported deaths; mortality-based inference unreliable", assumptions=assumptions)

    dist_ifr = beta_from_range(*ifr_range)
    ifr = np.clip(dist_ifr.rvs(size=n, random_state=rng), 0.02, 0.98)
    p_d = rng.uniform(*death_ascertainment, size=n)
    lag_death = rng.uniform(*onset_to_death_mean_range, size=n)
    lag_report = rng.uniform(*onset_to_report_mean_range, size=n)

    rho = np.full(n, np.nan)
    first = cases.points[0].as_of
    for i in range(n):
        # cases with onset by (t_end - lag_death) are reported by about (t_end - lag_death + lag_report)
        onset_cut_days = lag_death[i]
        report_date = t_end - _days(onset_cut_days - lag_report[i])
        if report_date < first:
            continue
        c_onset = cases.value_at(min(report_date, t_end))
        if c_onset is None or c_onset <= 0:
            continue
        infections_onset = d_now / (p_d[i] * ifr[i])
        rho[i] = c_onset / infections_onset
    ok = ~np.isnan(rho)
    if ok.sum() < n * 0.5:
        return BurdenEstimate("deaths_backcalculation", quantity, True, "series too short relative to the reporting delays", assumptions=assumptions)
    rho = rho[ok]
    inconsistent = float((rho > 1).mean())
    rho = np.minimum(rho, 1.0)
    total = c_now / rho
    q = _q(total)
    diag = {
        "reported_cases_at_t": c_now, "reported_deaths_at_t": d_now, "as_of": t_end.isoformat(),
        "crude_cfr_reported": d_now / c_now if c_now else None,
        "fraction_draws_inconsistent": inconsistent,
    }
    est = BurdenEstimate("deaths_backcalculation", quantity, False, None, ascertainment=_q(rho), assumptions=assumptions,
                         diagnostics=diag, samples=total, **q)
    if inconsistent > 0.5:
        est.diagnostics["warning"] = ("in most draws the assumptions imply fewer infections than reported cases; the "
                                      "IFR or death-ascertainment priors may not fit this outbreak")
    return est


def _days(x: float):
    from datetime import timedelta

    return timedelta(days=float(x))


def exportation_estimate(exported_cases: int, catchment_population: float, daily_travellers: tuple[float, float, float],
                         detection_window_days: tuple[float, float], detection_probability: tuple[float, float],
                         rng: np.random.Generator, n: int = 4000, citation: str | None = None) -> BurdenEstimate:
    assumptions = [
        "Exported cases are those detected after travel; medically evacuated patients are excluded",
        f"Daily travellers from the catchment: low {daily_travellers[0]:g}, central {daily_travellers[1]:g}, high {daily_travellers[2]:g}"
        + (f" ({citation})" if citation else ""),
        f"Detection window {detection_window_days[0]:g}-{detection_window_days[1]:g} days; destination detection probability "
        f"{detection_probability[0]:.0%}-{detection_probability[1]:.0%}",
        "Infected people travel at the same rate as the general catchment population (likely violated: illness reduces travel)",
    ]
    if catchment_population <= 0 or daily_travellers[1] <= 0:
        return BurdenEstimate("exportation", "cumulative_symptomatic_infections", True,
                              "no sourced mobility data configured for this catchment", assumptions=assumptions)
    if exported_cases < 1:
        return BurdenEstimate("exportation", "cumulative_symptomatic_infections", True,
                              "no exported cases detected; the method gives only a weak upper-bound signal", assumptions=assumptions)
    x = rng.gamma(exported_cases + 0.5, 1.0, size=n)  # Jeffreys posterior on the exportation rate
    lo, mid, hi = daily_travellers
    v = rng.triangular(lo, mid, hi, size=n)
    T = rng.uniform(*detection_window_days, size=n)
    p = rng.uniform(*detection_probability, size=n)
    prob = v / catchment_population * T * p
    total = x / prob
    return BurdenEstimate("exportation", "cumulative_symptomatic_infections", False, assumptions=assumptions,
                          diagnostics={"exported_cases": exported_cases}, samples=total, **_q(total))


def reported_floor(confirmed: float | None, probable: float | None) -> BurdenEstimate:
    if confirmed is None:
        return BurdenEstimate("reported_floor", "reported_cases", True, "no reported cases")
    total = confirmed + (probable or 0)
    return BurdenEstimate("reported_floor", "reported_cases", False, median=total, lower_90=total, upper_90=total,
                          lower_50=total, upper_50=total,
                          assumptions=["Floor only: confirmed plus probable reported cases; not an estimate of true burden"])


def combine(estimates: list[BurdenEstimate], data_age_days: int | None, weeks_of_data: int) -> dict:
    """Headline estimate, confidence and model-disagreement summary.

    The headline is never an average of disagreeing models: when 90% intervals
    do not overlap, the envelope of both is reported and confidence is low.
    """
    usable = [e for e in estimates if not e.insufficient and e.method != "reported_floor"]
    floor = next((e for e in estimates if e.method == "reported_floor" and not e.insufficient), None)
    if not usable:
        return {"insufficient": True, "message": "Insufficient evidence for a reliable numerical estimate.",
                "reasons": [e.reason for e in estimates if e.insufficient and e.reason], "confidence": None, "disagreement": None}
    lo = min(e.lower_90 for e in usable)
    hi = max(e.upper_90 for e in usable)
    disagreement = None
    if len(usable) >= 2:
        a, b = usable[0], usable[1]
        overlap = not (a.upper_90 < b.lower_90 or b.upper_90 < a.lower_90)
        disagreement = {"methods": [a.method, b.method], "intervals_overlap": overlap,
                        "medians": {a.method: a.median, b.method: b.median}, "substantial": not overlap}
    primary = usable[0]
    if floor and floor.median:
        lo = max(lo, floor.median)
    width_ratio = (primary.upper_90 + 1) / (primary.lower_90 + 1)
    if disagreement and disagreement["substantial"]:
        confidence = "low"
    elif data_age_days is not None and data_age_days > 14:
        confidence = "low"
    elif width_ratio > 4 or primary.diagnostics.get("fraction_draws_inconsistent", 0) > 0.2:
        confidence = "low"
    elif len(usable) >= 2 and weeks_of_data >= 8 and (data_age_days or 0) <= 7:
        confidence = "high"
    else:
        confidence = "moderate"
    return {
        "insufficient": False, "lower_90": lo if disagreement and disagreement["substantial"] else max(primary.lower_90, floor.median if floor else 0),
        "upper_90": hi if disagreement and disagreement["substantial"] else primary.upper_90,
        "median": primary.median, "primary_method": primary.method, "confidence": confidence, "disagreement": disagreement,
    }
