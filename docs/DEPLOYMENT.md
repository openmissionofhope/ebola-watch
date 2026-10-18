# Deployment

## Development (SQLite)

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev,postgres,geo,llm]"
.venv/bin/ebolawatch init-db                 # migrations + reference data
.venv/bin/ebolawatch ingest -s who_don -s worldbank_population -s osm_overpass
.venv/bin/ebolawatch analyze                 # signals, models, severity, backtests, reports
(cd frontend && npm ci && npm run build)     # dashboard
.venv/bin/ebolawatch serve                   # http://127.0.0.1:8000  (API docs: /api/docs)
```

Run the tests with `.venv/bin/pytest` (offline) and `.venv/bin/pytest -m live`
(contacts WHO, World Bank and OpenStreetMap).

## Production (Docker Compose, PostgreSQL + PostGIS)

```bash
cp .env.example .env
# set EW_SECRET_KEY, EW_PSEUDONYM_SALT (>= 32 random chars each) and POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec api ebolawatch init-db
docker compose exec api ebolawatch create-api-key "Reviewer name" --role reviewer
docker compose exec api ebolawatch run        # first pipeline run (the worker repeats it every 6 h)
```

Services: `db` (postgis/postgis:16-3.4), `api` (uvicorn, port 8000 bound to
localhost), `worker` (`ebolawatch scheduler`). Containers run as a non-root
user, read-only, with all capabilities dropped.

Put a TLS-terminating reverse proxy (Caddy, nginx, Traefik) in front of `api`,
and set `EW_TRUST_FORWARDED_FOR=true` only when that proxy sets
`X-Forwarded-For`. For several API replicas, add a shared rate limiter at the
proxy; the in-process limiter remains as a backstop.

The application refuses to start in production with development secrets or
SQLite.

## Configuration checklist

| Setting | Purpose |
|---|---|
| `EW_SECRET_KEY`, `EW_PSEUDONYM_SALT` | API-key hashing and author pseudonyms; rotate the salt only with a re-ingest (pseudonyms change) |
| `EW_SOURCE_ACKNOWLEDGEMENTS` | enable sources with data-use conditions (see DATA_SOURCES.md) |
| `EW_RELIEFWEB_APPNAME`, `EW_YOUTUBE_API_KEY`, `EW_X_BEARER_TOKEN`, `EW_REDDIT_CLIENT_ID/SECRET`, `EW_PROMED_FEED_URL`, `EW_RSS_FEEDS` | optional sources |
| `EW_ENABLE_LLM_TRANSLATION` + Anthropic credentials (`ANTHROPIC_API_KEY`) | optional reviewer translation; sends redacted text to Anthropic — assess against your data-protection obligations first |
| `EW_MIN_PUBLIC_CELL_COUNT`, `EW_MIN_PUBLIC_SUBNATIONAL_POPULATION`, `EW_PUBLIC_MAX_ADMIN_LEVEL` | publication policy |
| `EW_RAW_CONTENT_RETENTION_DAYS`, `EW_SIGNAL_RETENTION_DAYS` | retention |
| `EW_RATE_LIMIT_PER_MINUTE`, `EW_EXPORT_RATE_LIMIT_PER_HOUR`, `EW_CORS_ORIGINS` | API protection |

## Backups and retention

Back up the database daily. Retention runs in the worker: social-media and
news text is deleted after `EW_RAW_CONTENT_RETENTION_DAYS` (default 30);
signal rows after `EW_SIGNAL_RETENTION_DAYS` (default 365), keeping only
aggregated clusters. Official observations are retained (they are public
records with provenance).

## Updating reference data

* Boundaries: `python scripts/build_boundaries.py` (needs the `geo` extra).
* DRC health zones: `python scripts/build_health_zone_gazetteer.py`.
* Outbreak registry: edit `data/outbreaks.yaml` (cite declarations/ends).
* Transport corridors: edit `data/transport/corridors.yaml`, or change service
  status through the admin API with evidence (keeps history).
* Thresholds and parameters: edit the YAML files and bump their `version`.
