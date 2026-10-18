"""Personal-data minimisation for stored external text.

Public posts can contain names, phone numbers, handles and addresses. Being
public does not make them appropriate to republish, so text is redacted before
storage and only a keyed pseudonym of the author is kept for duplicate and
coordination analysis.

Name detection is heuristic. It is a defence-in-depth layer: public outputs
never include stored post text in the first place (clusters are paraphrased).
"""

from __future__ import annotations

import hashlib
import hmac
import re

from ..config import get_settings

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("[email]", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("[url]", re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)),
    ("[handle]", re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{2,30}\b")),
    ("[phone]", re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")),
    ("[id-number]", re.compile(r"\b(passport|ID|NIN|carte d'identité|kitambulisho)\s*(no\.?|number|n°|#)?\s*[:#]?\s*[A-Z0-9-]{5,}\b", re.I)),
]

# Cues that commonly precede a person's name in reporting, in several languages.
_NAME_CUES = re.compile(
    r"\b(Mr|Mrs|Ms|Miss|Dr|Mme|Mlle|M\.|Monsieur|Madame|Mama|Papa|Maman|Bwana|Bi|Ndugu|Sheikh|Pasteur|Pastor|Abbé|"
    r"named|called|nommée?|appelée?|anaitwa|aitwaye|jina lake|nkombo na ye|kombo na ye|chamado|chamada)\s+"
    r"((?:[A-ZÀ-Ý][\w'’-]+)(?:\s+[A-ZÀ-Ý][\w'’-]+){0,3})",
    re.U,
)
_AGE_DESCRIPTOR = re.compile(r"\b(\d{1,3})[- ]?(years?[- ]old|years?|ans|yrs?|años|anos)\b|\b(miaka|imyaka|emyaka)\s+(\d{1,3})\b", re.I)


def redact(text: str) -> tuple[str, list[str]]:
    """Return redacted text and the categories that were removed."""
    found: list[str] = []
    out = text
    for label, pat in _PATTERNS:
        if pat.search(out):
            found.append(label.strip("[]"))
            out = pat.sub(label, out)
    if _NAME_CUES.search(out):
        found.append("person-name")
        out = _NAME_CUES.sub(lambda m: f"{m.group(1)} [name]", out)
    # Exact ages combined with places can identify people; coarsen them.
    if _AGE_DESCRIPTOR.search(out):
        found.append("exact-age")
        out = _AGE_DESCRIPTOR.sub("[age]", out)
    return out, found


def pseudonymize(platform: str, author_id: str | None) -> str | None:
    """Keyed, non-reversible author pseudonym. Never exposed through any output channel."""
    if not author_id:
        return None
    key = get_settings().pseudonym_salt.encode()
    return hmac.new(key, f"{platform}:{author_id}".encode(), hashlib.sha256).hexdigest()[:32]
