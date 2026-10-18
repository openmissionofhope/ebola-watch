from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

REQUIRED = {"key", "from", "to", "mode", "physical_status", "service_status", "verification"}


@lru_cache
def _load(path: str) -> dict:
    data = yaml.safe_load(Path(path).read_text())
    for e in data.get("edges", []):
        missing = REQUIRED - set(e)
        if missing:
            raise ValueError(f"transport edge {e.get('key')} missing {sorted(missing)}")
        e.setdefault("cross_border", False)
        e.setdefault("sources", [])
    return data


def load_corridors(data_dir: Path) -> dict:
    return _load(str(Path(data_dir) / "transport" / "corridors.yaml"))
