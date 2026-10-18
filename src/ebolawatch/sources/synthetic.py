"""Synthetic outbreak generator for tests, calibration checks and demonstrations.

Everything produced here is flagged ``is_synthetic`` end to end, carries the
fictional region prefix ``ZZ`` where it creates places, and is labelled
SYNTHETIC in every interface. It must never be loaded into a production
database (the CLI refuses unless --i-understand-this-is-synthetic is given and
the environment is not production).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from ..epi.renewal import weekly_si
from ..epi.series import CumulativeSeries, Point


@dataclass
class SyntheticOutbreak:
    start: date
    weekly_cases: np.ndarray  # true reported (ascertained) weekly cases
    weekly_infections: np.ndarray
    weekly_deaths: np.ndarray
    r_path: np.ndarray
    ascertainment: float
    ifr: float


def simulate_outbreak(weeks: int = 30, r_path: list[float] | None = None, seed: int = 1, seed_cases: float = 5,
                      ascertainment: float = 0.6, ifr: float = 0.35, si_mean: float = 15.3, si_sd: float = 9.3,
                      start: date = date(2031, 1, 6)) -> SyntheticOutbreak:
    rng = np.random.default_rng(seed)
    if r_path is None:
        r_path = list(np.concatenate([np.full(10, 1.6), np.linspace(1.6, 0.8, 10), np.full(weeks - 20, 0.85)]))
    r = np.array(r_path[:weeks], dtype=float)
    w = weekly_si(si_mean, si_sd)
    inf = np.zeros(weeks)
    inf[0] = seed_cases / ascertainment
    for t in range(1, weeks):
        lam = sum(inf[t - k] * w[k] for k in range(1, min(t, len(w) - 1) + 1))
        mean = r[t] * lam
        inf[t] = rng.poisson(rng.gamma(20, mean / 20)) if mean > 0 else 0
    cases = rng.binomial(inf.astype(int), ascertainment).astype(float)
    deaths = np.zeros(weeks)
    for t in range(weeks):
        fatal = rng.binomial(int(inf[t]), ifr)
        reported = rng.binomial(fatal, 0.8)
        if t + 1 < weeks:
            deaths[t + 1] += reported  # ~1 week onset-to-death lag at weekly resolution
    return SyntheticOutbreak(start, cases, inf, deaths, r, ascertainment, ifr)


def to_series(weekly: np.ndarray, start: date, step_days: int = 7, source_key: str = "synthetic") -> CumulativeSeries:
    cum = np.cumsum(weekly)
    pts = [Point(start + timedelta(days=step_days * (i + 1)), float(v), source_key) for i, v in enumerate(cum)]
    return CumulativeSeries(pts)
