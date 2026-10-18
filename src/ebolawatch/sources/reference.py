"""Reference-data connectors: population (World Bank) and transport-infrastructure
checks (OpenStreetMap Overpass)."""

from __future__ import annotations

from datetime import UTC, datetime

from ..config import Settings
from ..domain.enums import ConnectorStatus, SourceCategory
from .base import Connector, ConnectorResult, FetchedItem, SourceInfo
from .http import HttpClient, SourceUnavailable

WB_URL = "https://api.worldbank.org/v2/country/{codes}/indicator/SP.POP.TOTL"


class WorldBankPopulationConnector(Connector):
    info = SourceInfo(
        key="worldbank_population",
        name="World Bank World Development Indicators: total population (SP.POP.TOTL)",
        institution="World Bank",
        category=SourceCategory.REFERENCE,
        access_method="World Bank Indicators API v2",
        homepage="https://data.worldbank.org/indicator/SP.POP.TOTL",
        license="CC BY 4.0",
        terms_note=None,
        attribution="World Bank, World Development Indicators",
    )

    def __init__(self, iso3_codes: list[str] | None = None):
        self.iso3_codes = iso3_codes

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        codes = self.iso3_codes or ["all"]
        pops: dict[str, dict] = {}
        try:
            for i in range(0, len(codes), 60):
                chunk = ";".join(codes[i:i + 60])
                page = 1
                while True:
                    data = client.get_json(WB_URL.format(codes=chunk), params={"format": "json", "mrnev": "1", "per_page": "400", "page": str(page)})
                    if not isinstance(data, list) or len(data) < 2 or data[1] is None:
                        break
                    for row in data[1]:
                        iso3 = row.get("countryiso3code")
                        if iso3 and row.get("value") is not None:
                            year = int(row["date"])
                            if iso3 not in pops or year > pops[iso3]["year"]:  # keep the most recent value
                                pops[iso3] = {"population": int(row["value"]), "year": year}
                    if page >= int(data[0].get("pages", 1)):
                        break
                    page += 1
        except SourceUnavailable as e:
            return ConnectorResult(ConnectorStatus.UNAVAILABLE, [], str(e))
        item = FetchedItem(
            external_id=f"SP.POP.TOTL:{datetime.now(UTC).date()}",
            url=self.info.homepage, title="World Bank population", published_at=None, text=None,
            meta={"populations": pops},
        )
        return ConnectorResult(ConnectorStatus.OK, [item], f"population for {len(pops)} countries")


OVERPASS = "https://overpass-api.de/api/interpreter"


class OverpassTransportConnector(Connector):
    """Checks whether transport infrastructure named in the curated corridor file
    is mapped in OpenStreetMap. A mapped feature documents *physical existence*
    only; it is never treated as evidence of an operating passenger service."""

    info = SourceInfo(
        key="osm_overpass",
        name="OpenStreetMap (Overpass API) infrastructure checks",
        institution="OpenStreetMap contributors",
        category=SourceCategory.REFERENCE,
        access_method="Overpass API (rate-limited, read-only)",
        homepage="https://www.openstreetmap.org/",
        license="ODbL 1.0",
        terms_note="Attribution required: © OpenStreetMap contributors. Queries are small and rate-limited per the Overpass usage policy.",
        attribution="© OpenStreetMap contributors (ODbL)",
    )

    def __init__(self, checks: list[dict] | None = None):
        self.checks = checks

    def fetch(self, client: HttpClient, settings: Settings, since=None) -> ConnectorResult:
        from ..transport.seed import load_corridors

        checks = self.checks
        if checks is None:
            checks = [
                {"edge_key": e["key"], **e["osm_check"]}
                for e in load_corridors(settings.data_dir)["edges"]
                if e.get("osm_check")
            ]
        results: dict[str, dict] = {}
        errors = []
        for chk in checks:
            s, w, n, e = chk["bbox"]
            q = f"[out:json][timeout:25];({chk['selector']}({s},{w},{n},{e}););out ids tags 50;"
            try:
                data = client.post(OVERPASS, data={"data": q}).json()
            except (SourceUnavailable, ValueError) as ex:
                errors.append(f"{chk['edge_key']}: {ex}")
                continue
            els = data.get("elements", [])
            results[chk["edge_key"]] = {
                "mapped_features": len(els),
                "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "selector": chk["selector"],
            }
        status = ConnectorStatus.OK if not errors else (ConnectorStatus.PARTIAL if results else ConnectorStatus.UNAVAILABLE)
        item = FetchedItem(
            external_id=f"overpass:{datetime.now(UTC).date()}", url=OVERPASS, title="OSM infrastructure checks",
            published_at=None, text=None, meta={"checks": results, "errors": errors},
        )
        return ConnectorResult(status, [item], f"{len(results)} checks completed" + (f"; {len(errors)} failed" if errors else ""))
