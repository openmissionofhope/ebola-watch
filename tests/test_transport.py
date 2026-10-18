"""Transport-network scenarios (9, 10, 11)."""

from sqlalchemy import select

from ebolawatch.db.models import AuditLog, TransportEdge, TransportStatusChange
from ebolawatch.review.queue import ReviewError, set_transport_status
from ebolawatch.transport.network import EdgeSpec, build_graph, edge_weight, introduction_ranking

E = [
    EdgeSpec("road-a-b", "A", "B", "road", "operational", "documented", "official"),
    EdgeSpec("rail-b-c", "B", "C", "rail", "non_operational", "documented", "secondary"),
    EdgeSpec("river-a-d", "A", "D", "river", "unknown", "unverified", "unverified"),
    EdgeSpec("road-a-e", "A", "E", "road", "unknown", "documented", "mapped_only"),
]


def test_scenario_09_railway_that_exists_but_does_not_operate_carries_no_connectivity():
    assert edge_weight(E[1]) == 0
    g = build_graph(E)
    assert not g.has_edge("B", "C")
    ranking = {r["unit"]: r for r in introduction_ranking(E, {"B": 100})}
    assert "C" not in ranking or ranking["C"]["path_modes"] != ["rail"]


def test_scenario_10_river_without_verified_passenger_service_is_a_scenario_not_a_fact():
    assert edge_weight(E[2], "closed") == 0
    assert 0 < edge_weight(E[2], "partial") < edge_weight(E[2], "open")
    rows = {r["unit"]: r for r in introduction_ranking(E, {"A": 100}, {"A": (0, 0), "D": (1, 1), "E": (0, 2)})}
    d = rows["D"]
    assert d["relative_score"]["closed"] == 0 and d["share_unverified_links"] == 1.0
    assert d["straight_line_km_from_nearest_source"] is not None


def test_scenario_11_ferry_stops_operating(session):
    edge = session.scalar(select(TransportEdge).where(TransportEdge.key == "lake-kivu-nk-sk"))
    assert edge.service_status == "unknown"
    try:
        set_transport_status(session, "lake-kivu-nk-sk", "suspended", "x", "tester")
        raise AssertionError("evidence should be required")
    except ReviewError:
        pass
    set_transport_status(session, "lake-kivu-nk-sk", "suspended", "SYNTHETIC test: operator announced suspension", "tester")
    session.flush()
    assert edge.service_status == "suspended"
    hist = list(session.scalars(select(TransportStatusChange).where(TransportStatusChange.edge_id == edge.id)))
    assert hist and hist[0].old_status == "unknown" and hist[0].new_status == "suspended"
    assert session.scalar(select(AuditLog).where(AuditLog.action == "transport_status_change"))
    spec = EdgeSpec(edge.key, "CD-NK", "CD-SK", edge.mode, edge.service_status, edge.physical_status, edge.verification)
    assert edge_weight(spec, "open") == 0
