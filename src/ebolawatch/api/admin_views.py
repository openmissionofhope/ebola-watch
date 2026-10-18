"""Reviewer-facing detail views. Reviewers see redacted source text (within its
retention period) so they can verify claims; nothing here is public."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.models import Alert, Document, ErrorReport, Observation, ReviewItem, Signal, SignalCluster


def review_detail(session: Session, item: ReviewItem) -> dict:
    base = {"id": item.id, "item_type": item.item_type, "item_id": item.item_id, "reason": item.reason, "status": item.status}
    if item.item_type == "observation" and (o := session.get(Observation, item.item_id)):
        base["observation"] = {"region_id": o.region_id, "metric": o.metric, "case_class": o.case_class, "value_type": o.value_type,
                               "transmission": o.transmission, "as_of": o.as_of.isoformat(), "value": o.value, "quote": o.quote,
                               "citation": o.citation, "notes": o.validation_notes, "extraction_method": o.extraction_method}
    elif item.item_type == "signal" and (sg := session.get(Signal, item.item_id)):
        doc = session.get(Document, sg.document_id)
        base["signal"] = {"claim_type": sg.claim_type, "report_kind": sg.report_kind, "relevance": sg.relevance,
                          "languages": sg.languages, "features": sg.features, "translation_quality": sg.translation_quality,
                          "review_reasons": sg.review_reasons,
                          "redacted_text": doc.text_minimized if doc else None, "safety_flags": doc.safety_flags if doc else []}
    elif item.item_type == "cluster" and (cl := session.get(SignalCluster, item.item_id)):
        base["cluster"] = {"summary": cl.summary, "assessment": cl.assessment, "corroboration": cl.corroboration,
                           "evidence": cl.evidence, "n_documents": cl.n_documents, "n_independent_origins": cl.n_independent_origins}
    elif item.item_type == "alert" and (a := session.get(Alert, item.item_id)):
        base["alert"] = {"kind": a.kind, "message": a.message, "evidence": a.evidence, "relies_on_unofficial": a.relies_on_unofficial}
    elif item.item_type == "correction" and (er := session.get(ErrorReport, item.item_id)):
        base["error_report"] = {"target_type": er.target_type, "target_ref": er.target_ref, "description": er.description,
                                "organisation": er.organisation}
    return base
