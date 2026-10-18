"""Static snapshot of the public API and dashboard, for hosting without a server
(for example GitHub Pages).

Every data file is produced by calling the public API in-process, so a snapshot
applies exactly the same publication policy as the live API (resolution cap,
small-area and complementary suppression, paraphrased signals). Only public
``GET`` endpoints are exported; nothing from the administrative API is.

Layout of the output directory::

    index.html, assets/        dashboard built with VITE_STATIC=1
    <route>/index.html         copies of index.html so deep links load
    404.html                   the dashboard again (unknown paths)
    data/<path>.json           GET /api/v1/<path>
    data/reports/<id>.md       report Markdown
    data/export/<name>.csv     CSV exports
    data/index.json            manifest of the data files
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ..config import Settings, get_settings

MARKER = ".ebolawatch-site"
STATIC_BUILD_FLAG = '<meta name="ebolawatch-build" content="static"'
GLOBAL_ENDPOINTS = ("meta", "overview", "regions", "map/geometry/0", "map/geometry/1", "map/layers", "severity",
                    "surveillance-quality", "transport", "signals", "alerts", "sources", "evaluation", "reports")
REGION_ENDPOINTS = ("summary", "official-series", "estimates", "forecasts", "forecast-comparison", "evidence", "transport")
CSV_DATASETS = ("summaries", "subnational")
SPA_ROUTES = ("map", "regions", "evidence", "evaluation", "transport", "reports", "sources", "methodology", "report-error", "languages")
PAGES_SIZE_WARNING = 500 * 1024 * 1024


class ExportError(RuntimeError):
    pass


def _prepare(out: Path) -> None:
    if out.exists():
        if (out / MARKER).exists():
            shutil.rmtree(out)
        elif any(out.iterdir()):
            raise ExportError(f"{out} is not empty and was not created by export-static; refusing to overwrite it")
    out.mkdir(parents=True, exist_ok=True)


def _check_frontend(dist: Path) -> str:
    index = dist / "index.html"
    if not index.is_file():
        raise ExportError(f"{index} not found: build the dashboard first (VITE_STATIC=1 npm run build)")
    html = index.read_text(encoding="utf-8")
    if STATIC_BUILD_FLAG not in html:
        raise ExportError("the dashboard build is not a static build (it would call /api/v1); rebuild with VITE_STATIC=1")
    return html


def export_static(out: Path, frontend_dist: Path | None = None, cname: str | None = None,
                  settings: Settings | None = None) -> dict:
    """Write a complete static site (or only ``data/`` when ``frontend_dist`` is None)."""
    settings = settings or get_settings()
    index_html = _check_frontend(frontend_dist) if frontend_dist is not None else None
    _prepare(out)

    from ..api.app import create_app

    # the snapshot is one client making many requests: lift the per-client limits
    app_settings = settings.model_copy(update={"rate_limit_per_minute": 10**9, "export_rate_limit_per_hour": 10**9})
    client = TestClient(create_app(app_settings), base_url="http://snapshot.local")
    data = out / "data"
    written: list[str] = []
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    def fetch(path: str, params: dict | None = None):
        r = client.get(f"/api/v1{path}", params=params)
        if r.status_code != 200:
            raise ExportError(f"GET /api/v1{path} returned HTTP {r.status_code}")
        return r

    def write(rel: str, content: str) -> None:
        target = data / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel)

    def write_json(rel: str, payload) -> None:
        write(rel, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    for path in GLOBAL_ENDPOINTS:
        payload = fetch(f"/{path}").json()
        if path == "meta":
            payload |= {"static": True, "snapshot_generated_at": generated_at}
        write_json(f"{path}.json", payload)

    report_ids = [r["id"] for r in json.loads((data / "reports.json").read_text(encoding="utf-8"))]
    for rid in report_ids:
        write_json(f"reports/{rid}.json", fetch(f"/reports/{rid}").json())
        write(f"reports/{rid}.md", fetch(f"/reports/{rid}", {"format": "markdown"}).text)

    regions = json.loads((data / "regions.json").read_text(encoding="utf-8"))
    for region in regions:
        code = region["code"]
        if not code.replace("-", "").replace("_", "").isalnum():
            raise ExportError(f"unexpected region code {code!r}")
        for ep in REGION_ENDPOINTS:
            write_json(f"regions/{code}/{ep}.json", fetch(f"/regions/{code}/{ep}").json())
        if region["level"] == 0:
            write_json(f"regions/{code}/subnational.json", fetch(f"/regions/{code}/subnational").json())

    for name in CSV_DATASETS:
        write(f"export/{name}.csv", fetch(f"/export/{name}.csv").text)

    write_json("index.json", {
        "name": "Ebola Watch static data", "generated_at": generated_at,
        "note": "Each file is the response of the corresponding public API endpoint (GET /api/v1/<path>), "
                "with the same publication policy. See docs/API.md.",
        "files": sorted(written),
    })

    if index_html is not None:
        for item in frontend_dist.iterdir():
            dest = out / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)
        routes = list(SPA_ROUTES) + [f"region/{r['code']}" for r in regions] + [f"reports/{rid}" for rid in report_ids]
        for route in routes:
            (out / route).mkdir(parents=True, exist_ok=True)
            (out / route / "index.html").write_text(index_html, encoding="utf-8")
        (out / "404.html").write_text(index_html, encoding="utf-8")
        (out / ".nojekyll").write_text("", encoding="utf-8")
    if cname:
        (out / "CNAME").write_text(cname.strip() + "\n", encoding="utf-8")
    (out / MARKER).write_text(generated_at + "\n", encoding="utf-8")

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    result = {"generated_at": generated_at, "data_files": len(written), "regions": len(regions), "reports": len(report_ids),
              "bytes": size}
    if size > PAGES_SIZE_WARNING:
        result["warning"] = "site exceeds 500 MB; GitHub Pages sites are limited to 1 GB"
    return result
