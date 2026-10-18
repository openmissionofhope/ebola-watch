"""Geographic expansion of an existing outbreak.

Empirical model: the number of newly affected administrative units (health
zones, or provinces) per week is Poisson with a rate given a Gamma posterior
from the recent record of affected-unit counts. This answers "how likely is at
least one newly affected unit in the next h days" from the outbreak's own
history, without assuming mobility volumes.

Network ranking (see transport.analysis) adds *where* expansion is more likely,
as a scenario-based relative ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np


@dataclass
class ExpansionForecast:
    insufficient: bool
    reason: str | None
    unit: str
    weekly_rate_median: float | None = None
    weekly_rate_90: tuple[float, float] | None = None
    p_new_unit: dict[int, float] | None = None  # horizon_days -> P(>=1 new unit)
    expected_new_units: dict[int, dict] | None = None
    observations_used: int = 0
    window_days: int = 0


def forecast_expansion(points: list[tuple[date, float]], unit: str, rng: np.random.Generator,
                       lookback_days: int = 42, horizons=(7, 14, 21, 28), n: int = 4000) -> ExpansionForecast:
    """points: (as_of, cumulative number of affected units), sorted by date."""
    pts = sorted(points)
    if len(pts) < 2:
        return ExpansionForecast(True, "fewer than two reports of affected-unit counts", unit)
    end = pts[-1][0]
    window = [p for p in pts if (end - p[0]).days <= lookback_days]
    if len(window) < 2:
        window = pts[-2:]
    start = window[0]
    days = (end - start[0]).days
    if days < 7:
        return ExpansionForecast(True, "reports span less than one week", unit)
    new_units = max(window[-1][1] - start[1], 0)
    # Gamma(0.5 + k, rate = exposure weeks) posterior on the weekly rate (Jeffreys prior)
    weeks = days / 7
    rate = rng.gamma(0.5 + new_units, 1 / weeks, size=n)
    p_new, expected = {}, {}
    for h in horizons:
        lam = rate * h / 7
        draws = rng.poisson(lam)
        p_new[h] = float((draws >= 1).mean())
        q = np.quantile(draws, [0.05, 0.5, 0.95])
        expected[h] = {"lower_90": float(q[0]), "median": float(q[1]), "upper_90": float(q[2])}
    rq = np.quantile(rate, [0.05, 0.5, 0.95])
    return ExpansionForecast(False, None, unit, float(rq[1]), (float(rq[0]), float(rq[2])), p_new, expected, len(window), days)
