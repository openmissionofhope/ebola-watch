"""Numbers and dates in official and unofficial text (multilingual where needed)."""

from __future__ import annotations

import re
from datetime import date, timedelta

NUMBER_WORDS = {
    # English
    "zero": 0, "no": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100,
    # French
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20, "trente": 30, "cent": 100,
    # Swahili
    "moja": 1, "mbili": 2, "tatu": 3, "nne": 4, "tano": 5, "sita": 6, "saba": 7, "nane": 8, "tisa": 9, "kumi": 10,
    # Lingala
    "mɔ̌kɔ́": 1, "moko": 1, "mibale": 2, "misato": 3, "minei": 4, "mitano": 5, "motoba": 6, "nsambo": 7,
    "mwambe": 8, "libwa": 9, "zomi": 10,
    # Portuguese
    "dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "oito": 8, "nove": 9, "dez": 10,
}

ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "premier": 1, "première": 1, "deuxième": 2, "troisième": 3,
}

_WORD_ALT = "|".join(sorted((re.escape(w) for w in NUMBER_WORDS if len(w) > 2), key=len, reverse=True))
# Digits with optional thousands separators (space, thin/nbsp space, comma, period-as-separator)
NUM_PATTERN = rf"(?:(?<![\w.,])(?:\d{{1,3}}(?:[ \u202f\u00a0,]\d{{3}})+|\d+)(?![\w])|\b(?:{_WORD_ALT})\b)"


def parse_number(token: str) -> int | None:
    t = token.strip().lower()
    if t in NUMBER_WORDS:
        return NUMBER_WORDS[t]
    digits = re.sub(r"[ \u202f\u00a0,]", "", t)
    return int(digits) if digits.isdigit() else None


MONTHS = {
    # en
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # fr
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # pt
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10, "dezembro": 12,
    # sw
    "januari": 1, "februari": 2, "machi": 3, "aprili": 4, "mei": 5, "juni": 6, "julai": 7, "agosti": 8,
    "septemba": 9, "oktoba": 10, "novemba": 11, "desemba": 12,
}
_MONTH_ALT = "|".join(sorted(map(re.escape, MONTHS), key=len, reverse=True))

DATE_DMY = re.compile(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th)?\s+({_MONTH_ALT})\.?(?:\s+(\d{{4}}))?\b", re.I)
DATE_MDY = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?(?:\s+(\d{{4}}))?\b", re.I)
DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")  # day-first (francophone/WHO AFRO usage)
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def infer_year(d: int, m: int, reference: date) -> date | None:
    """Resolve a day-month without year to the most recent date not after ``reference`` (+1 day slack)."""
    cand = _mk(reference.year, m, d)
    if cand and cand > reference + timedelta(days=1):
        cand = _mk(reference.year - 1, m, d)
    return cand


def find_dates(text: str, reference: date) -> list[tuple[int, int, date, bool]]:
    """Return (start, end, date, year_explicit) for each date expression found."""
    out: list[tuple[int, int, date, bool]] = []
    for m in DATE_ISO.finditer(text):
        if dt := _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))):
            out.append((m.start(), m.end(), dt, True))
    for m in DATE_DMY.finditer(text):
        mon = MONTHS[m.group(2).lower()]
        day = int(m.group(1))
        dt = _mk(int(m.group(3)), mon, day) if m.group(3) else infer_year(day, mon, reference)
        if dt:
            out.append((m.start(), m.end(), dt, bool(m.group(3))))
    for m in DATE_MDY.finditer(text):
        if any(s <= m.start() < e for s, e, _, _ in out):
            continue
        mon = MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        dt = _mk(int(m.group(3)), mon, day) if m.group(3) else infer_year(day, mon, reference)
        if dt:
            out.append((m.start(), m.end(), dt, bool(m.group(3))))
    for m in DATE_NUMERIC.finditer(text):
        if dt := _mk(int(m.group(3)), int(m.group(2)), int(m.group(1))):
            out.append((m.start(), m.end(), dt, True))
    out.sort()
    return out


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9À-Ý\"“(])")


def sentences(text: str) -> list[tuple[int, str]]:
    """Split into sentences, returning (offset, sentence)."""
    out = []
    pos = 0
    for part in SENTENCE_SPLIT.split(text):
        idx = text.find(part, pos)
        out.append((idx, part.strip()))
        pos = idx + len(part)
    return [(i, s) for i, s in out if s]
