"""Time-varying reproduction number of *reported* cases (Cori et al., 2013).

R_t is estimated on weekly incidence with a gamma conjugate posterior:

    R_t | I ~ Gamma(a + sum I_s, 1 / (1/b + sum Lambda_s)),  s in window
    Lambda_s = sum_k I_{s-k} w_k                              (weekly serial interval w)

Two refinements guard against overconfidence:

* serial-interval uncertainty is propagated by mixing posteriors over draws of
  the serial-interval mean;
* extra-Poisson variation is measured (Pearson dispersion of one-step-ahead
  predictions) and the posterior is widened accordingly.

Changes in ascertainment also move R_t of reported cases; this is stated
wherever R_t is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .parameters import discretize

PRIOR_SHAPE = 1.0
PRIOR_SCALE = 5.0  # EpiEstim default prior: mean 5, sd 5
MAX_LAG_WEEKS = 10


def weekly_si(mean: float, sd: float) -> np.ndarray:
    """Weekly serial-interval pmf w[1..MAX_LAG_WEEKS] (index 0 unused)."""
    daily = discretize(mean, sd, max_days=7 * MAX_LAG_WEEKS + 3)
    w = np.zeros(MAX_LAG_WEEKS + 1)
    for d, p in enumerate(daily):
        k = max(1, int(round(d / 7)))
        if k <= MAX_LAG_WEEKS:
            w[k] += p
    return w / w.sum()


def infectiousness(incidence: np.ndarray, w: np.ndarray) -> np.ndarray:
    lam = np.zeros(len(incidence))
    for t in range(len(incidence)):
        for k in range(1, min(t, len(w) - 1) + 1):
            lam[t] += incidence[t - k] * w[k]
    return lam


@dataclass
class RtResult:
    insufficient: bool
    reason: str | None = None
    samples: np.ndarray = field(default_factory=lambda: np.zeros(0))
    median: float | None = None
    lower_90: float | None = None
    upper_90: float | None = None
    lower_50: float | None = None
    upper_50: float | None = None
    p_above_one: float | None = None
    dispersion: float = 1.0
    window_weeks: int = 2
    history: list[dict] = field(default_factory=list)  # per-week median/intervals for charts


def _dispersion(incidence: np.ndarray, lam: np.ndarray, window: int) -> float:
    """Pearson dispersion of one-step-ahead predictions over the last 8 weeks."""
    resid = []
    for t in range(max(window + 1, len(incidence) - 8), len(incidence)):
        num = incidence[t - window:t].sum()
        den = lam[t - window:t].sum()
        if den <= 0 or lam[t] <= 0:
            continue
        r_prev = (PRIOR_SHAPE + num) / (1 / PRIOR_SCALE + den)
        expected = r_prev * lam[t]
        if expected > 0:
            resid.append((incidence[t] - expected) ** 2 / expected)
    if len(resid) < 3:
        return 1.0
    return float(np.clip(np.mean(resid), 1.0, 100.0))


def estimate_rt(incidence: np.ndarray, si_mean: float, si_sd: float, si_mean_range: tuple[float, float],
                rng: np.random.Generator, window: int = 2, n_samples: int = 4000, n_si_draws: int = 20,
                min_cases_in_window: int = 10, min_weeks: int = 4, extra_dispersion: float = 1.0) -> RtResult:
    """``extra_dispersion`` (>= 1) widens the posterior when weekly counts were
    apportioned from reports spaced more than a week apart (less information
    than the smoothed weekly series suggests)."""
    incidence = np.asarray(incidence, dtype=float)
    if len(incidence) < min_weeks:
        return RtResult(True, f"fewer than {min_weeks} weeks of incidence data")
    recent = incidence[-window:].sum()
    w_central = weekly_si(si_mean, si_sd)
    lam_c = infectiousness(incidence, w_central)
    if recent < min_cases_in_window and lam_c[-window:].sum() < min_cases_in_window:
        return RtResult(True, f"fewer than {min_cases_in_window} reported cases in the last {window} weeks; R_t not identifiable")
    phi = _dispersion(incidence, lam_c, window) * max(1.0, extra_dispersion)

    cv = si_sd / si_mean
    draws = []
    per = max(1, n_samples // n_si_draws)
    for m in rng.uniform(si_mean_range[0], si_mean_range[1], size=n_si_draws):
        w = weekly_si(m, m * cv)
        lam = infectiousness(incidence, w)
        shape = PRIOR_SHAPE + incidence[-window:].sum()
        rate = 1 / PRIOR_SCALE + lam[-window:].sum()
        if rate <= 1 / PRIOR_SCALE + 1e-9:
            continue
        shape_eff = max(shape / phi, 1.0)
        rate_eff = rate / phi
        draws.append(rng.gamma(shape_eff, 1 / rate_eff, size=per))
    if not draws:
        return RtResult(True, "no infectiousness in window (insufficient preceding cases)")
    samples = np.concatenate(draws)
    q = np.quantile(samples, [0.05, 0.25, 0.5, 0.75, 0.95])

    history = []
    for t in range(window + 1, len(incidence)):
        shape = PRIOR_SHAPE + incidence[t - window + 1:t + 1].sum()
        rate = 1 / PRIOR_SCALE + lam_c[t - window + 1:t + 1].sum()
        if lam_c[t - window + 1:t + 1].sum() < 1:
            continue
        from scipy import stats

        g = stats.gamma(a=max(shape / phi, 1.0), scale=phi / rate)
        history.append({"index": t, "median": float(g.median()), "lower_90": float(g.ppf(0.05)), "upper_90": float(g.ppf(0.95))})

    return RtResult(
        insufficient=False, samples=samples, median=float(q[2]), lower_90=float(q[0]), upper_90=float(q[4]),
        lower_50=float(q[1]), upper_50=float(q[3]), p_above_one=float((samples > 1).mean()), dispersion=phi,
        window_weeks=window, history=history,
    )


def growth_rate(incidence: np.ndarray, weeks: int = 6) -> tuple[float, float] | None:
    """Weekly exponential growth rate (log scale) and its standard error from a
    log-linear fit to the last ``weeks`` weeks."""
    y = np.asarray(incidence[-weeks:], dtype=float)
    if len(y) < 4 or y.sum() < 10:
        return None
    x = np.arange(len(y))
    ly = np.log(y + 0.5)
    wts = np.sqrt(y + 0.5)  # approximate inverse-variance weights on the log scale
    X = np.vstack([np.ones_like(x), x]).T
    W = np.diag(wts**2)
    try:
        beta = np.linalg.solve(X.T @ W @ X, X.T @ W @ ly)
        resid = ly - X @ beta
        s2 = float((wts**2 * resid**2).sum() / max(len(y) - 2, 1))
        cov = s2 * np.linalg.inv(X.T @ W @ X)
    except np.linalg.LinAlgError:
        return None
    return float(beta[1]), float(np.sqrt(max(cov[1, 1], 1e-12)))
