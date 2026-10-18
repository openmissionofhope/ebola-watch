"""Probabilistic forecasts of reported cases and scenario projections.

Model A (primary): renewal / branching simulation.
    R evolves as a log-normal random walk with a scenario-specific drift;
    weekly reported cases are negative-binomial around R_t * Lambda_t. When
    infectiousness is small the offspring-level dispersion k is used instead,
    so small outbreaks can go extinct in simulation (probability of continued
    transmission is then informative).

Model B (comparison): log-linear growth extrapolation of recent weeks.

Horizons beyond 28 days are labelled scenarios: assumptions about response and
surveillance dominate them. Substantial disagreement between A and B is
reported, not averaged away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

HORIZONS_DAYS = [7, 14, 21, 28, 42, 56, 84]
SCENARIO_HORIZON_DAYS = 28  # beyond this, outputs are scenarios
QUANTILES = [0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975]
SCENARIOS = {
    "improving": float(np.log(0.9)),  # R falls ~10% per week for 4 weeks
    "baseline": 0.0,
    "deteriorating": float(np.log(1.1)),  # R rises ~10% per week for 4 weeks
}
R_CAP = 3.0  # above the reproduction numbers reported for Ebola; prevents runaway tails
SCENARIO_SHIFT_WEEKS = 4  # scenario drift applies for 4 weeks, then R plateaus (x0.66 / x1.46)


@dataclass
class HorizonForecast:
    horizon_days: int
    scenario: str
    target: str
    quantiles: dict[str, float]
    p_continued_transmission: float | None
    is_scenario: bool
    samples: np.ndarray | None = field(default=None, repr=False)


def _nb(rng: np.random.Generator, mean: np.ndarray, size: np.ndarray) -> np.ndarray:
    mean = np.maximum(mean, 0)
    size = np.maximum(size, 1e-3)
    lam = rng.gamma(size, np.where(mean > 0, mean / size, 0.0))
    return rng.poisson(lam)


def simulate(history: np.ndarray, r_samples: np.ndarray, w: np.ndarray, weeks: int, drift: float, sigma_rw: float,
             k_obs: float, k_offspring: float, rng: np.random.Generator, n_sims: int = 2000) -> np.ndarray:
    """Return array (n_sims, weeks) of simulated weekly reported cases."""
    hist = np.asarray(history, dtype=float)
    L = len(w) - 1
    pad = np.zeros(max(0, L - len(hist)))
    base = np.concatenate([pad, hist[-L:]])
    R = rng.choice(r_samples, size=n_sims, replace=True)
    buf = np.tile(base, (n_sims, 1))  # last L weeks per sim
    out = np.zeros((n_sims, weeks))
    wk = w[1:][::-1]  # align: buf[:, -1] is lag 1
    for t in range(weeks):
        step_drift = drift if t < SCENARIO_SHIFT_WEEKS else 0.0
        R = np.minimum(R * np.exp(step_drift + sigma_rw * rng.standard_normal(n_sims)), R_CAP)
        lam = buf @ wk
        mean = R * lam
        size = np.where(lam >= 50, k_obs, np.maximum(k_offspring * lam, 0.05))
        x = _nb(rng, mean, size)
        out[:, t] = x
        buf = np.concatenate([buf[:, 1:], x[:, None]], axis=1)
    return out


def summarize(sims: np.ndarray, scenario: str, target: str = "new_reported_confirmed", scale: np.ndarray | None = None,
              shift_weeks: int = 0) -> list[HorizonForecast]:
    out = []
    for h in HORIZONS_DAYS:
        hw = h // 7
        seg = sims[:, shift_weeks:shift_weeks + hw]
        if seg.shape[1] < hw:
            continue
        total = seg.sum(axis=1).astype(float)
        if scale is not None:
            total = total / scale
        q = np.quantile(total, QUANTILES)
        cont = float((sims[:, shift_weeks + hw - 1] > 0).mean())
        out.append(HorizonForecast(h, scenario, target, {str(k): float(v) for k, v in zip(QUANTILES, q, strict=False)},
                                   cont, h > SCENARIO_HORIZON_DAYS, total))
    return out


def loglinear_forecast(incidence: np.ndarray, rng: np.random.Generator, weeks_fit: int = 6, n_sims: int = 2000) -> list[HorizonForecast] | None:
    """Model B: extrapolate a log-linear trend with parameter and Poisson noise."""
    from .renewal import growth_rate

    gr = growth_rate(incidence, weeks_fit)
    if gr is None:
        return None
    r, se = gr
    level = float(np.mean(incidence[-2:]))
    if level <= 0:
        return None
    rs = rng.normal(r, se, size=n_sims)
    max_w = max(HORIZONS_DAYS) // 7
    t = np.arange(1, max_w + 1)
    means = level * np.exp(np.outer(rs, t + 0.5))
    means = np.minimum(means, 1e7)
    sims = rng.poisson(means)
    return summarize(sims, "baseline", target="new_reported_confirmed_loglinear")


def compare_models(a: list[HorizonForecast], b: list[HorizonForecast] | None, horizon: int = 28) -> dict:
    if not b:
        return {"compared": False, "reason": "comparison model not identifiable"}
    fa = next((f for f in a if f.horizon_days == horizon), None)
    fb = next((f for f in b if f.horizon_days == horizon), None)
    if not fa or not fb:
        return {"compared": False}
    ma, mb = fa.quantiles["0.5"], fb.quantiles["0.5"]
    overlap = not (fa.quantiles["0.95"] < fb.quantiles["0.05"] or fb.quantiles["0.95"] < fa.quantiles["0.05"])
    ratio = (max(ma, mb) + 1) / (min(ma, mb) + 1)
    return {
        "compared": True, "horizon_days": horizon, "renewal_median": ma, "loglinear_median": mb,
        "ratio": float(ratio), "intervals_overlap": overlap,
        "substantial_disagreement": bool(ratio > 2.0 or not overlap),
    }
