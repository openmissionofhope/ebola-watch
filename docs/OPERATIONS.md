# Operations: human review, corrections and maintenance

## Daily review routine

1. Open **Review** in the dashboard (API key with role `reviewer`) or call
   `GET /api/v1/admin/review-queue`. Items are ordered by priority (1 = high).
2. For each item, open the detail view. Observations show the supporting quote
   and citation — check the number against the linked bulletin. Signals show
   redacted text, language, features and review reasons. Alerts show the
   evidence that triggered them.
3. Decide: **approved**, **rejected** or **needs_more_info**, with a short note.
   Approving an alert publishes it; approving an observation marks it verified;
   rejecting it marks it disputed and removes it from public series.
4. Never approve an alert that relies on unofficial reports without independent
   confirmation (a call to a partner, an official statement, a credible
   professional report).

| Queue item | Typical action |
|---|---|
| `observation` (ambiguous extraction, >5% revision, multi-country split, medevac) | verify against the bulletin; approve or reject |
| `outbreak` (auto-registered from a bulletin) | check declaration date and pathogen; edit `data/outbreaks.yaml` for curated metadata |
| `signal` (low-resource language, injection flag, ambiguous terms) | a reviewer who reads the language assesses relevance |
| `cluster` / `alert` (possible emerging signal; official reporting may be incomplete) | seek corroboration; approve only with independent confirmation |
| `correction` (public error report) | investigate; retract or correct; reply through your organisation's channels if contact was offered |

## Corrections and retractions

`POST /api/v1/admin/retractions` retracts an alert, report or observation and
creates a public correction note (no personal data). Observations are never
deleted; retracted rows are excluded from public outputs and remain in the
audit trail.

## Transport status changes

When a service changes (a ferry stops, a border closes, a road reopens), call
`POST /api/v1/admin/transport/{edge_key}/status` with the new status and the
evidence (a source and date). The change is recorded in
`transport_status_changes` and the audit log, and the next analysis run uses it.

## Adding a language

1. Copy `data/lexicons/en.yaml` to `data/lexicons/<code>.yaml`.
2. Fill `identifiers` (distinctive function words) and term categories with
   native-speaker input; include regional spellings and transliterations.
3. Keep `support_level: low` and `review_status: draft_requires_native_review`
   until a native speaker with public-health experience has reviewed it.
4. Add tests with synthetic sentences (positive, negative, negated, ambiguous).

No code changes are needed: languages are discovered at runtime.

## Monitoring

* `GET /api/v1/sources` — connector status and last success.
* `connector_runs` table — per-run status and messages.
* `model_runs.status` and `diagnostics.reasons` — why an estimate or forecast
  was not produced.
* `GET /api/v1/evaluation` — forecast performance; investigate if 90% coverage
  falls below 0.75.

## Incident response

If an incorrect alert or estimate is published: retract it immediately with a
public note, fix the cause (source extraction, threshold, data error), re-run
`ebolawatch analyze`, and record the incident in your organisation's log. If a
privacy breach is suspected, disable the affected connector
(`EW_DISABLED_SOURCES`), purge text (`ebolawatch retention` after shortening
retention), and follow your data-protection procedures.
