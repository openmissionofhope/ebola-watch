# API

Interactive documentation (OpenAPI): `/api/docs` (Swagger UI) and `/api/redoc`;
schema at `/api/openapi.json`.

All public endpoints are read-only, unauthenticated, rate-limited
(`EW_RATE_LIMIT_PER_MINUTE`, default 120/min per client), and apply the same
publication policy as the dashboard: first-level administrative resolution at
most, small-area and complementary suppression, paraphrased unofficial signals,
and explicit "insufficient evidence" results. Clients that enumerate many
distinct filter combinations are throttled (HTTP 429).

Region codes: ISO 3166-1 alpha-3 for countries (`COD`), ISO 3166-2 for
first-level units (`CD-IT`); a unit without an ISO 3166-2 code gets
`<ISO3>-<NAME>` (e.g. `SDN-ABYEI-PCA`). Finer units return 404.

## Public endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/meta` | version, model version, disclaimer, synthetic-data flag, publication policy |
| GET | `/api/v1/overview` | assessed areas (summaries), severity map, published alerts, latest official developments |
| GET | `/api/v1/regions` | publishable regions |
| GET | `/api/v1/regions/{code}/summary` | official counts (by category, with source/date/citation), estimated total, recent incidence, completeness, R_t, nowcast, forecasts and scenarios, expansion, severity (with triggers) and confidence, surveillance indicators, assumptions |
| GET | `/api/v1/regions/{code}/official-series?metric=cases&case_class=confirmed` | official cumulative series for the current outbreak with publication dates, citations, revisions and pending-review count |
| GET | `/api/v1/regions/{code}/subnational` | first-level table with suppression applied |
| GET | `/api/v1/regions/{code}/estimates` | burden methods, assumptions, ascertainment, disagreement |
| GET | `/api/v1/regions/{code}/forecasts` | forecast and scenario intervals, model comparison, expansion |
| GET | `/api/v1/regions/{code}/forecast-comparison` | past forecasts vs subsequently reported values |
| GET | `/api/v1/regions/{code}/evidence` | official sources used, validation counts, unofficial signals, published estimates |
| GET | `/api/v1/regions/{code}/transport` | corridor edges touching the area and introduction ranking |
| GET | `/api/v1/severity` | severity status, level and confidence for every assessed area |
| GET | `/api/v1/surveillance-quality` | surveillance indicators per assessed area |
| GET | `/api/v1/signals` | aggregated, paraphrased unofficial signal clusters |
| GET | `/api/v1/alerts` | published alerts and retractions |
| GET | `/api/v1/transport` | all generalised corridors + introduction ranking |
| GET | `/api/v1/map/geometry/{0\|1}` | simplified boundaries (countries / first-level units) |
| GET | `/api/v1/map/layers` | per-area values for the five map layers |
| GET | `/api/v1/sources` | connector status, licence and terms |
| GET | `/api/v1/evaluation` | backtest results (real and synthetic, labelled) |
| GET | `/api/v1/reports` · `/api/v1/reports/{id}?format=json\|markdown` | published situation reports |
| GET | `/api/v1/export/summaries.csv` · `/api/v1/export/subnational.csv` | aggregated exports (separately rate-limited, audit-logged) |
| POST | `/api/v1/query` `{"question": "..."}` | scope-guarded answers; clinical, identity, tracking and operational requests are refused |
| POST | `/api/v1/error-reports` | correction requests (personal data removed on receipt) |

### Example

```bash
curl -s https://HOST/api/v1/regions/COD/summary | jq '{official: .official.confirmed_cases, estimate: .estimated_total, severity: .severity.label, confidence: .severity.confidence}'
```

A field that cannot be estimated is returned as:

```json
{"label": "Estimated cumulative symptomatic infections (reported and unreported)",
 "insufficient": true,
 "message": "Insufficient evidence for a reliable numerical estimate.",
 "reason": "fewer than 20 reported deaths; mortality-based inference unreliable"}
```

## Administrative endpoints

Require `X-API-Key` (create with `ebolawatch create-api-key NAME --role reviewer|admin|analyst`).
Every call is audit-logged.

| Method | Path | Role |
|---|---|---|
| GET | `/api/v1/admin/review-queue?status=pending` | reviewer |
| GET | `/api/v1/admin/review-queue/{id}` | reviewer (includes redacted source text within retention) |
| POST | `/api/v1/admin/review-queue/{id}/decision` `{"decision": "approved\|rejected\|needs_more_info", "note": "..."}` | reviewer |
| POST | `/api/v1/admin/signals/{id}/translate` | reviewer (machine translation, disabled unless configured) |
| POST | `/api/v1/admin/retractions` | reviewer |
| POST | `/api/v1/admin/transport/{edge_key}/status` `{"service_status": "...", "evidence": "..."}` | reviewer |
| GET | `/api/v1/admin/alerts` | reviewer |
| POST | `/api/v1/admin/pipeline/run` | admin |
| GET | `/api/v1/admin/audit-log` | admin |

## Static data files

A deployment without a server (see DEPLOYMENT.md, "GitHub Pages") publishes the
response of every public `GET` endpoint as a file, written by
`ebolawatch export-static` through the same code and publication policy:

| API | File |
|---|---|
| `GET /api/v1/<path>` | `data/<path>.json`, e.g. `data/overview.json`, `data/regions/COD/summary.json`, `data/map/geometry/1.json` |
| `GET /api/v1/reports/{id}?format=markdown` | `data/reports/{id}.md` |
| `GET /api/v1/export/{name}.csv` | `data/export/{name}.csv` |

`data/index.json` lists every file; `data/meta.json` adds `static: true` and
`snapshot_generated_at`. Query parameters are not supported (the official
series is the default `cases`/`confirmed` series), and there are no `POST` or
administrative endpoints.

## Errors

`401` missing/invalid API key · `403` insufficient role · `404` unknown region or
resolution not publishable · `413` request body over 64 KB · `422` validation
error · `429` rate limit or query-guard throttling (see `Retry-After`).
