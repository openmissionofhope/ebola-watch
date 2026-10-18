"""Reference-data seeding: sources, regions, outbreaks, transport corridors."""

from __future__ import annotations

import json
from datetime import date

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import Outbreak, Region, Source, TransportEdge, TransportNode
from ..nlp.gazetteer import ISO_3166_2, admin1_code, load_gazetteer
from ..sources.registry import all_connectors
from ..transport.seed import load_corridors

PRIORITY_ISO3 = ["COD", "COG", "CAF", "UGA", "RWA", "BDI", "SSD", "SDN", "KEN", "TZA", "AGO", "CMR", "GAB", "GNQ"]


def seed_sources(session: Session, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    n = 0
    for c in all_connectors(settings):
        info = c.info
        src = session.scalar(select(Source).where(Source.key == info.key))
        if src is None:
            src = Source(key=info.key)
            session.add(src)
            n += 1
        src.name, src.institution, src.category = info.name, info.institution, info.category.value
        src.access_method, src.homepage, src.license = info.access_method, info.homepage, info.license
        src.terms_note, src.attribution = info.terms_note, info.attribution
        problem = c.configuration_problem(settings)
        if problem:
            src.status, src.status_message = problem[0].value, problem[1]
        elif src.status in (None, "unknown", "requires_configuration", "requires_acknowledgement", "disabled"):
            src.status, src.status_message = "configured", "not yet run"
    for key, name, cat in [("manual", "Manual import by reviewers", "official_national"),
                           ("community", "Community error reports and submissions", "community")]:
        if session.scalar(select(Source).where(Source.key == key)) is None:
            session.add(Source(key=key, name=name, category=cat, access_method="manual", status="configured"))
    session.flush()
    return n


def _round(v, nd=1):
    return round(float(v), nd) if v is not None else None


def seed_regions(session: Session, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    g = load_gazetteer(str(settings.data_dir))
    existing = {r.code: r for r in session.scalars(select(Region))}
    created = 0
    admin0 = json.loads((settings.data_dir / "boundaries" / "admin0.geojson").read_text())
    for f in admin0["features"]:
        p = f["properties"]
        iso3 = p["iso3"]
        if not iso3 or iso3 == "-99":
            continue
        r = existing.get(iso3)
        if r is None:
            r = Region(code=iso3, name=p["name"], level=0, iso3=iso3[:3])
            session.add(r)
            existing[iso3] = r
            created += 1
        r.geometry = f["geometry"]
        r.centroid_lat, r.centroid_lon = _round(p.get("label_lat")), _round(p.get("label_lon"))
        r.priority = iso3 in PRIORITY_ISO3
        r.aliases = sorted({k for k, v in g.names.items() if v[0] == iso3})[:30]
    session.flush()
    admin1 = json.loads((settings.data_dir / "boundaries" / "admin1_priority.geojson").read_text())
    for f in admin1["features"]:
        p = f["properties"]
        code = admin1_code(p)
        if not code:
            continue
        parent = existing.get(p["iso3"])
        r = existing.get(code)
        raw = p.get("iso_3166_2")
        if r is None and raw in existing and not ISO_3166_2.match(raw):  # stored under an invalid code: rename in place
            r = existing.pop(raw)
            r.code = code
            existing[code] = r
        if r is None:
            r = Region(code=code, name=g.canonical.get(code, p["name"]), level=1, iso3=p["iso3"], parent_id=parent.id if parent else None)
            session.add(r)
            existing[code] = r
            created += 1
        r.name = g.canonical.get(code, p["name"])
        r.geometry = f["geometry"]
        r.centroid_lat, r.centroid_lon = _round(p.get("label_lat")), _round(p.get("label_lon"))
        r.priority = True
        r.aliases = sorted({k for k, v in g.names.items() if v[0] == code})[:20]
    session.flush()
    return created


def ensure_health_zone(session: Session, code: str) -> Region | None:
    """Create a level-2 region for a health-zone code on first use (no geometry)."""
    r = session.scalar(select(Region).where(Region.code == code))
    if r:
        return r
    g = load_gazetteer()
    prov = g.parents.get(code)
    parent = session.scalar(select(Region).where(Region.code == prov)) if prov else None
    if parent is None:
        return None
    r = Region(code=code, name=g.canonical.get(code, code.split(":")[-1]), level=2, iso3=parent.iso3, parent_id=parent.id,
               population=g.populations.get(code), population_source="WorldPop (CC BY 4.0) via INRB-UMIE gazetteer",
               centroid_lat=parent.centroid_lat, centroid_lon=parent.centroid_lon)
    session.add(r)
    session.flush()
    return r


def seed_outbreaks(session: Session, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    data = yaml.safe_load((settings.data_dir / "outbreaks.yaml").read_text())
    n = 0
    for o in data["outbreaks"]:
        ob = session.scalar(select(Outbreak).where(Outbreak.key == o["key"]))
        if ob is None:
            ob = Outbreak(key=o["key"])
            session.add(ob)
            n += 1
        ob.name, ob.pathogen, ob.primary_iso3 = o["name"], o["pathogen"], o["iso3"]
        ob.declared_on = _date(o.get("declared_on"))
        ob.ended_on = _date(o.get("ended_on"))
        ob.notes = o.get("citation")
    session.flush()
    return n


def _date(v):
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def seed_transport(session: Session, settings: Settings | None = None) -> int:
    """Add corridor edges. Existing edges keep their (admin-managed) statuses."""
    settings = settings or get_settings()
    data = load_corridors(settings.data_dir)
    regions = {r.code: r for r in session.scalars(select(Region).where(Region.level <= 1))}
    nodes = {n.key: n for n in session.scalars(select(TransportNode))}

    def node(code: str) -> TransportNode | None:
        if code in nodes:
            return nodes[code]
        r = regions.get(code)
        if r is None or r.centroid_lat is None:
            return None
        n = TransportNode(key=code, name=r.name, kind="admin_unit", region_id=r.id, iso3=r.iso3,
                          lat=round(r.centroid_lat, 1), lon=round(r.centroid_lon, 1))
        session.add(n)
        session.flush()
        nodes[code] = n
        return n

    added = 0
    for e in data["edges"]:
        a, b = node(e["from"]), node(e["to"])
        if a is None or b is None:
            continue
        edge = session.scalar(select(TransportEdge).where(TransportEdge.key == e["key"]))
        if edge is not None:
            continue
        session.add(TransportEdge(
            key=e["key"], from_node_id=a.id, to_node_id=b.id, mode=e["mode"], corridor=e.get("corridor"),
            cross_border=bool(e.get("cross_border")), physical_status=e["physical_status"], service_status=e["service_status"],
            verification=e["verification"], sources=e.get("sources", []), seasonal_note=e.get("seasonal_note"),
            disruption_note=e.get("disruption_note"), notes=e.get("notes"),
        ))
        added += 1
    session.flush()
    return added


def sync_postgis(session: Session) -> bool:
    """Populate the PostGIS geometry column from GeoJSON when running on PostGIS."""
    from sqlalchemy import text

    if session.get_bind().dialect.name != "postgresql":
        return False
    has_col = session.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='regions' AND column_name='geom'")).first()
    if not has_col:
        return False
    session.execute(text("UPDATE regions SET geom = ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(geometry::text), 4326)) "
                         "WHERE geometry IS NOT NULL AND geom IS NULL"))
    return True


def seed_literature(session: Session, settings: Settings | None = None) -> int:
    from ..db.models import LiteratureEstimate

    settings = settings or get_settings()
    path = settings.data_dir / "literature" / "estimates.yaml"
    if not path.exists():
        return 0
    n = 0
    for e in yaml.safe_load(path.read_text()).get("estimates", []):
        row = session.scalar(select(LiteratureEstimate).where(LiteratureEstimate.key == e["key"]))
        if row is None:
            row = LiteratureEstimate(key=e["key"])
            session.add(row)
            n += 1
        row.region_code, row.quantity, row.as_of = e["region_code"], e["quantity"], _date(e["as_of"])
        row.lower, row.upper, row.central = e.get("lower"), e.get("upper"), e.get("central")
        row.statement, row.citation, row.url = e["statement"], e["citation"], e.get("url")
        if row.validation_status != "verified":
            row.validation_status = e.get("validation_status", "pending_review")
    session.flush()
    return n


def seed_all(session: Session, settings: Settings | None = None) -> dict:
    out = {
        "sources": seed_sources(session, settings),
        "regions": seed_regions(session, settings),
        "outbreaks": seed_outbreaks(session, settings),
        "transport_edges": seed_transport(session, settings),
        "literature_estimates": seed_literature(session, settings),
    }
    out["postgis"] = sync_postgis(session)
    return out
