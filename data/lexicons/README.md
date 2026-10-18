# Language lexicons

One YAML file per language. The NLP engine discovers files at runtime; adding a
language means adding a file — no code change.

Each file declares a `support_level` and `review_status`:

* `support_level: high | medium | low` — how much the system can rely on its own
  analysis of this language. Signals in `low` languages are always escalated to
  human review and never trigger alerts on their own.
* `review_status: reviewed | draft_requires_native_review` — whether a native
  speaker with public-health background has reviewed the term lists. Draft
  lexicons are deliberately small: they contain only terms the maintainers are
  reasonably confident about, and they force human review.

Term categories map to cross-lingual *concepts* (`ebola`, `death`, `illness`,
...). Concepts, not words, are compared across languages for deduplication, so a
French post and a Lingala post describing the same event can be linked.

**Contributions from native speakers are the single most valuable improvement
to this system.** Please open a pull request that sets `review_status:
reviewed` only after native-speaker review, and note regional variants.
