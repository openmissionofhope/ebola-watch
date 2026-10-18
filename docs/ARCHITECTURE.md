# Architecture

```
                    ┌───────────────────────────── sources/ ─────────────────────────────┐
 WHO DON · HDX ·    │ Connector.fetch() → FetchedItem(text, observations, meta)           │
 GDELT · feeds ·    │ honest ConnectorStatus · polite HttpClient (UA, per-host limits,    │
 social APIs ·      │ retries, Retry-After, size caps, no auth bypass)                    │
 World Bank · OSM   └──────────────┬──────────────────────────────────────────────────────┘
                                   │
                    pipeline/ingest.py  sanitize (safety/untrusted) → redact (privacy/redaction)
                                   │    → Document (minimised text, retention deadline, pseudonym)
                                   │    → DataVintage → Observation (append-only, validated,
                                   │      linked to Outbreak; review queue for ambiguous rows)
                                   ▼
                    ┌──────────── PostgreSQL / PostGIS (SQLite for development) ────────────┐
                    │ sources · documents · data_vintages · observations · outbreaks ·      │
                    │ regions · signals · signal_clusters · model_runs · estimates ·        │
                    │ forecasts · forecast_evaluations · severity_assessments · alerts ·    │
                    │ situation_reports · transport_* · review_items · corrections ·        │
                    │ error_reports · literature_estimates · api_keys · audit_log           │
                    └──────┬───────────────────────┬────────────────────────┬──────────────┘
                           │                       │                        │
        pipeline/signals.py│      pipeline/modeling.py                pipeline/evaluation.py
   nlp/ langid · lexicons ·│ epi/ series → renewal (R_t) → burden        epi/backtest · scoring
   classifier · gazetteer  │ → forecast (scenarios) → expansion          (real + SYNTHETIC)
   evidence/ fingerprint · │ severity/ classify + surveillance
   assess (origins,        │ transport/ network (connectivity watch)
   clusters, coordination, │ alerts (major change)
   staleness) → alerts     │
                           ▼
                    views.py  ← single public read model: resolution cap, suppression,
                           │    paraphrase, labels, "insufficient evidence", synthetic flags
            ┌──────────────┼──────────────────┬──────────────────┐
        api/app.py     reports/generate.py   exports (CSV)    dashboard (frontend/)
   public + admin API   situation reports
   rate limit · query guard · CSP · API keys/roles · audit
```

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Environment-only configuration; production refuses insecure defaults |
| `db/` | SQLAlchemy models (append-only observations, provenance fields), sessions; Alembic migrations in `migrations/` |
| `domain/enums.py` | Controlled vocabularies (case classes, transmission types, report kinds, statuses) |
| `sources/` | Connectors, HTTP client, registry, manual import, synthetic generator |
| `parsing/` | Number/date parsing (multilingual), WHO bulletin extraction |
| `nlp/` | Language registry (YAML lexicons, discovered at runtime), language identification with code-switching, gazetteer (admin units only), contextual claim classifier, optional translation |
| `evidence/` | MinHash near-duplicate detection, origin grouping, event clustering, independence, coordination and staleness detection, corroboration assessment |
| `epi/` | Series construction, weekly incidence, R_t, mortality- and exportation-based burden, renewal forecasts and scenarios, expansion, backtesting and scoring |
| `transport/` | Corridor seed loader, multimodal connectivity graph, effective distance, introduction ranking |
| `severity/` | Severity levels, confidence, surveillance-quality indicators |
| `reports/` | Situation reports (daily, weekly, major change, country, multi-country) |
| `review/` | Review queue, decisions, retractions, transport status changes, audit log |
| `privacy/` | Redaction, pseudonyms, publication policy and suppression, query guard |
| `safety/` | Untrusted-text handling, scope guard for user questions |
| `pipeline/` | Seeding, ingestion, signals, modelling, evaluation, orchestration, scheduler, retention |
| `views.py` | Public read models shared by every output channel |
| `api/` | FastAPI app, security (API keys, roles), rate limiting, constrained Q&A, reviewer views |
| `publish/` | Static snapshot of the public API and dashboard; review, retractions and transport changes through GitHub issues (deployments without a server) |
| `cli.py` | `ebolawatch` command |

## Processing schedule

`ebolawatch scheduler` (the `worker` container) runs the pipeline every
`EW_INGEST_INTERVAL_S` (default 6 h) and retention daily; without a server, a
scheduled GitHub Actions workflow does the same and publishes a static snapshot
(DEPLOYMENT.md). Scheduled runs skip sources that are not due: population data
are refreshed monthly, OpenStreetMap checks weekly, and a source that failed its
last three runs is retried once a day. Each connector run is
recorded in `connector_runs`; failing connectors never stop the pipeline.

## Design decisions

* **Python + FastAPI** for the statistical stack (NumPy/SciPy/NetworkX) and a
  typed, self-documenting API. **React + Vite** dashboard served by the same
  app; no third-party CDNs, fonts or map tiles (strict CSP; works offline from
  the server).
* **Rule-based, explainable NLP** with explicit lexicons rather than an opaque
  classifier: decisions carry reasons, and unsupported languages fail towards
  human review. A statistical or LLM classifier can be added behind the same
  interface once a labelled evaluation set exists.
* **One read model for every channel** (`views.py`), so privacy rules cannot
  diverge between API, dashboard, exports and reports.
* **SQLite for development, PostgreSQL + PostGIS for production**; GeoJSON is
  stored on every backend and mirrored into a PostGIS geometry column when
  available (migration `0002`).
