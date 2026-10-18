# Ebola Watch dashboard

React + TypeScript single-page app (Vite). In production it is built to
`frontend/dist/` and served by the FastAPI backend from the same origin, under
a strict Content Security Policy (no inline scripts, no third-party hosts, no
web fonts, no map tile servers — maps are drawn locally with `d3-geo` from the
API's simplified boundaries).

## Develop

```bash
# terminal 1 — backend (from the repository root)
.venv/bin/ebolawatch serve --port 8765

# terminal 2 — dashboard with hot reload (proxies /api to :8765)
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

## Build

```bash
cd frontend
npm ci
npm run build      # type-checks, then writes dist/ (index.html + assets/)
```

Restart the backend after the first build: it mounts `dist/assets` and serves
`index.html` for client-side routes when `dist/` exists at start-up.

## Structure

| Path | Contents |
|------|----------|
| `src/api.ts` | Typed API client and response types (errors and HTTP 429 handled) |
| `src/hooks.ts` | `useApi` (loading/error/cache), `useWidth`, `useDocumentTitle` |
| `src/components/` | Layout, badges (severity and confidence are separate badges), tiles, tables, safe Markdown renderer, ask box |
| `src/charts/` | SVG charts (cumulative series with forecast fan, weekly bars, R_t, evaluation) and the map |
| `src/pages/` | Overview, Map, Regions, Region detail, Evidence, Forecasts & evaluation, Transport, Reports, Sources, Ask, Methodology & ethics, Report an error, Review |
| `src/styles.css` | Design tokens (light and dark, both selected), layout and chart styles |

## Design rules applied

* Official counts, model estimates, forecasts, scenarios and unverified signals
  are always labelled as such and never merged into one number or colour.
* "Insufficient evidence for a reliable numerical estimate." is rendered
  verbatim whenever the API reports an insufficient estimate.
* Severity uses a validated one-hue ordinal ramp (levels 1–4) plus an icon and
  text label; level 0 is neutral; "insufficient information" uses a hatch
  texture. Confidence is a separate badge.
* Every chart has a legend (≥2 series), a hover tooltip and a table view; one
  y-axis per chart.
* Light and dark themes follow the OS setting and can be overridden with the
  theme button (stored in `localStorage` as a convenience only).
* The reviewer API key is kept in `sessionStorage` (cleared when the tab
  closes) and sent only to this site's API.
* Keyboard: skip link, visible focus, focusable map regions (Enter opens the
  regional view) and a table alternative for every map layer.
