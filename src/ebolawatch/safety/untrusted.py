"""Safe handling of untrusted external text.

Fetched bulletins, articles and social-media posts are *data*. Nothing in them
can change configuration, trigger tool use, alter thresholds, or publish
alerts. This module:

* normalises text (NFKC, strips control and zero-width characters, caps length);
* removes markup;
* detects instruction-like content aimed at automated pipelines ("prompt
  injection") so the item is flagged, escalated to human review and barred
  from triggering alerts on its own.

Detection never *executes* or *obeys* anything; it only adds a flag.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

MAX_TEXT_CHARS = 20_000

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­‪‫‬‭‮⁦⁧⁨⁩"))
_TAG_RE = re.compile(r"<[^>]{0,2000}>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style|iframe|object|embed)[^>]*>.*?</\1\s*>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")

# Patterns typical of text addressed to an AI system or automated pipeline
# rather than to human readers. Multilingual where practical.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_instructions", re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|earlier|system)\b.{0,40}\b(instruction|prompt|rule|guideline|directive)s?\b", re.I | re.S)),
    ("ignore_instructions_fr", re.compile(r"\b(ignore[rz]?|oublie[rz]?)\b.{0,40}\b(instructions?|consignes?|règles?)\b", re.I | re.S)),
    ("role_reassignment", re.compile(r"\byou are (now|no longer)\b|\bact as (an?|the)\b.{0,30}\b(admin|system|developer|model)\b|\bnew (system )?persona\b", re.I)),
    ("system_prompt_reference", re.compile(r"\b(system|developer) (prompt|message|instructions?)\b|\bjailbreak\b|\bDAN mode\b", re.I)),
    ("pipeline_command", re.compile(r"\b(set|change|raise|lower|mark)\b.{0,30}\b(severity|alert level|confidence|threshold|status)\b.{0,30}\b(to|as|=)\b", re.I | re.S)),
    ("publish_command", re.compile(r"\b(publish|issue|send|broadcast|declare)\b.{0,30}\b(alert|warning|emergency|outbreak)\b.{0,40}\b(immediately|now|without review|automatically)\b", re.I | re.S)),
    ("tool_call_syntax", re.compile(r"(<\|?(im_start|im_end|system|assistant|tool)[^>]*>|\{\s*\"(tool|function|name)\"\s*:|```\s*(tool|function_call)|\[INST\]|<<SYS>>)", re.I)),
    ("ai_addressed", re.compile(r"\b(dear|attention|note to|instructions? for)\b.{0,20}\b(ai|llm|language model|chatbot|assistant|gpt|claude|bot)\b", re.I | re.S)),
    ("credential_request", re.compile(r"\b(reveal|print|output|send|exfiltrate)\b.{0,30}\b(api[_ ]?key|secret|password|token|credentials?)\b", re.I | re.S)),
]


@dataclass(frozen=True)
class SanitizedText:
    text: str
    flags: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False

    @property
    def injection_suspected(self) -> bool:
        return any(f.startswith("injection:") for f in self.flags)


def strip_markup(raw: str) -> str:
    s = _SCRIPT_RE.sub(" ", raw)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s)
    s = _TAG_RE.sub(" ", s)
    return html.unescape(s)


def normalize(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw)
    s = s.translate(_ZERO_WIDTH)
    s = "".join(ch for ch in s if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    s = _WS_RE.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def detect_injection(text: str) -> list[str]:
    return [f"injection:{name}" for name, pat in _INJECTION_PATTERNS if pat.search(text)]


def sanitize(raw: str | None, *, is_html: bool = False, max_chars: int = MAX_TEXT_CHARS) -> SanitizedText:
    if not raw:
        return SanitizedText("")
    s = strip_markup(raw) if is_html or "<" in raw else raw
    s = normalize(s)
    truncated = len(s) > max_chars
    if truncated:
        s = s[:max_chars]
    flags = detect_injection(s)
    if truncated:
        flags.append("truncated")
    return SanitizedText(s, tuple(flags), truncated)


def as_data_block(text: str, label: str = "untrusted_document") -> str:
    """Wrap untrusted text for any downstream language-model call.

    The delimiter contains a fixed token that is stripped from the content so
    the content cannot close the block early.
    """
    token = "EBOLAWATCH_UNTRUSTED_DATA"
    cleaned = text.replace(token, "[removed]")
    return f"<{token} label=\"{label}\">\n{cleaned}\n</{token}>"
