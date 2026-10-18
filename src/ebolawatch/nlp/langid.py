"""Lightweight, explainable language identification with code-switching support.

Scores each registered language by the share of tokens that are its function
words, plus script evidence (Ethiopic, Arabic). Returns every language with a
meaningful share, so a French-Lingala or Swahili-English post is reported as
mixed rather than forced into one label. This is intentionally simple and is
paired with human-review escalation for low-support languages; an optional
statistical identifier can be plugged in behind the same interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexicon import Language, fold_text, load_languages

_TOKEN = re.compile(r"[\w']+", re.U)
_ETHIOPIC = re.compile(r"[ሀ-፿]")
_ARABIC = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class LanguageGuess:
    code: str
    share: float
    support_level: str


def identify(text: str, languages: dict[str, Language] | None = None, min_share: float = 0.15) -> list[LanguageGuess]:
    languages = languages or load_languages()
    folded = fold_text(text)
    tokens = _TOKEN.findall(folded)
    scores: dict[str, float] = {}
    if _ETHIOPIC.search(text):
        for code, lang in languages.items():
            if "Ethi" in lang.scripts:
                p = lang.ident_pattern()
                scores[code] = 1.0 + (len(p.findall(folded)) if p else 0)
    if _ARABIC.search(text):
        for code, lang in languages.items():
            if "Arab" in lang.scripts and "Latn" not in lang.scripts:
                scores[code] = scores.get(code, 0) + 1.0 + len(_ARABIC.findall(text)) / 20
    if tokens:
        # Weight each function word by how many languages share it (1/k), so
        # tokens such as "na" (Lingala and Swahili) count less than "ezali".
        owners: dict[str, list[str]] = {}
        for code, lang in languages.items():
            if "Latn" in lang.scripts:
                for w in {fold_text(i) for i in lang.identifiers}:
                    owners.setdefault(w, []).append(code)
        for tok in tokens:
            for code in owners.get(tok, ()):
                scores[code] = scores.get(code, 0) + 1.0 / len(owners[tok])
        # Topic vocabulary is weaker evidence (loanwords travel between languages).
        for code, lang in languages.items():
            if "Latn" not in lang.scripts:
                continue
            hits = sum(len(p.findall(folded)) for concept, p in lang.patterns.items() if concept != "ebola")
            if hits:
                scores[code] = scores.get(code, 0) + 0.5 * hits
    total = sum(scores.values())
    if not total:
        return []
    guesses = sorted((LanguageGuess(c, s / total, languages[c].support_level) for c, s in scores.items()), key=lambda g: -g.share)
    kept = [g for g in guesses if g.share >= min_share]
    return kept or guesses[:1]
