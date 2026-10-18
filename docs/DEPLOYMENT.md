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

## Without a server (GitHub Pages)

The public site does not need a running server: nobody changes data through
it, and the data only change when the pipeline runs. In this mode

* a **private operations repository** runs the pipeline every 6 hours with
  GitHub Actions (`.github/workflows/publish-static.yml` in this repository,
  called from the operations repository), keeps the SQLite database as an
  encrypted release asset (AES-256, key in the `EW_STATE_KEY` secret; daily
  backups kept 14 days), and holds the human-review queue as issues;
* each run exports a **static snapshot** of every public API response
  (`ebolawatch export-static`, same publication policy as the API) plus the
  dashboard built with `VITE_STATIC=1`, and force-pushes it to the `gh-pages`
  branch of the public repository, which GitHub Pages serves.

Set-up (needs `gh` signed in as an owner of both repositories):

```bash
deploy/github/setup.sh init openmissionofhope/ebola-watch openmissionofhope/ebola-watch-ops
gh workflow run pipeline.yml --repo openmissionofhope/ebola-watch-ops      # first run (~10 min)
deploy/github/setup.sh pages openmissionofhope/ebola-watch                 # once it has succeeded
```

`init` creates the private repository from `deploy/github/ops-repo/`, generates
the secrets (never printed; the state key is also saved to
`~/.config/ebola-watch/state-key` — keep it in a password manager), adds a write
deploy key for publishing, and adds a ruleset so that key cannot push to the
default branch. The site is then at `https://<owner>.github.io/<repo>/`.

**Custom domain:** add a DNS `CNAME` record from the subdomain (e.g.
`ebolawatch.openmissionofhope.org`) to `<owner>.github.io`, set the variable
`EW_SITE_DOMAIN` in the operations repository, run the workflow, then
`deploy/github/setup.sh pages <site repo> <domain>`. Verifying the domain for
the organisation (*Organisation settings → Pages*) prevents takeover of the
subdomain by other GitHub users.

What differs from the server deployment:

| | Server | GitHub Pages |
|---|---|---|
| Free-text questions (Ask), custom queries | yes | no (all published figures are on the pages and in CSV/JSON files) |
| Review | dashboard, API key | issues in the operations repository: label **approve** / **reject** |
| Retractions, transport status | admin API | issue forms in the operations repository + label **apply** |
| Public error reports | form stored in the database | public GitHub issue form (`data-error`) |
| Update frequency | worker interval | every 6 hours, and within minutes of a review decision |
| Cost | a server | free for a public site repository; the private operations repository uses Actions minutes (about 1,000–1,300 of the 2,000 included monthly in GitHub Free) |

If a run fails, the previous site stays online and the next run starts from the
last saved state; the dashboard shows an "out of date" warning when the
snapshot is more than 36 hours old. If the saved database cannot be restored
(e.g. the state key was lost), runs stop rather than starting over; delete the
`state` release to start a new database deliberately.

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
