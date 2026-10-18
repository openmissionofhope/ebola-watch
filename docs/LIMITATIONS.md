# Known limitations

Stated plainly so that nobody mistakes the system for more than it is.

## Data

* **Narrative extraction.** By default the official series comes from WHO
  Disease Outbreak News prose (about fortnightly). Extraction is conservative
  and consistency-checked, but can miss figures or mis-assign them; ambiguous
  rows go to review and are not published until verified. Province-level
  figures from bulletins are partial (only provinces named with a cumulative
  count).
* **Health-zone data** (HDX/INRB) are only used after the operator acknowledges
  the producers' pre-publication request; without them, sub-national series are
  sparse.
* **Probable and suspected cases** are reported irregularly; burden estimation
  uses confirmed cases and confirmed deaths.
* **Outbreak registry.** Historical outbreaks detected in old bulletins are
  auto-registered for review with approximate dates; their metadata is not
  curated.
* **Transport corridors** are a curated starting set. Most passenger services
  are recorded as *unknown* because their current operation could not be
  verified; no passenger volumes are included. Regional experts need to verify
  and update them.
* **Unofficial sources**: GDELT rate-limits heavily; ReliefWeb, ProMED and the
  social-media APIs need credentials or approval and were not tested live;
  Facebook and Telegram are unsupported. Local radio has no machine-readable
  source unless a station publishes a feed.

## Models

* Parameters for Bundibugyo virus disease (serial interval, delays, IFR) are
  largely transferred from Ebola virus disease or are explicit assumptions with
  ranges; estimates are sensitive to the IFR and death-ascertainment priors.
* The mortality method assumes confirmed deaths and confirmed cases share a case
  definition and uses mean delays rather than full delay distributions.
* R_t refers to reported cases; changes in testing or reporting move it.
* Weekly incidence from fortnightly reports is interpolated; the posterior is
  widened, but short-term dynamics within a reporting interval are invisible.
* The exportation estimator is implemented but inactive until sourced mobility
  data are configured.
* No reporting-triangle (backfill) nowcast yet: onset-dated vintaged data are not
  available from current sources.
* Forecast intervals were conservative (90% coverage 1.0 on the 2026 DRC
  backtest at 7–28 days); they may be wider than necessary. Evaluation sets are
  small (tens of origins).
* Introduction rankings are relative and scenario-based; they are not
  probabilities and depend on unverified service statuses.
* Severity thresholds are expert-set, not outcome-validated.

## Language

* English, French and Portuguese lexicons are usable; Swahili, Lingala and
  Arabic are drafts needing native review; Sango, Kikongo/Kituba, Tshiluba,
  Kinyarwanda, Kirundi, Luganda, Acholi, Amharic, Tigrinya and Juba Arabic are
  minimal placeholders that route content to people.
* Language identification is lexicon-based and weak on very short texts.
* Name redaction is heuristic.
* Multi-claim documents (e.g. a headline about two countries) yield one signal
  attributed to the place nearest the first claim; counts stated for other
  places are dropped rather than misattributed.

* The dashboard's French, Swahili, Lingala, Portuguese and Arabic versions
  were produced with machine assistance and have not been reviewed by native
  speakers; Lingala and Swahili technical terminology in particular needs
  review. Sentences the backend generates in new forms fall back to English
  until a template is added. Downloaded files (CSV, JSON, report Markdown)
  are in English.

## Evidence assessment

* Coordination detection relies on timing, near-duplication, author novelty and
  urgency cues; diverse, well-crafted campaigns can evade it.
* There is no image, audio or video analysis; screenshots and voice notes are
  not assessed.
* Historical source reliability is not yet computed (insufficient validated
  history); no numerical reliability scores are shown.

## Operations

* The GitHub Pages deployment has no free-text questions or custom queries,
  updates at most every 6 hours (plus after review decisions), and needs
  reviewers to have GitHub accounts with access to the private operations
  repository. Its scheduled runs use the operations repository's Actions
  minutes.
* Rate limiting and the query guard are in-process; multi-replica deployments
  need a shared limiter.
* The optional Claude translator is unit-tested with a stub but was not tested
  against the live API (no credentials in the development environment).
