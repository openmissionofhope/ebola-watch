"""Parameter loading and delay-distribution discretisation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from scipy import stats

from ..config import get_settings

MODEL_VERSION = "ew-epi-1.0.0"


@lru_cache
def load_parameters(data_dir: str | None = None) -> dict:
    base = Path(data_dir) if data_dir else get_settings().data_dir
    return yaml.safe_load((base / "parameters" / "pathogens.yaml").read_text())


@lru_cache
def load_mobility(data_dir: str | None = None) -> list[dict]:
    base = Path(data_dir) if data_dir else get_settings().data_dir
    return yaml.safe_load((base / "parameters" / "mobility_scenarios.yaml").read_text()).get("catchments") or []


def pathogen_params(pathogen: str, params: dict | None = None) -> dict:
    params = params or load_parameters()
    return params["pathogens"].get(pathogen) or params["pathogens"]["unknown_orthoebolavirus"]


def gamma_from_mean_sd(mean: float, sd: float):
    shape = (mean / sd) ** 2
    scale = sd**2 / mean
    return stats.gamma(a=shape, scale=scale)


def discretize(mean: float, sd: float, max_days: int = 70, step_days: int = 1, include_zero: bool = False) -> np.ndarray:
    """Discretised gamma pmf on bins of ``step_days`` (bin k covers ((k-0.5)s, (k+0.5)s])."""
    dist = gamma_from_mean_sd(mean, sd)
    n = max_days // step_days
    edges = (np.arange(n + 1) + 0.5) * step_days
    cdf = dist.cdf(edges)
    pmf = np.diff(np.concatenate([[0.0], cdf]))  # bin 0 = [0, 0.5s]
    if not include_zero:
        pmf[0] = 0.0
    pmf = pmf / pmf.sum()
    return pmf


@dataclass(frozen=True)
class DelaySample:
    si_mean: float
    si_sd: float


def sample_uniform(rng: np.random.Generator, lo: float, hi: float, n: int) -> np.ndarray:
    return rng.uniform(lo, hi, size=n)


def beta_from_range(lo: float, hi: float, coverage: float = 0.9):
    """Beta distribution whose central ``coverage`` interval approximates [lo, hi]."""
    mean = (lo + hi) / 2
    # approximate sd from the range as a normal interval
    z = stats.norm.ppf(0.5 + coverage / 2)
    sd = (hi - lo) / (2 * z)
    var = sd**2
    common = mean * (1 - mean) / var - 1
    a, b = max(mean * common, 0.5), max((1 - mean) * common, 0.5)
    return stats.beta(a, b)
