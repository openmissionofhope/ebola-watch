"""Multimodal connectivity model.

Connectivity is not transmission. Ebola spreads through direct contact with
symptomatic or deceased people; travel matters because an infected person in
the 2–21-day incubation period, or early in illness, can move between areas.
The model therefore produces *relative* connectivity and introduction-risk
rankings under explicit scenarios, never individual-level predictions.

Edge weight = mode propensity x service factor. Service factors:

    operational 1.0 | intermittent 0.5 | seasonal 0.5 | suspended 0 | non_operational 0
    unknown -> scenario value: closed 0.0 | partial 0.3 | open 1.0

No passenger volumes are assumed. Mode propensities are relative scenario
weights documented in METHODOLOGY.md, not measured frequencies.

Effective distance (Brockmann & Helbing, Science 2013) uses
d_ij = 1 - log(P_ij), with P_ij = w_ij / sum_k w_ik, along the shortest path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

from ..domain.enums import ServiceStatus

MODE_PROPENSITY = {"road": 1.0, "rail": 0.6, "river": 0.5, "lake": 0.4, "air": 0.3, "informal": 0.3}
SERVICE_FACTOR = {
    ServiceStatus.OPERATIONAL: 1.0, ServiceStatus.INTERMITTENT: 0.5, ServiceStatus.SEASONAL: 0.5,
    ServiceStatus.SUSPENDED: 0.0, ServiceStatus.NON_OPERATIONAL: 0.0,
}
UNKNOWN_SCENARIOS = {"closed": 0.0, "partial": 0.3, "open": 1.0}


@dataclass(frozen=True)
class EdgeSpec:
    key: str
    a: str
    b: str
    mode: str
    service_status: str
    physical_status: str
    verification: str
    cross_border: bool = False
    corridor: str | None = None
    seasonal_note: str | None = None


def edge_weight(e: EdgeSpec, unknown_scenario: str = "partial") -> float:
    st = ServiceStatus(e.service_status)
    factor = SERVICE_FACTOR.get(st, UNKNOWN_SCENARIOS[unknown_scenario])
    if e.physical_status == "unverified" and st == ServiceStatus.UNKNOWN:
        factor *= 0.5  # neither infrastructure nor service is documented
    return MODE_PROPENSITY.get(e.mode, 0.3) * factor


def build_graph(edges: list[EdgeSpec], unknown_scenario: str = "partial") -> nx.Graph:
    """Undirected graph between admin units; parallel modes are summed into one weight."""
    g = nx.Graph()
    for e in edges:
        w = edge_weight(e, unknown_scenario)
        if g.has_edge(e.a, e.b):
            g[e.a][e.b]["weight"] += w
            g[e.a][e.b]["modes"].append(e.mode)
            g[e.a][e.b]["edges"].append(e.key)
        else:
            g.add_edge(e.a, e.b, weight=w, modes=[e.mode], edges=[e.key])
    to_drop = [(u, v) for u, v, d in g.edges(data=True) if d["weight"] <= 0]
    g.remove_edges_from(to_drop)
    return g


def effective_distances(g: nx.Graph, sources: list[str]) -> dict[str, tuple[float, list[str]]]:
    """Shortest effective distance from any source node, with the path."""
    dg = nx.DiGraph()
    for u in g.nodes:
        total = sum(d["weight"] for _, _, d in g.edges(u, data=True))
        for _, v, d in g.edges(u, data=True):
            p = d["weight"] / total
            dg.add_edge(u, v, cost=1 - math.log(p))
    out: dict[str, tuple[float, list[str]]] = {}
    srcs = [s for s in sources if s in dg]
    if not srcs:
        return out
    dist, paths = nx.multi_source_dijkstra(dg, srcs, weight="cost")
    for node, d in dist.items():
        out[node] = (d, paths[node])
    return out


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def introduction_ranking(edges: list[EdgeSpec], source_weights: dict[str, float], coords: dict[str, tuple[float, float]] | None = None) -> list[dict]:
    """Relative introduction-risk ranking of non-source units under each unknown-service scenario.

    ``source_weights``: unit -> recent reported incidence (or any non-negative weight).
    Returns rows with a relative score per scenario (normalised so the top unit = 1),
    the rank range across scenarios, effective and straight-line distances, and the
    share of the best path made of unverified links.
    """
    sources = [s for s, w in source_weights.items() if w > 0]
    by_key = {e.key: e for e in edges}
    scenario_scores: dict[str, dict[str, float]] = {}
    paths_central: dict[str, list[str]] = {}
    dist_central: dict[str, float] = {}
    for sc in UNKNOWN_SCENARIOS:
        g = build_graph(edges, sc)
        scores: dict[str, float] = {}
        for src in sources:
            if src not in g:
                continue
            for node, (d, path) in effective_distances(g, [src]).items():
                if node in source_weights and source_weights[node] > 0:
                    continue
                scores[node] = scores.get(node, 0.0) + source_weights[src] * math.exp(-d)
                if sc == "partial" and (node not in dist_central or d < dist_central[node]):
                    dist_central[node] = d
                    paths_central[node] = path
        top = max(scores.values(), default=0) or 1.0
        scenario_scores[sc] = {k: v / top for k, v in scores.items()}

    g_partial = build_graph(edges, "partial")
    nodes = set().union(*[set(s) for s in scenario_scores.values()]) if scenario_scores else set()
    rows = []
    ranks = {sc: {n: i + 1 for i, (n, _) in enumerate(sorted(s.items(), key=lambda kv: -kv[1]))} for sc, s in scenario_scores.items()}
    for n in nodes:
        path = paths_central.get(n, [])
        unverified_links = 0
        links = 0
        modes = []
        for a, b in zip(path, path[1:], strict=False):
            if g_partial.has_edge(a, b):
                links += 1
                keys = g_partial[a][b]["edges"]
                modes.extend(g_partial[a][b]["modes"])
                if all(by_key[k].verification in ("unverified", "mapped_only") and by_key[k].service_status == "unknown" for k in keys):
                    unverified_links += 1
        straight = None
        if coords and path and path[0] in coords and n in coords:
            straight = round(haversine_km(coords[path[0]], coords[n]))
        rows.append({
            "unit": n,
            "relative_score": {sc: round(scenario_scores[sc].get(n, 0.0), 4) for sc in scenario_scores},
            "rank": {sc: ranks[sc].get(n) for sc in ranks},
            "effective_distance": round(dist_central[n], 2) if n in dist_central else None,
            "straight_line_km_from_nearest_source": straight,
            "path": path,
            "path_modes": sorted(set(modes)),
            "share_unverified_links": round(unverified_links / links, 2) if links else None,
        })
    rows.sort(key=lambda r: -(r["relative_score"].get("partial") or 0))
    for r in rows:
        rs = [x for x in r["rank"].values() if x]
        r["rank_range"] = [min(rs), max(rs)] if rs else None
        p = r["relative_score"].get("partial", 0)
        r["tier"] = "higher" if p >= 0.5 else "moderate" if p >= 0.15 else "lower"
        r["robust"] = bool(rs) and (max(rs) - min(rs) <= 2)
    return rows
