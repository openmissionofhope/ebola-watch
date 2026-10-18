"""Near-duplicate detection with MinHash over normalised shingles.

Normalisation removes the parts that differ between copies of the same
message (URLs, @handles, "RT", "Forwarded", emoji, punctuation, case,
accents), so 100 reposts of one rumour collapse to one origin.
"""

from __future__ import annotations

import hashlib
import re
import struct

from ..nlp.lexicon import fold_text

N_HASHES = 64
_MASK = (1 << 64) - 1
_SEEDS = [int.from_bytes(hashlib.blake2b(f"ew-minhash-{i}".encode(), digest_size=8).digest(), "big") for i in range(N_HASHES)]
_STRIP = [
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"(?<![\w@])@\w+"),
    re.compile(r"\[(handle|url|email|phone|name|age|id-number)\]"),
    re.compile(r"^\s*(rt|fwd?|forwarded|transféré|partagé|imetumwa)\b[:\s]*", re.I),
    re.compile(r"#(\w+)"),
]


def normalize_for_dedup(text: str) -> str:
    s = text or ""
    for rx in _STRIP:
        s = rx.sub(lambda m: m.group(1) if m.re.pattern.startswith("#") else " ", s)
    s = fold_text(s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def shingles(text: str) -> set[str]:
    norm = normalize_for_dedup(text)
    words = norm.split()
    if len(words) >= 6:
        return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}
    compact = norm.replace(" ", "_")
    return {compact[i:i + 5] for i in range(max(1, len(compact) - 4))}


def minhash(text: str) -> list[int]:
    sh = shingles(text)
    if not sh:
        return [0] * N_HASHES
    base = [struct.unpack(">Q", hashlib.blake2b(s.encode(), digest_size=8).digest())[0] for s in sh]
    return [min(((h ^ seed) * 0x9E3779B97F4A7C15) & _MASK for h in base) >> 1 for seed in _SEEDS]


def similarity(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    return sum(1 for x, y in zip(a, b, strict=False) if x == y) / len(a)
