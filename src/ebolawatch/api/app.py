"""FastAPI application: public API, administrative API and the dashboard."""

from __future__ import annotations

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__, views
from ..config import get_settings
from ..db.models import Alert, AuditLog, ErrorReport, Region, ReviewItem, SituationReport
from ..domain.enums import Role
from ..privacy.query_guard import QueryGuard
from ..review.queue import ReviewError, audit, decide, enqueue, retract, set_transport_status
from ..safety.scope import DISCLAIMER
from ..safety.untrusted import sanitize
from .deps import get_session
from .query import answer
from .ratelimit import TokenBucket
from .security import client_id, require_role

METRICS = {"cases", "deaths"}
CLASSES = {"confirmed", "probable", "suspected"}
MAX_BODY = 64 * 1024

tags = [
    {"name": "summaries", "description": "Regional summaries: official counts, estimates, severity, confidence"},
    {"name": "series", "description": "Official case series with provenance and revisions"},
    {"name": "models", "description": "Estimates, forecasts, scenarios and model evaluation"},
    {"name": "evidence", "description": "Sources, aggregated unofficial signals, transport context"},
    {"name": "reports", "description": "Published situation reports"},
    {"name": "public-input", "description": "Questions and error reports"},
    {"name": "admin", "description": "Human review, corrections and source management (API key required)"},
]


class QueryIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


class ErrorReportIn(BaseModel):
    target_type: str = Field(..., pattern="^(observation|estimate|forecast|severity|alert|report|signal|transport|other)$")
    target_ref: str | None = Field(None, max_length=128)
    description: str = Field(..., min_length=10, max_length=4000)
    organisation: str | None = Field(None, max_length=255)


class DecisionIn(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected|needs_more_info)$")
    note: str | None = Field(None, max_length=1000)


class RetractIn(BaseModel):
    target_type: str = Field(..., pattern="^(alert|report|observation)$")
    target_id: int
    public_note: str = Field(..., min_length=10, max_length=1000)
    error_report_id: int | None = None


class TransportStatusIn(BaseModel):
    service_status: str = Field(..., pattern="^(operational|intermittent|seasonal|suspended|non_operational|unknown)$")
    evidence: str = Field(..., min_length=10, max_length=1000)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_for_production()
    limiter = TokenBucket(settings.rate_limit_per_minute)
    export_limiter = TokenBucket(settings.export_rate_limit_per_hour // 60 or 1, burst=settings.export_rate_limit_per_hour)
    guard = QueryGuard()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.database_url.startswith("sqlite") and not settings.is_production:
            from ..db.session import create_all

            create_all()
        yield

    app = FastAPI(
        title="Ebola Watch API", version=__version__, lifespan=lifespan, openapi_tags=tags,
        description=(
            "Evidence-based Ebola outbreak monitoring, estimation and forecasting by Open Mission of Hope.\n\n"
            f"**{DISCLAIMER}**\n\n"
            "All outputs apply the same publication policy: first-level administrative resolution at most, small-area and "
            "complementary suppression, paraphrased unofficial signals, and explicit 'insufficient evidence' results. "
            "Official observations, model estimates, forecasts and unverified signals are separate fields and are never combined."
        ),
        docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json",
    )
    app.state.limiter, app.state.guard = limiter, guard
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-API-Key"], allow_credentials=False)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_BODY:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
            cid = client_id(request)
            if not limiter.allow(cid):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "30"})
            if request.method == "GET" and request.query_params:
                if not guard.check(cid, request.url.path, dict(request.query_params)):
                    return JSONResponse({"detail": "too many distinct filter combinations; aggregated data are available "
                                                   "without filtering"}, status_code=429, headers={"Retry-After": "600"})
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if not request.url.path.startswith("/api/docs") and not request.url.path.startswith("/api/redoc"):
            response.headers.setdefault("Content-Security-Policy",
                                        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        return response

    def region_or_404(session: Session, code: str) -> Region:
        r = session.scalar(select(Region).where(Region.code == code.strip().upper()))
        if r is None or r.level > get_settings().public_max_admin_level:
            raise HTTPException(404, "region not found at a publishable resolution")
        return r

    # ---- public ---------------------------------------------------------
    @app.get("/api/v1/meta", tags=["summaries"])
    def meta(session: Session = Depends(get_session)):
        ov = views.overview(session)
        return {"name": "Ebola Watch", "organisation": "Open Mission of Hope", "website": "https://openmissionofhope.org",
                "version": __version__, "model_version": ov["model_version"], "disclaimer": DISCLAIMER,
                "contains_synthetic_data": ov["contains_synthetic_data"], "latest_model_run": ov["latest_model_run"],
                "publication_policy": {"max_admin_level": get_settings().public_max_admin_level,
                                       "min_cell_count": get_settings().min_public_cell_count,
                                       "min_subnational_population": get_settings().min_public_subnational_population}}

    @app.get("/api/v1/overview", tags=["summaries"])
    def overview(session: Session = Depends(get_session)):
        """Dashboard overview: assessed areas, severity map, published alerts, latest official developments."""
        return views.overview(session)

    @app.get("/api/v1/regions", tags=["summaries"])
    def regions(session: Session = Depends(get_session)):
        return [views.region_ref(r) | {"priority": r.priority} for r in views.public_regions(session)]

    @app.get("/api/v1/regions/{code}/summary", tags=["summaries"])
    def region_summary(code: str, session: Session = Depends(get_session)):
        """Official counts, estimated burden, recent incidence, completeness, R_t, forecasts, severity and surveillance quality."""
        return views.region_summary(session, region_or_404(session, code), detail=True)

    @app.get("/api/v1/regions/{code}/official-series", tags=["series"])
    def official_series(code: str, metric: str = Query("cases"), case_class: str = Query("confirmed"), session: Session = Depends(get_session)):
        if metric not in METRICS or case_class not in CLASSES:
            raise HTTPException(422, "unsupported metric or case class")
        return views.official_series(session, region_or_404(session, code), metric, case_class)

    @app.get("/api/v1/regions/{code}/subnational", tags=["series"])
    def subnational(code: str, session: Session = Depends(get_session)):
        """First-level administrative breakdown with small-area and complementary suppression applied."""
        r = region_or_404(session, code)
        if r.level != 0:
            raise HTTPException(422, "subnational tables are available for countries")
        return {"region": views.region_ref(r), "cells": views.subnational(session, r),
                "note": "Finer resolutions are not published. Suppressed cells are shown as '<k' or 'suppressed'."}

    @app.get("/api/v1/regions/{code}/estimates", tags=["models"])
    def estimates(code: str, session: Session = Depends(get_session)):
        s = views.region_summary(session, region_or_404(session, code), detail=True)
        return {k: s.get(k) for k in ("region", "data_as_of", "latest_update", "model_version", "estimated_total", "recent_incidence",
                                      "ascertainment", "rt", "nowcast_reported", "model_disagreement", "burden_methods", "parameters")}

    @app.get("/api/v1/regions/{code}/forecasts", tags=["models"])
    def forecasts(code: str, session: Session = Depends(get_session)):
        s = views.region_summary(session, region_or_404(session, code), detail=True)
        return {"region": s["region"], "model_version": s["model_version"], "forecasts": s.get("forecasts"), "expansion": s.get("expansion")}

    @app.get("/api/v1/regions/{code}/forecast-comparison", tags=["models"])
    def forecast_comparison(code: str, session: Session = Depends(get_session)):
        """Previous forecasts compared with subsequently reported observations."""
        return views.forecast_comparison(session, region_or_404(session, code))

    @app.get("/api/v1/regions/{code}/evidence", tags=["evidence"])
    def evidence(code: str, session: Session = Depends(get_session)):
        return views.evidence(session, region_or_404(session, code))

    @app.get("/api/v1/regions/{code}/transport", tags=["evidence"])
    def transport(code: str, session: Session = Depends(get_session)):
        return views.transport_context(session, region_or_404(session, code))

    @app.get("/api/v1/map/geometry/{level}", tags=["summaries"])
    def map_geometry(level: int, response: Response, session: Session = Depends(get_session)):
        """Simplified boundaries: level 0 (countries) or 1 (first-level units of priority countries)."""
        if level not in (0, 1):
            raise HTTPException(404)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return views.map_geometry(session, level)

    @app.get("/api/v1/map/layers", tags=["summaries"])
    def map_layers(session: Session = Depends(get_session)):
        return views.map_layers(session)

    @app.get("/api/v1/severity", tags=["summaries"])
    def severity(session: Session = Depends(get_session)):
        return views.overview(session)["map"]

    @app.get("/api/v1/surveillance-quality", tags=["summaries"])
    def surveillance(session: Session = Depends(get_session)):
        return [{"region": s["region"], "surveillance": s.get("surveillance"), "confidence": s["severity"].get("confidence")}
                for s in views.overview(session)["regions"]]

    @app.get("/api/v1/transport", tags=["evidence"])
    def transport_all(session: Session = Depends(get_session)):
        return views.transport_context(session)

    @app.get("/api/v1/signals", tags=["evidence"])
    def signals(session: Session = Depends(get_session)):
        """Aggregated, paraphrased unofficial signals. No posts, accounts or precise locations."""
        return views.signals_public(session)

    @app.get("/api/v1/alerts", tags=["summaries"])
    def alerts(session: Session = Depends(get_session)):
        return views.alerts_public(session)

    @app.get("/api/v1/sources", tags=["evidence"])
    def sources(session: Session = Depends(get_session)):
        return views.sources_status(session)

    @app.get("/api/v1/evaluation", tags=["models"])
    def evaluation(session: Session = Depends(get_session)):
        return views.evaluation(session)

    @app.get("/api/v1/reports", tags=["reports"])
    def reports(session: Session = Depends(get_session)):
        q = select(SituationReport).where(SituationReport.status.in_(("published", "retracted"))).order_by(SituationReport.generated_at.desc()).limit(50)
        return [{"id": r.id, "kind": r.kind, "title": r.title, "generated_at": r.generated_at.isoformat(), "data_as_of": r.data_as_of and r.data_as_of.isoformat(),
                 "scope": r.scope, "status": r.status, "is_synthetic": r.is_synthetic} for r in session.scalars(q)]

    @app.get("/api/v1/reports/{rid}", tags=["reports"])
    def report(rid: int, format: str = Query("json", pattern="^(json|markdown)$"), session: Session = Depends(get_session)):
        r = session.get(SituationReport, rid)
        if r is None or r.status not in ("published", "retracted"):
            raise HTTPException(404, "report not found")
        if format == "markdown":
            body = r.content_md if r.status == "published" else f"# Retracted\n\n{r.retraction_note}"
            return PlainTextResponse(body, media_type="text/markdown")
        return {"id": r.id, "kind": r.kind, "title": r.title, "generated_at": r.generated_at.isoformat(), "status": r.status,
                "retraction_note": r.retraction_note, "markdown": r.content_md if r.status == "published" else None,
                "is_synthetic": r.is_synthetic}

    @app.get("/api/v1/export/{dataset}.csv", tags=["series"])
    def export(dataset: str, request: Request, session: Session = Depends(get_session)):
        """Aggregated CSV exports (country and first-level units only), rate-limited."""
        if not export_limiter.allow(client_id(request)):
            raise HTTPException(429, "export rate limit exceeded")
        buf = io.StringIO()
        w = csv.writer(buf)
        if dataset == "summaries":
            w.writerow(["region_code", "region_name", "level", "data_as_of", "official_confirmed_cases", "official_confirmed_deaths",
                        "estimated_total_lower_90", "estimated_total_median", "estimated_total_upper_90", "estimate_confidence",
                        "severity", "severity_confidence", "model_version", "synthetic"])
            for s in views.overview(session)["regions"]:
                oc, od, et = s["official"]["confirmed_cases"], s["official"]["confirmed_deaths"], s.get("estimated_total") or {}
                w.writerow([s["region"]["code"], s["region"]["name"], s["region"]["level"], s.get("data_as_of"),
                            oc and oc["value"], od and od["value"], et.get("lower_90"), et.get("median"), et.get("upper_90"),
                            et.get("confidence") or ("insufficient" if et.get("insufficient") else None),
                            s["severity"]["label"], s["severity"].get("confidence"), s["model_version"], s["is_synthetic"]])
        elif dataset == "subnational":
            w.writerow(["country", "region_code", "region_name", "value", "display", "suppressed"])
            for c in session.scalars(select(Region).where(Region.level == 0, Region.priority.is_(True))):
                for cell in views.subnational(session, c):
                    w.writerow([c.code, cell["region_code"], cell["region_name"], cell["value"], cell["display"], cell["suppressed"]])
        else:
            raise HTTPException(404, "unknown dataset")
        audit(session, f"client:{client_id(request)[:8]}", "export", "dataset", dataset)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")

    @app.post("/api/v1/query", tags=["public-input"])
    def query(body: QueryIn, session: Session = Depends(get_session)):
        """Scope-guarded questions about the data. Clinical, identity, tracking and operational requests are refused."""
        return answer(session, sanitize(body.question).text)

    @app.post("/api/v1/error-reports", tags=["public-input"], status_code=201)
    def error_report(body: ErrorReportIn, session: Session = Depends(get_session)):
        """Report an error or request a correction. Do not include personal or patient information."""
        from ..privacy.redaction import redact

        text, _ = redact(sanitize(body.description).text)
        er = ErrorReport(organisation=sanitize(body.organisation or "").text or None, target_type=body.target_type,
                         target_ref=sanitize(body.target_ref or "").text or None, description=text)
        session.add(er)
        session.flush()
        enqueue(session, "correction", er.id, f"public error report on {body.target_type}", priority=2)
        return {"id": er.id, "status": "received", "message": "Thank you. Reports are reviewed by people; personal details were removed."}

    # ---- admin ----------------------------------------------------------
    @app.get("/api/v1/admin/review-queue", tags=["admin"])
    def review_queue(status: str = "pending", session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        q = select(ReviewItem).where(ReviewItem.status == status).order_by(ReviewItem.priority, ReviewItem.created_at).limit(200)
        return [{"id": i.id, "item_type": i.item_type, "item_id": i.item_id, "reason": i.reason, "priority": i.priority,
                 "created_at": i.created_at.isoformat(), "status": i.status} for i in session.scalars(q)]

    @app.get("/api/v1/admin/review-queue/{rid}", tags=["admin"])
    def review_item(rid: int, session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        from .admin_views import review_detail

        item = session.get(ReviewItem, rid)
        if item is None:
            raise HTTPException(404)
        return review_detail(session, item)

    @app.post("/api/v1/admin/review-queue/{rid}/decision", tags=["admin"])
    def review_decision(rid: int, body: DecisionIn, session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        try:
            item = decide(session, rid, body.decision, f"key:{key.id}:{key.name}", body.note)
        except ReviewError as e:
            raise HTTPException(409, str(e)) from e
        return {"id": item.id, "status": item.status}

    @app.post("/api/v1/admin/signals/{sid}/translate", tags=["admin"])
    def translate_signal(sid: int, session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        """Machine translation of a signal's redacted text for a reviewer (disabled unless configured)."""
        from ..db.models import Document, Signal
        from ..nlp.translation import get_translator

        sig = session.get(Signal, sid)
        doc = session.get(Document, sig.document_id) if sig else None
        if doc is None or not doc.text_minimized:
            raise HTTPException(404, "signal text not available (not found or past retention)")
        res = get_translator().translate(doc.text_minimized)
        audit(session, f"key:{key.id}:{key.name}", "translate_signal", "signal", sid, {"status": res.quality})
        return res.__dict__

    @app.post("/api/v1/admin/retractions", tags=["admin"])
    def retraction(body: RetractIn, session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        try:
            c = retract(session, body.target_type, body.target_id, sanitize(body.public_note).text, f"key:{key.id}:{key.name}", body.error_report_id)
        except ReviewError as e:
            raise HTTPException(404, str(e)) from e
        return {"correction_id": c.id}

    @app.post("/api/v1/admin/transport/{edge_key}/status", tags=["admin"])
    def transport_status(edge_key: str, body: TransportStatusIn, session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        try:
            e = set_transport_status(session, edge_key, body.service_status, sanitize(body.evidence).text, f"key:{key.id}:{key.name}")
        except ReviewError as ex:
            raise HTTPException(404, str(ex)) from ex
        return {"key": e.key, "service_status": e.service_status}

    @app.post("/api/v1/admin/pipeline/run", tags=["admin"])
    def pipeline_run(skip_ingest: bool = False, session: Session = Depends(get_session), key=Depends(require_role(Role.ADMIN))):
        from ..pipeline.run import run_all

        audit(session, f"key:{key.id}:{key.name}", "pipeline_run", details={"note": "manual trigger"})
        session.commit()
        return run_all(skip_ingest=skip_ingest)

    @app.get("/api/v1/admin/alerts", tags=["admin"])
    def admin_alerts(session: Session = Depends(get_session), key=Depends(require_role(Role.REVIEWER))):
        q = select(Alert).order_by(Alert.created_at.desc()).limit(100)
        return [{"id": a.id, "kind": a.kind, "message": a.message, "review_status": a.review_status, "published": a.published,
                 "relies_on_unofficial": a.relies_on_unofficial, "evidence": a.evidence} for a in session.scalars(q)]

    @app.get("/api/v1/admin/audit-log", tags=["admin"])
    def audit_log(session: Session = Depends(get_session), key=Depends(require_role(Role.ADMIN))):
        q = select(AuditLog).order_by(AuditLog.at.desc()).limit(500)
        return [{"at": a.at.isoformat(), "actor": a.actor, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
                 "details": a.details} for a in session.scalars(q)]

    # ---- dashboard --------------------------------------------------------
    dist = Path(settings.frontend_dist)
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return {"message": "Ebola Watch API. Dashboard not built: run `npm run build` in frontend/.", "docs": "/api/docs"}

    return app
