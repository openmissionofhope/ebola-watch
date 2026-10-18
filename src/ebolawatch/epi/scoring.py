"""Forecast evaluation metrics."""

from __future__ import annotations

import numpy as np


def interval_score(lower: float, upper: float, y: float, alpha: float) -> float:
    return (upper - lower) + (2 / alpha) * max(lower - y, 0) + (2 / alpha) * max(y - upper, 0)


def wis(quantiles: dict[str, float], y: float) -> float:
    """Weighted interval score (Bracher et al., 2021) from 50% and 90% (and 95%) intervals + median."""
    med = quantiles["0.5"]
    pairs = [(0.5, "0.25", "0.75"), (0.1, "0.05", "0.95")]
    if "0.025" in quantiles and "0.975" in quantiles:
        pairs.append((0.05, "0.025", "0.975"))
    K = len(pairs)
    total = 0.5 * abs(y - med)
    for alpha, lo, hi in pairs:
        total += (alpha / 2) * interval_score(quantiles[lo], quantiles[hi], y, alpha)
    return total / (K + 0.5)


def pit(samples: np.ndarray, y: float, rng: np.random.Generator | None = None) -> float:
    """Randomised probability integral transform for count forecasts."""
    rng = rng or np.random.default_rng(0)
    below = (samples < y).mean()
    at = (samples == y).mean()
    return float(below + rng.uniform() * at)


def summarize(rows: list[dict]) -> dict:
    """rows: dicts with horizon_days, observed, median, lower_50, upper_50, lower_90, upper_90, wis, pit."""
    if not rows:
        return {"n": 0}
    out = {"n": len(rows), "by_horizon": {}}
    for h in sorted({r["horizon_days"] for r in rows}):
        rs = [r for r in rows if r["horizon_days"] == h]
        obs = np.array([r["observed"] for r in rs], dtype=float)
        med = np.array([r["median"] for r in rs], dtype=float)
        cov50 = np.mean([r["lower_50"] <= r["observed"] <= r["upper_50"] for r in rs])
        cov90 = np.mean([r["lower_90"] <= r["observed"] <= r["upper_90"] for r in rs])
        rel_bias = np.median((med - obs) / np.maximum(obs, 1))
        pits = [r["pit"] for r in rs if r.get("pit") is not None]
        hist = np.histogram(pits, bins=5, range=(0, 1))[0].tolist() if pits else []
        out["by_horizon"][h] = {
            "n": len(rs), "coverage_50": float(cov50), "coverage_90": float(cov90),
            "mean_wis": float(np.mean([r["wis"] for r in rs])), "mae": float(np.mean(np.abs(med - obs))),
            "median_relative_bias": float(rel_bias), "pit_histogram_5bins": hist,
            "calibration_note": _calibration_note(cov50, cov90, len(rs)),
        }
    return out


def _calibration_note(c50: float, c90: float, n: int) -> str:
    if n < 8:
        return "too few evaluated forecasts for a calibration judgement"
    notes = []
    if c90 < 0.75:
        notes.append("90% intervals cover too rarely (overconfident)")
    elif c90 > 0.98 and c50 > 0.8:
        notes.append("intervals may be wider than necessary (underconfident)")
    if c50 < 0.3:
        notes.append("50% intervals cover too rarely")
    return "; ".join(notes) or "coverage broadly consistent with nominal levels"


def brier(prob: list[float], outcome: list[int]) -> float | None:
    if not prob:
        return None
    p = np.array(prob, dtype=float)
    o = np.array(outcome, dtype=float)
    return float(np.mean((p - o) ** 2))
