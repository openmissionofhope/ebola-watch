"""Build the DRC health-zone gazetteer (names -> province, population) used for
geocoding official sub-national data and applying small-area publication rules.

Source: INRB-UMIE/BDBV2026-Data build/drc_health_zones.geojson (MIT-licensed
repository; health-zone boundaries from the HDX MoH shapefile; population totals
from WorldPop, CC BY 4.0). Only names, province membership and rounded
population totals are kept: no geometry, no facility data.

Usage: python scripts/build_health_zone_gazetteer.py
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = "https://raw.githubusercontent.com/INRB-UMIE/BDBV2026-Data/main/build/drc_health_zones.geojson"
UA = {"User-Agent": "EbolaWatch/0.1 (Open Mission of Hope; +https://openmissionofhope.org)"}


def main() -> None:
    r = httpx.get(URL, headers=UA, timeout=300, follow_redirects=True)
    r.raise_for_status()
    zones = []
    for f in r.json()["features"]:
        p = f["properties"]
        pop = ((p.get("worldpop") or {}).get("pop_count") or {}).get("pop_count")
        zones.append({
            "name": p["nom"],
            "province": p["province"],
            "population": int(round(pop, -2)) if pop else None,
        })
    zones.sort(key=lambda z: (z["province"], z["name"]))
    out = {
        "source": "INRB-UMIE/BDBV2026-Data build/drc_health_zones.geojson",
        "source_url": URL,
        "population_source": "WorldPop (CC BY 4.0), rounded to nearest 100",
        "zones": zones,
    }
    path = ROOT / "data" / "gazetteer" / "cod_health_zones.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {len(zones)} health zones to {path}")


if __name__ == "__main__":
    main()
