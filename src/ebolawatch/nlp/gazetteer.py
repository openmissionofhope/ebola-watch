"""Place-name resolution to administrative units.

Text is resolved to *administrative units* (country, admin-1, health zone),
never to coordinates, so downstream code cannot place an unverified report on
a precise point.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import get_settings


def fold(s: str) -> str:
    """Case- and accent-insensitive key, tolerant of hyphen/space/apostrophe variants."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("’", "'")
    s = re.sub(r"[-_./]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Virus and disease names that contain place names ("Bundibugyo virus",
# "Sudan virus", "Tai Forest virus", "Reston virus") must not geocode a text.
_PATHOGEN_NAMES = re.compile(
    r"\b(bundibugyo|sudan|tai forest|ta[iï] forest|reston|zaire|bombali)\s+(virus|ebolavirus|ebola virus|virus disease|strain|species)\b"
    r"|\b(orthoebolavirus|ebolavirus)\s+(bundibugyoense|sudanense|zairense|taiense|restonense)\b"
    r"|\b(bdbv|sudv|bvd|svd)\b"
    # "Ebola Bundibugyo", "souche Bundibugyo", "Bundibugyo strain/outbreak" name the virus, not the district
    r"|[eé]bola[\s-]+bundibugyo\b"
    r"|\b(strain|souche|cepa|variant|esp[eè]ce|esp[eé]cie)\s+(de\s+|du\s+|d')?(bundibugyo|soudan|sudan|za[iï]re)\b"
    r"|\bbundibugyo\s+([eé]bola|outbreak|epidemic|disease|maladie|fever|fi[eè]vre)\b",
    re.I,
)
# Generic admin-1 names (common in boundary datasets) that are ordinary words in text.
_GENERIC_ADMIN_NAMES = {
    "centre", "center", "central", "east", "est", "north", "nord", "south", "sud", "west", "ouest",
    "littoral", "northern", "eastern", "western", "southern", "coast", "lakes", "upper", "lower",
    "north west", "north east", "south west", "south east", "nord ouest", "nord est", "sud ouest", "sud est",
    "extreme nord", "far north", "plateaux", "pool", "capital", "kigali city", "northern region", "eastern region",
    "western region", "central region", "southern region", "northern province", "eastern province",
    "western province", "southern province", "lake", "river", "rivers", "mountain", "highlands",
}


def mask_pathogen_names(text: str) -> str:
    return _PATHOGEN_NAMES.sub(lambda m: " " * len(m.group(0)), text)


@dataclass(frozen=True)
class PlaceMatch:
    code: str  # region code (ISO3, ISO 3166-2 or health-zone code)
    level: int
    surface: str
    start: int
    end: int


@dataclass
class Gazetteer:
    names: dict[str, tuple[str, int]]  # folded name -> (code, level)
    canonical: dict[str, str]  # code -> canonical display name
    parents: dict[str, str]  # code -> parent code
    populations: dict[str, int]
    # Health zones are resolved only from structured official data, never from
    # free text: many names are common words or coincide with towns/countries.
    health_zones: dict[str, list[str]]  # folded name -> [codes]
    _pattern: re.Pattern | None = None

    def pattern(self) -> re.Pattern:
        if self._pattern is None:
            keys = sorted(self.names, key=len, reverse=True)
            alt = "|".join(re.escape(k) for k in keys if len(k) >= 3)
            self._pattern = re.compile(rf"(?<![\w])(?:{alt})(?![\w])")
        return self._pattern

    def find(self, text: str) -> list[PlaceMatch]:
        folded = fold(mask_pathogen_names(text))
        out: list[PlaceMatch] = []
        for m in self.pattern().finditer(folded):
            code, level = self.names[m.group(0)]
            out.append(PlaceMatch(code, level, m.group(0), m.start(), m.end()))
        return out

    def lookup(self, name: str) -> tuple[str, int] | None:
        return self.names.get(fold(name))

    def health_zone(self, name: str, province_code: str | None = None) -> str | None:
        codes = self.health_zones.get(fold(name), [])
        if province_code:
            codes = [c for c in codes if self.parents.get(c) == province_code]
        return codes[0] if len(codes) == 1 else None

    def country_of(self, code: str) -> str:
        while code in self.parents:
            code = self.parents[code]
        return code

    def admin1_of(self, code: str) -> str | None:
        """Return the admin-1 ancestor of a code (or the code itself if admin-1)."""
        level = self.level_of(code)
        while level is not None and level > 1:
            code = self.parents.get(code, code)
            level = self.level_of(code)
        return code if level == 1 else None

    def level_of(self, code: str) -> int | None:
        if len(code) == 3 and code.isupper():
            return 0
        if re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", code):
            return 1
        if code.startswith("HZ:"):
            return 2
        return None


def _hz_code(province_iso: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-")
    return f"HZ:{province_iso}:{slug}"


ISO_3166_2 = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
# geoBoundaries features carrying a wrong ISO 3166-2 code (iso3, name) -> code
_UPSTREAM_CODE_FIXES = {("CAF", "Sangha-Mbaéré"): "CF-SE"}  # tagged CF-HS, which is Mambéré-Kadéï


def admin1_code(props: dict) -> str | None:
    """Region code for a first-level unit: its ISO 3166-2 code, repairing a known
    upstream typo ("CF=OP"); units without one (e.g. the Abyei area, "N/A") get
    an internal ``<ISO3>-<NAME>`` code. Codes are URL path segments, so they are
    restricted to letters, digits and hyphens and must be unique."""
    raw = _UPSTREAM_CODE_FIXES.get((props.get("iso3"), props.get("name"))) or props.get("iso_3166_2") or ""
    raw = raw.strip().upper().replace("=", "-")
    if ISO_3166_2.match(raw):
        return raw
    slug = re.sub(r"[^A-Z0-9]+", "-", (props.get("name") or "").upper()).strip("-")
    return f"{props['iso3']}-{slug}" if slug else None


@lru_cache
def load_gazetteer(data_dir: str | None = None) -> Gazetteer:
    base = Path(data_dir) if data_dir else get_settings().data_dir
    names: dict[str, tuple[str, int]] = {}
    canonical: dict[str, str] = {}
    parents: dict[str, str] = {}
    populations: dict[str, int] = {}
    health_zones: dict[str, list[str]] = {}

    def add(name: str, code: str, level: int, overwrite: bool = False) -> None:
        k = fold(name)
        if not k:
            return
        if overwrite or k not in names or names[k][1] > level:
            names[k] = (code, level)

    admin0 = json.loads((base / "boundaries" / "admin0.geojson").read_text())
    for f in admin0["features"]:
        p = f["properties"]
        iso3 = p["iso3"]
        canonical.setdefault(iso3, p["name"])
        add(p["name"], iso3, 0)
        if p.get("name_fr"):
            add(p["name_fr"], iso3, 0)

    places = yaml.safe_load((base / "gazetteer" / "places.yaml").read_text())
    for iso3, aliases in places["country_aliases"].items():
        for a in aliases:
            add(a, iso3, 0, overwrite=True)

    admin1 = json.loads((base / "boundaries" / "admin1_priority.geojson").read_text())
    for f in admin1["features"]:
        p = f["properties"]
        code = admin1_code(p)
        if not code:
            continue
        canonical.setdefault(code, p["name"])
        parents[code] = p["iso3"]
        name_key = fold(p["name"])
        if name_key not in _GENERIC_ADMIN_NAMES and len(name_key) >= 4:
            add(p["name"], code, 1)
    for code, spec in places["admin1"].items():
        canonical[code] = spec["name"]
        add(spec["name"], code, 1, overwrite=True)
        for a in spec.get("aliases", []):
            add(a, code, 1, overwrite=True)

    hz_file = base / "gazetteer" / "cod_health_zones.json"
    if hz_file.exists():
        prov_map = places["cod_province_names"]
        for z in json.loads(hz_file.read_text())["zones"]:
            prov = prov_map.get(z["province"])
            if not prov:
                continue
            code = _hz_code(prov, z["name"])
            canonical[code] = z["name"]
            parents[code] = prov
            if z.get("population"):
                populations[code] = z["population"]
            for variant in {fold(z["name"]), fold(re.sub(r"\s*\(.*?\)", "", z["name"]))}:
                health_zones.setdefault(variant, []).append(code)

    for place, code in places["places"].items():
        level = 0 if len(code) == 3 else 1
        add(place, code, level, overwrite=True)

    return Gazetteer(names, canonical, parents, populations, health_zones)


def health_zone_code(province_iso: str, name: str) -> str:
    return _hz_code(province_iso, name)
