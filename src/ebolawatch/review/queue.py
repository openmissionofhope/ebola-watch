"""Human-oversight primitives: review queue, audit trail, corrections."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import (
    Alert,
    AuditLog,
    Correction,
    Observation,
    ReviewItem,
    SignalCluster,
    SituationReport,
    TransportEdge,
    TransportStatusChange,
)
from ..domain.enums import ReviewStatus, ServiceStatus, ValidationStatus

SAFE_DETAIL_KEYS = {"reason", "status", "old", "new", "note", "count", "source", "level", "kind", "fields"}


def audit(session: Session, actor: str, action: str, target_type: str | None = None, target_id=None, details: dict | None = None) -> None:
    """Append a non-sensitive audit record (no request bodies, no free text beyond short notes)."""
    clean = {k: (str(v)[:300] if isinstance(v, str) else v) for k, v in (details or {}).items() if k in SAFE_DETAIL_KEYS}
    session.add(AuditLog(actor=actor[:64], action=action[:64], target_type=target_type, target_id=str(target_id) if target_id is not None else None, details=clean))


def enqueue(session: Session, item_type: str, item_id: int, reason: str, priority: int = 2) -> ReviewItem:
    existing = session.scalar(select(ReviewItem).where(ReviewItem.item_type == item_type, ReviewItem.item_id == item_id,
                                                       ReviewItem.status == ReviewStatus.PENDING.value))
    if existing:
        if reason not in existing.reason:
            existing.reason = (existing.reason + "; " + reason)[:2000]
        existing.priority = min(existing.priority, priority)
        return existing
    item = ReviewItem(item_type=item_type, item_id=item_id, reason=reason[:2000], priority=priority)
    session.add(item)
    session.flush()
    return item


class ReviewError(ValueError):
    pass


def decide(session: Session, review_id: int, decision: str, actor: str, note: str | None = None) -> ReviewItem:
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise ReviewError("review item not found")
    if item.status != ReviewStatus.PENDING.value:
        raise ReviewError("review item already resolved")
    if decision not in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, ReviewStatus.NEEDS_MORE_INFO.value):
        raise ReviewError("invalid decision")
    item.status = decision
    item.resolved_at = utcnow()
    item.resolved_by = actor
    item.resolution_note = (note or "")[:1000]
    _apply(session, item, decision, actor)
    audit(session, actor, "review_decision", item.item_type, item.item_id, {"status": decision, "note": note or ""})
    return item


def _apply(session: Session, item: ReviewItem, decision: str, actor: str) -> None:
    approved = decision == ReviewStatus.APPROVED.value
    if decision == ReviewStatus.NEEDS_MORE_INFO.value:
        return
    if item.item_type == "observation":
        obs = session.get(Observation, item.item_id)
        if obs:
            obs.validation_status = ValidationStatus.VERIFIED.value if approved else ValidationStatus.DISPUTED.value
            obs.validation_notes = list(obs.validation_notes or []) + [f"reviewed by {actor}: {decision}"]
    elif item.item_type == "alert":
        alert = session.get(Alert, item.item_id)
        if alert:
            alert.review_status = decision
            if approved:
                alert.published = True
                alert.published_at = utcnow()
    elif item.item_type == "cluster":
        cl = session.get(SignalCluster, item.item_id)
        if cl:
            cl.status = "reviewed_credible" if approved else "reviewed_not_credible"
    elif item.item_type == "report":
        rep = session.get(SituationReport, item.item_id)
        if rep:
            rep.status = "published" if approved else "withdrawn"


def retract(session: Session, target_type: str, target_id: int, public_note: str, actor: str, error_report_id: int | None = None) -> Correction:
    """Retract a published alert/report/observation, keeping a public, non-sensitive record."""
    if target_type == "alert":
        obj = session.get(Alert, target_id)
        if obj is None:
            raise ReviewError("alert not found")
        obj.retracted, obj.retraction_note, obj.published = True, public_note[:1000], False
    elif target_type == "report":
        obj = session.get(SituationReport, target_id)
        if obj is None:
            raise ReviewError("report not found")
        obj.status, obj.retraction_note = "retracted", public_note[:1000]
    elif target_type == "observation":
        obj = session.get(Observation, target_id)
        if obj is None:
            raise ReviewError("observation not found")
        obj.validation_status = ValidationStatus.RETRACTED.value
        obj.validation_notes = list(obj.validation_notes or []) + [f"retracted: {public_note[:200]}"]
    else:
        raise ReviewError("unsupported target type")
    corr = Correction(target_type=target_type, target_id=target_id, action="retraction", public_note=public_note[:1000],
                      error_report_id=error_report_id)
    session.add(corr)
    audit(session, actor, "retraction", target_type, target_id, {"note": public_note[:200]})
    return corr


def set_transport_status(session: Session, edge_key: str, new_status: str, evidence: str, actor: str) -> TransportEdge:
    """Change an edge's service status (e.g. a ferry stops operating), with history."""
    ServiceStatus(new_status)
    if not evidence or len(evidence.strip()) < 10:
        raise ReviewError("a source or explanation (>= 10 characters) is required for a status change")
    edge = session.scalar(select(TransportEdge).where(TransportEdge.key == edge_key))
    if edge is None:
        raise ReviewError("transport edge not found")
    old = edge.service_status
    edge.service_status = new_status
    edge.verified_on = utcnow().date()
    edge.sources = list(edge.sources or []) + [evidence[:300]]
    if edge.verification in ("unverified", "mapped_only"):
        edge.verification = "secondary"
    session.add(TransportStatusChange(edge_id=edge.id, old_status=old, new_status=new_status, evidence=evidence[:1000], actor=actor[:64]))
    audit(session, actor, "transport_status_change", "transport_edge", edge.id, {"old": old, "new": new_status})
    return edge
