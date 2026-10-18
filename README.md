# Ebola Watch

**Evidence-based, multilingual Ebola outbreak monitoring, burden estimation and
forecasting — by [Open Mission of Hope](https://openmissionofhope.org).**

Ebola Watch helps humanitarian organisations, researchers, journalists and the
public understand:

1. how much Ebola has officially been reported,
2. how much probably exists in reality,
3. how many additional cases may occur, where, and how quickly,
4. how confident we are — and where surveillance has dangerous blind spots.

It treats official statistics as important but possibly incomplete, treats
unofficial reports as possibly wrong, and keeps the two — and every model
estimate — visibly separate, with uncertainty on every number. When evidence is
insufficient it says so: *"Insufficient evidence for a reliable numerical
estimate."*

> **Ebola Watch is not a medical service.** It provides no diagnosis, treatment,
> medicine, vaccine or other clinical advice. Anyone who may be unwell or exposed
> should contact a health professional or their national public-health authority.

## What it does

| | |
|---|---|
| **Official data** | Ingests WHO Disease Outbreak News (and, with acknowledgement, DRC national/health-zone data via OCHA HDX), extracts figures with provenance and validation, keeps every published version, never overwrites revisions |
| **Event-based surveillance** | Multilingual (16 language lexicons, extensible by adding a YAML file), code-switching aware, contextual claim analysis; near-duplicate collapse so 100 reposts count once; independence, coordination and staleness detection; human review before any alert relying on unofficial reports is published |
| **True burden** | Mortality-based back-calculation with species-specific priors; exportation-based inference when sourced mobility data exist; model disagreement shown, never averaged away |
| **Forecasts** | Renewal/branching simulations at 7–84 days, three scenarios (improving / current / deteriorating), probability of continued transmission and of newly affected areas, comparison model, backtesting with coverage and WIS shown in the app |
| **Transport** | Multimodal corridor graph (road, rail, river, lake, air, informal) between administrative units with verified/unknown service status and scenario analysis — connectivity is not transmission |
| **Severity** | Levels 0–4 plus *insufficient information*, with confidence as a separate dimension and an underestimation-risk flag; every level explains its triggers |
| **Reports** | Daily, weekly, major-change, country and multi-country situation reports |
| **Ethics by architecture** | No patient or personal data model; PII redaction; pseudonymous authors; first-level resolution cap with small-area and complementary suppression; query-reconstruction guard; scope guard against clinical, identity, tracking and targeting requests; prompt-injection handling; retention limits; audit log |

## Current status (2026-10-18)

| Component | Status |
|---|---|
| WHO DON connector + extraction | **Operational** — tested live; extracted DRC 2026 national figures match the independent HDX dataset on 20/20 overlapping dates |
| HDX DRC national + health-zone data | **Operational, off by default** — requires `EW_SOURCE_ACKNOWLEDGEMENTS=hdx_cod_ebola` after honouring the producers' request |
| World Bank population, OpenStreetMap checks | **Operational** — tested live |
| GDELT news (en/fr/sw/pt/ar) | **Partially operational** — works, heavily rate-limited |
| Africa CDC feed | Reachable; API returns 403 to automated clients (not bypassed) |
| ReliefWeb, ProMED, local RSS, Reddit, YouTube, X | **Require configuration** (credentials/approval); implemented, not tested live |
| Facebook, Telegram | **Unsupported** (no lawful automated read path for this use) |
| Models, severity, transport, reports, API | **Operational** — 70+ automated tests incl. the 20 required scenarios; PostgreSQL/PostGIS migration tested |
| Dashboard | **Operational** — React/Vite build served by the API |
| Optional reviewer translation (Claude) | Implemented; requires `EW_ENABLE_LLM_TRANSLATION` + credentials; not tested live |
| Lexicons beyond en/fr/pt | Drafts awaiting native-speaker review (content routed to people) |

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for everything that does not yet work as well as it should.

## Quick start

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev,postgres,geo]"
.venv/bin/ebolawatch init-db
.venv/bin/ebolawatch ingest -s who_don -s worldbank_population -s osm_overpass
.venv/bin/ebolawatch analyze
(cd frontend && npm ci && npm run build)
.venv/bin/ebolawatch serve            # dashboard: http://127.0.0.1:8000   API docs: /api/docs
```

Tests: `.venv/bin/pytest` (offline, synthetic data) and `.venv/bin/pytest -m live`
(real services). Production: `docker compose up -d --build` — see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Scientific methodology](docs/METHODOLOGY.md)
* [Severity levels and confidence](docs/SEVERITY.md)
* [Data sources, licences and access conditions](docs/DATA_SOURCES.md)
* [Ethical risk assessment](docs/ETHICS_RISK_ASSESSMENT.md)
* [API](docs/API.md) (interactive: `/api/docs`)
* [Validation and evaluation results](docs/VALIDATION.md)
* [Operations: review, corrections, maintenance](docs/OPERATIONS.md)
* [Deployment](docs/DEPLOYMENT.md)
* [Known limitations](docs/LIMITATIONS.md)

## Repository layout

```
src/ebolawatch/   backend: sources, parsing, nlp, evidence, epi, transport, severity,
                  reports, review, privacy, safety, pipeline, api, cli
frontend/         dashboard (React + TypeScript + Vite)
data/             lexicons, gazetteer, boundaries, parameters, thresholds,
                  transport corridors, outbreak registry, literature estimates
migrations/       Alembic migrations (SQLite and PostgreSQL/PostGIS)
tests/            unit, scenario, API and live tests (synthetic data only)
docs/             documentation
scripts/          reference-data build scripts
```

## Contributing

Native-speaker review of the language lexicons and regional verification of
transport services are the most valuable contributions — see
[CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately
([SECURITY.md](SECURITY.md)).

## Licence

Copyright (c) 2026 Open Mission of Hope. Released under the
[Christian Open Source License (COSL) 1.0](LICENSE.md). Bundled third-party data
keep their own licences — see [NOTICE.md](NOTICE.md).
