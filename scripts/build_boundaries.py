"""Build simplified, public-safe boundary files used by the dashboard and region registry.

Sources (downloaded at build time, licences recorded per feature and in
data/boundaries/ATTRIBUTION.md):
  * Natural Earth 1:50m admin-0 countries (public domain)
  * geoBoundaries gbOpen ADM1 for priority countries (licence varies by country)

Usage:  python scripts/build_boundaries.py [--cache DIR]
Requires the optional ``geo`` extra (shapely).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "boundaries"
UA = {"User-Agent": "EbolaWatch/0.1 (Open Mission of Hope; +https://openmissionofhope.org)"}
NE_ADM0 = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
GB_API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM1/"
PRIORITY = ["COD", "COG", "CAF", "UGA", "RWA", "BDI", "SSD", "SDN", "KEN", "TZA", "AGO", "CMR", "GAB", "GNQ"]


def fetch(url: str, cache: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / (url.rstrip("/").replace("/", "_").replace(":", "")[-150:] + ".json")
    if not p.exists():
        r = httpx.get(url, headers=UA, timeout=300, follow_redirects=True)
        r.raise_for_status()
        p.write_bytes(r.content)
    return json.loads(p.read_text())


def simplify(geom: dict, tol: float) -> dict:
    g = shape(geom).simplify(tol, preserve_topology=True)
    if not g.is_valid:
        g = g.buffer(0)
    m = mapping(g)
    return json.loads(json.dumps(m), parse_float=lambda x: round(float(x), 3))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=ROOT / "var" / "cache" / "boundaries")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    ne = fetch(NE_ADM0, args.cache)
    countries = []
    for f in ne["features"]:
        p = f["properties"]
        iso3 = p.get("ADM0_A3") if p.get("ISO_A3") in (None, "-99") else p["ISO_A3"]
        countries.append({
            "type": "Feature",
            "properties": {
                "iso3": iso3, "name": p.get("NAME_EN") or p.get("NAME"), "name_fr": p.get("NAME_FR"),
                "continent": p.get("CONTINENT"), "label_lat": p.get("LABEL_Y"), "label_lon": p.get("LABEL_X"),
                "source": "Natural Earth 1:50m admin-0 (public domain)",
            },
            "geometry": simplify(f["geometry"], 0.05 if p.get("CONTINENT") == "Africa" else 0.15),
        })
    (OUT / "admin0.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": countries}, separators=(",", ":")))

    adm1 = []
    for iso3 in PRIORITY:
        meta = fetch(GB_API.format(iso3=iso3), args.cache)
        gj = fetch(meta["simplifiedGeometryGeoJSON"], args.cache)
        for f in gj["features"]:
            p = f["properties"]
            g = shape(f["geometry"])
            c = g.representative_point()
            adm1.append({
                "type": "Feature",
                "properties": {
                    "iso3": iso3, "name": p.get("shapeName"), "iso_3166_2": p.get("shapeISO") or None,
                    "gb_id": p.get("shapeID"), "label_lat": round(c.y, 2), "label_lon": round(c.x, 2),
                    "source": f"geoBoundaries gbOpen {iso3} ADM1 ({meta.get('boundarySource')}, {meta.get('boundaryYearRepresented')})",
                    "license": meta.get("boundaryLicense"),
                },
                "geometry": simplify(f["geometry"], 0.02),
            })
    (OUT / "admin1_priority.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": adm1}, separators=(",", ":")))
    print(f"wrote {len(countries)} countries, {len(adm1)} admin-1 units")


if __name__ == "__main__":
    main()
