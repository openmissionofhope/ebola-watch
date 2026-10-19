# Data sources

Each source is a connector in `src/ebolawatch/sources/`. Connectors report an
honest status (`ok`, `partial`, `unavailable`, `requires_configuration`,
`requires_acknowledgement`, `unsupported`, `disabled`, `error`) visible at
`/api/v1/sources` and in the dashboard. When a source is unavailable the system
records that fact; it never substitutes invented data.

Status below was **tested on 2026-10-18** from the development environment.

## Official epidemiological sources

| Key | Source | Access | Licence / terms | Status (tested) |
|---|---|---|---|---|
| `who_don` | WHO Disease Outbreak News | public JSON API used by who.int | © WHO; short quotes with attribution and links | **Working** — 368 Ebola-related bulletins retrieved (2000s–2026); figures extracted with validation |
| `ecdc` | ECDC page on the outbreak (updated every weekday) | public web page (HTML; robots.txt allows it) | © ECDC, CC BY 4.0 — attribution and licence link shown with each figure; figures are reformatted as data | **Working** — tested live on 2026-10-19: DRC national totals and all seven provinces as of 14 October, and Kenya's cases. Provincial figures are published automatically only when they add up to the national totals on the same page; statements the page attributes to media reports are not extracted |
| `hdx_cod_ebola` | HDX "République démocratique du Congo : Cas et Décès d'Ebola" (OCHA DRC; INSP/COUSP situation reports transcribed by INRB-UMIE) | HDX CKAN API + CSV | CC BY 4.0 on HDX; upstream repository MIT **with a request to contact the producers before using epidemiological data ahead of their publication** | **Working** when acknowledged — 11,172 national and health-zone observations; **disabled by default** |
| `africa_cdc` | Africa CDC news feed | RSS | publisher terms | Reachable; no matching entries at test time. Its WordPress API returns HTTP 403 to automated clients and is not bypassed |
| `manual` | Reviewer transcription of official sitreps (e.g. PDF) | `ebolawatch import-observations` | as per the transcribed source | Working (tested with synthetic CSV) |

### Data-use acknowledgement (`hdx_cod_ebola`)

The INRB-UMIE repository README asks anyone intending to use the epidemiological
data before the team's publication to contact the data producers. Ebola Watch
honours that request architecturally: the connector runs only when the operator
adds `hdx_cod_ebola` to `EW_SOURCE_ACKNOWLEDGEMENTS`. Contact details are in the
upstream README (github.com/INRB-UMIE/BDBV2026-Data). With it disabled, the
system runs on WHO bulletins (about fortnightly) and the ECDC page (weekdays).

## Unofficial and media sources

| Key | Source | Access | Status (tested) |
|---|---|---|---|
| `gdelt_doc` | GDELT DOC 2.0 news search (en, fr, sw, pt, ar) | public API, ≤ 1 request / 5 s | **Partially working** — 101 articles retrieved; aggressive rate limiting (HTTP 429) on some language queries |
| `reliefweb` | ReliefWeb reports | API v2 | **Requires configuration** — the API rejects unapproved appnames (verified: HTTP 403 "not using an approved appname"); set `EW_RELIEFWEB_APPNAME` |
| `promed` | ProMED | subscription feed | **Requires configuration** — `EW_PROMED_FEED_URL` for a licensed feed |
| `local_feeds` | Local newspapers / radio stations | operator-listed RSS/Atom (`EW_RSS_FEEDS`) | **Requires configuration** |
| `reddit` | Reddit public posts | Data API (OAuth application-only) | **Requires configuration**; implemented, not tested live (no credentials) |
| `youtube` | YouTube video titles/descriptions | Data API v3 key | **Requires configuration**; implemented, not tested live |
| `x` | X public posts | API v2 recent search (paid tier) | **Requires configuration**; implemented, not tested live |
| `facebook` | Facebook | — | **Unsupported**: no general public-content search API (CrowdTangle discontinued; Meta Content Library needs approved research access); scraping is prohibited by Meta's terms |
| `telegram` | Telegram public channels | — | **Unsupported** for unattended use: the Bot API cannot read channels without being added by the owner, and the client API requires logging in as a person |

Only public content reachable through sanctioned interfaces is used. No
connector logs in as an individual, joins private groups, reads private
messages, or works around access controls (401/403 responses are reported as
unavailable and not retried with workarounds). News connectors collect titles,
short descriptions, dates and links only.

## Reference data

| Key / file | Source | Licence | Status |
|---|---|---|---|
| `worldbank_population` | World Bank WDI SP.POP.TOTL | CC BY 4.0 | **Working** (261 countries) |
| `osm_overpass` | OpenStreetMap via Overpass API | ODbL 1.0 | **Working** (infrastructure-mapping checks only) |
| `data/boundaries/admin0.geojson` | Natural Earth 1:50m countries | public domain | bundled (simplified) |
| `data/boundaries/admin1_priority.geojson` | geoBoundaries gbOpen ADM1 (14 priority countries) | per country: ODbL, CC BY, CC BY-SA, CC0, public domain — recorded per feature | bundled (simplified); see NOTICE.md |
| `data/gazetteer/cod_health_zones.json` | DRC health-zone names/provinces; WorldPop population totals via INRB-UMIE build | names: factual; populations: CC BY 4.0 (WorldPop) | bundled |
| `data/transport/corridors.yaml` | curated corridor list; statuses default to *unknown* | COSL (this project) | bundled; needs regional verification |
| `data/literature/estimates.yaml` | published estimates (Imperial College London, 20 May 2026) | quoted with citation | pending reviewer verification |

Rebuild scripts: `scripts/build_boundaries.py`, `scripts/build_health_zone_gazetteer.py`.

## Adding a source

1. Implement a `Connector` (see `sources/base.py`) with honest
   `configuration_problem()` and `fetch()` that returns `ConnectorStatus`
   rather than raising on availability problems.
2. Register it in `sources/registry.py`.
3. Document access conditions here; set `requires_acknowledgement=True` when the
   provider attaches conditions beyond the licence.
4. Add a mocked-HTTP test and, if possible, a `@pytest.mark.live` check.
