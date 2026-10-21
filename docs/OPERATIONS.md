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

### Reviewing on GitHub (deployments without a server)

Review items that affect current outputs (alerts, signal clusters, official
figures from the last 12 months, recent auto-registered outbreaks, error
reports) arrive as issues labelled `ew-review` in the private operations
repository, at most 25 new issues per run. Items about historical data are not
sent. Source excerpts are posted as the first comment, inside code blocks, and
that comment is deleted after the raw-content retention period. Add the label
**approve** or **reject**: the GitHub account that adds it is recorded in the
audit log, and the label starts a short run that applies the decision,
republishes the site and closes the issue. Low-priority `signal` items are not
sent individually; their text appears in the excerpts of the cluster they
belong to.

## Official statements (between bulletins)

Ministries announce confirmed cases a day or more before ECDC or WHO restates
them. To publish such a figure, add an entry to `data/official/statements.yaml`
(the file explains the fields and rules) and push it to `main`: the hourly check
sees the new commit and the site is updated within the hour. Each entry needs
the authority, a link, a verbatim quote and only the figures the authority gave.
For an imported case, record the route (`transit_iso3`, `travel_date`) when the
authority gives it: countries a confirmed case travelled through are assessed
ELEVATED for 42 days. Never edit a published figure; add a corrected entry.
When ECDC or WHO later reports the same date, their figure is kept alongside and
any disagreement is shown.

## Corrections and retractions

`POST /api/v1/admin/retractions` (or, without a server, a *Retract published
output* issue in the operations repository labelled **apply**) retracts an
alert, report or observation and creates a public correction note (no personal
data). Observations are never
deleted; retracted rows are excluded from public outputs and remain in the
audit trail.

## Transport status changes

When a service changes (a ferry stops, a border closes, a road reopens), call
`POST /api/v1/admin/transport/{edge_key}/status` (or open a *Change a transport
service status* issue in the operations repository and label it **apply**) with
the new status and the evidence (a source and date). The change is recorded in
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
