"""Build frontend/src/i18n/countries.json: ISO3 -> [ISO2, English name] for the
countries in data/boundaries/admin0.geojson, so the dashboard can show country
names in the reader's language (Intl.DisplayNames takes ISO2 codes).

Uses the iso-codes package (Debian/Ubuntu: /usr/share/iso-codes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISO_CODES = Path(sys.argv[1] if len(sys.argv) > 1 else "/usr/share/iso-codes/json/iso_3166-1.json")
EXTRA = {"KOS": "XK"}  # user-assigned code recognised by CLDR


def main() -> None:
    alpha2 = {c["alpha_3"]: c["alpha_2"] for c in json.loads(ISO_CODES.read_text())["3166-1"]} | EXTRA
    out = {}
    for f in json.loads((ROOT / "data" / "boundaries" / "admin0.geojson").read_text())["features"]:
        p = f["properties"]
        if p["iso3"] and p["iso3"] != "-99":
            out[p["iso3"]] = [alpha2.get(p["iso3"]), p["name"]]
    target = ROOT / "frontend" / "src" / "i18n" / "countries.json"
    target.write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {len(out)} countries to {target}")


if __name__ == "__main__":
    main()
