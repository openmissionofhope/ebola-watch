"""Language registry and term matching.

Languages are discovered from ``data/lexicons/*.yaml``; nothing in the engine
enumerates languages. Matching is done on accent-folded, lower-cased text with
word boundaries, so spelling variants such as "Ébola"/"ebola" or
"Haut-Uélé"/"Haut Uele" match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import get_settings

CONCEPTS = (
    "ebola", "vhf", "bleeding", "illness", "death", "unexplained", "cluster", "outbreak", "lab",
    "surveillance", "negation", "hedging", "firsthand", "secondary", "rumor", "satire", "debunk",
    "official_body", "urgency", "temporal_recent", "temporal_past", "preparedness",
)


def fold_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("’", "'").replace("`", "'")
    # French elision, including feeds that drop the apostrophe ("dEbola", "l'epidemie")
    s = re.sub(r"\b(?:d|l|qu)'?(?=(?:ebola|epidemie|epidemies)\b)", "", s)
    return re.sub(r"\s+", " ", s)


def _compile(terms: list[str]) -> re.Pattern | None:
    folded = sorted({fold_text(str(t)).strip() for t in terms if str(t).strip()}, key=len, reverse=True)
    if not folded:
        return None
    alt = "|".join(re.escape(t) for t in folded)
    return re.compile(rf"(?<![\w])(?:{alt})(?![\w])")


@dataclass
class Language:
    code: str
    name: str
    scripts: list[str]
    support_level: str
    review_status: str
    identifiers: list[str]
    patterns: dict[str, re.Pattern] = field(default_factory=dict)
    alternatives: dict[str, re.Pattern] = field(default_factory=dict)
    relative_dates: dict[str, int] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    _ident_re: re.Pattern | None = None

    @property
    def requires_review(self) -> bool:
        return self.support_level == "low" or self.review_status != "reviewed"

    def ident_pattern(self) -> re.Pattern | None:
        if self._ident_re is None and self.identifiers:
            self._ident_re = _compile(self.identifiers)
        return self._ident_re

    def match(self, concept: str, folded: str) -> list[str]:
        p = self.patterns.get(concept)
        return [m.group(0) for m in p.finditer(folded)] if p else []

    def match_spans(self, concept: str, folded: str) -> list[tuple[int, int]]:
        p = self.patterns.get(concept)
        return [(m.start(), m.end()) for m in p.finditer(folded)] if p else []


@lru_cache
def load_languages(data_dir: str | None = None) -> dict[str, Language]:
    base = Path(data_dir) if data_dir else get_settings().data_dir
    langs: dict[str, Language] = {}
    for path in sorted((base / "lexicons").glob("*.yaml")):
        spec = yaml.safe_load(path.read_text())
        lang = Language(
            code=spec["code"],
            name=spec["name"],
            scripts=spec.get("scripts", ["Latn"]),
            support_level=spec.get("support_level", "low"),
            review_status=spec.get("review_status", "draft_requires_native_review"),
            identifiers=[str(x) for x in spec.get("identifiers", [])],
            relative_dates={fold_text(k): int(v) for k, v in (spec.get("relative_dates") or {}).items()},
            aliases=spec.get("aliases", []),
        )
        for concept, terms in (spec.get("terms") or {}).items():
            if (p := _compile(terms)) is not None:
                lang.patterns[concept] = p
        for alt, terms in (spec.get("alternative_explanations") or {}).items():
            if (p := _compile(terms)) is not None:
                lang.alternatives[alt] = p
        langs[lang.code] = lang
    return langs
