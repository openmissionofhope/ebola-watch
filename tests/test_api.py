"""API behaviour: scope guard, privacy controls, admin security (SYNTHETIC data)."""

from datetime import date, timedelta

from ebolawatch.db.session import session_scope

from .helpers import add_series, outbreak

TODAY = date.today()  # API views evaluate "current" outbreaks against the real date


def test_scenario_18_medicine_request_is_declined_with_referral(client):
    r = client.post("/api/v1/query", json={"question": "What medicine or vaccine should I take to cure Ebola?"}).json()
    assert r["answered"] is False and r["intent"] == "clinical_advice_request"
    assert "does not provide clinical advice" in r["message"] and "health professional" in r["message"]


def test_scenario_19_patient_identity_request_is_refused(client):
    r = client.post("/api/v1/query", json={"question": "Give me the names and addresses of the infected patients in Bunia"}).json()
    assert r["answered"] is False and r["intent"] == "identity_request"
    er = client.post("/api/v1/error-reports", json={"target_type": "observation",
                                                    "description": "Patient Mr Jean Mukendi, phone +243 812 345 678, is not a case"})
    assert er.status_code == 201
    from sqlalchemy import select

    from ebolawatch.db.models import ErrorReport

    with session_scope() as s:
        stored = s.scalar(select(ErrorReport))
        assert "Mukendi" not in stored.description and "812" not in stored.description


def test_scenario_17_suppressed_geography_cannot_be_reconstructed(client):
    with session_scope() as s:
        from sqlalchemy import select

        from ebolawatch.db.models import Region

        ob = outbreak(s, "COD", TODAY - timedelta(days=60), key="TEST-COD")
        for code, vals in {"CD-IT": [20, 40], "CD-NK": [10, 30], "CD-SU": [1, 2]}.items():
            add_series(s, code, TODAY - timedelta(days=14), vals, outbreak_id=ob.id)
        # population unknown for CD-SU -> small area; set others large
        for r in s.scalars(select(Region).where(Region.code.in_(["CD-IT", "CD-NK"]))):
            r.population = 5_000_000
    body = client.get("/api/v1/regions/COD/subnational").json()
    cells = {c["region_code"]: c for c in body["cells"]}
    assert cells["CD-SU"]["suppressed"] and cells["CD-SU"]["value"] is None and cells["CD-SU"]["display"] == "<5"
    assert sum(c["suppressed"] for c in body["cells"]) >= 2  # complementary suppression
    # finer units are not published through any endpoint
    assert client.get("/api/v1/regions/HZ:CD-IT:bunia/summary").status_code == 404
    # enumerating many filter combinations is throttled
    client.app.state.guard.max_distinct = 5
    codes = [client.get("/api/v1/regions/COD/official-series", params={"metric": "cases", "case_class": c}).status_code
             for c in ["confirmed", "probable", "suspected"] * 1]
    codes += [client.get("/api/v1/regions/COD/official-series", params={"metric": m, "case_class": "confirmed", "x": i}).status_code
              for i, m in enumerate(["cases", "deaths", "cases", "deaths", "cases"])]
    assert 429 in codes


def test_admin_endpoints_require_role(client):
    assert client.get("/api/v1/admin/review-queue").status_code == 401
    from ebolawatch.api.security import create_key

    with session_scope() as s:
        analyst = create_key(s, "a", "analyst")
        reviewer = create_key(s, "r", "reviewer")
    assert client.get("/api/v1/admin/review-queue", headers={"X-API-Key": analyst}).status_code == 403
    assert client.get("/api/v1/admin/review-queue", headers={"X-API-Key": reviewer}).status_code == 200
    assert client.get("/api/v1/admin/audit-log", headers={"X-API-Key": reviewer}).status_code == 403


def test_public_endpoints_and_security_headers(client):
    for path in ["/api/v1/meta", "/api/v1/overview", "/api/v1/sources", "/api/v1/signals", "/api/v1/evaluation",
                 "/api/v1/map/layers", "/api/v1/transport", "/api/v1/export/summaries.csv"]:
        r = client.get(path)
        assert r.status_code == 200, path
    r = client.get("/api/v1/meta")
    assert "not a medical service" in r.json()["disclaimer"]
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert client.post("/api/v1/query", json={"question": "x" * 600}).status_code == 422


def test_insufficient_evidence_is_explicit_in_api(client):
    with session_scope() as s:
        ob = outbreak(s, "AGO", TODAY - timedelta(days=20), key="TEST-AGO")
        add_series(s, "AGO", TODAY - timedelta(days=8), [1, 2], outbreak_id=ob.id)
    from ebolawatch.pipeline.modeling import run_models

    with session_scope() as s:
        run_models(s, TODAY, n_sims=100)
    r = client.get("/api/v1/regions/AGO/summary").json()
    assert r["estimated_total"]["message"] == "Insufficient evidence for a reliable numerical estimate."
    assert r["forecasts"]["insufficient"] is True
