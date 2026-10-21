"""Serverless deployment: static export, GitHub-issue review, scheduling (SYNTHETIC data)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from ebolawatch.config import Settings
from ebolawatch.db.models import Alert, AuditLog, ConnectorRun, Document, ReviewItem, Signal, SignalCluster
from ebolawatch.db.session import session_scope
from ebolawatch.domain.enums import SourceCategory
from ebolawatch.nlp.gazetteer import admin1_code
from ebolawatch.publish import github_ops
from ebolawatch.publish.github_ops import apply_from_github, fence, parse_form, sync_to_github
from ebolawatch.publish.static import ExportError, export_static
from ebolawatch.review.queue import enqueue

from .helpers import add_series, outbreak, region, source

TODAY = date.today()  # public views evaluate "current" outbreaks against the real date
STATIC_INDEX = '<!doctype html><html><head><meta charset="UTF-8" />\n<meta name="ebolawatch-build" content="static" /></head><body></body></html>'


# ---------------------------------------------------------------- static export

@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(STATIC_INDEX)
    (d / "assets" / "app.js").write_text("console.log('x')")
    return d


@pytest.fixture()
def few_regions(monkeypatch):
    """Export a handful of areas instead of every country (speed)."""
    from ebolawatch import views

    original = views.public_regions
    monkeypatch.setattr(views, "public_regions", lambda s: [r for r in original(s) if r.code in ("COD", "CD-IT", "CD-SU", "KEN")])


def test_static_export_matches_public_api_and_publishes_nothing_else(db, client, dist, tmp_path, few_regions):
    with session_scope() as s:
        ob = outbreak(s, "COD", TODAY - timedelta(days=70), key="TEST-COD")
        add_series(s, "COD", TODAY - timedelta(days=63), [10, 25, 50, 90, 140, 200, 260, 330, 400, 470], outbreak_id=ob.id)
        add_series(s, "CD-IT", TODAY - timedelta(days=14), [20, 40], outbreak_id=ob.id)
        add_series(s, "CD-SU", TODAY - timedelta(days=14), [1, 2], outbreak_id=ob.id)
        region(s, "CD-IT").population = 5_000_000
        src = source(s, "test_news", SourceCategory.NEWS)
        s.add(Document(source_id=src.id, external_id="n1", title="SYNTHETIC rumour headline", content_hash="h1",
                       text_minimized="SYNTHETIC raw post text that must stay private", is_synthetic=True))
    out = tmp_path / "site"
    result = export_static(out, dist, cname="ebolawatch.example.org")
    assert result["regions"] == 4

    data = out / "data"
    meta = json.loads((data / "meta.json").read_text())
    assert meta["static"] is True and meta["snapshot_generated_at"]
    for path in ("overview", "regions/COD/summary", "regions/COD/official-series", "map/layers", "signals"):
        exported = json.loads((data / f"{path}.json").read_text())
        live = client.get(f"/api/v1/{path}").json()
        if path == "overview":
            exported.pop("generated_at"), live.pop("generated_at")
        assert exported == live, path
    sub = json.loads((data / "regions/COD/subnational.json").read_text())
    assert {c["region_code"]: c["display"] for c in sub["cells"]}["CD-SU"] == "<5"
    assert not (data / "regions/CD-IT/subnational.json").exists()  # countries only

    files = [p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()]
    assert not any("admin" in f for f in files)
    blob = "\n".join(p.read_text(errors="ignore") for p in data.rglob("*") if p.is_file())
    assert "must stay private" not in blob and "rumour headline" not in blob
    assert (out / "region/COD/index.html").read_text() == STATIC_INDEX
    assert (out / "languages/index.html").exists()
    assert (out / "404.html").exists() and (out / ".nojekyll").exists() and (out / "assets/app.js").exists()
    assert (out / "CNAME").read_text().strip() == "ebolawatch.example.org"

    export_static(out, dist)  # a previous export is replaced
    assert not (out / "CNAME").exists()


def test_static_export_is_not_throttled_by_the_query_guard(db, dist, tmp_path, few_regions, monkeypatch):
    from ebolawatch.config import get_settings, reset_settings_cache
    from ebolawatch.reports.generate import generate

    with session_scope() as s:
        for days in range(4):  # each report is fetched with ?format=markdown: one distinct filter combination per report
            generate(s, "daily", today=TODAY - timedelta(days=days))
    monkeypatch.setenv("EW_QUERY_GUARD_MAX_DISTINCT_FILTERS", "2")
    reset_settings_cache()
    assert get_settings().query_guard_max_distinct_filters == 2
    result = export_static(tmp_path / "site", dist)
    assert result["reports"] >= 4


def test_static_export_refuses_unsafe_inputs(db, dist, tmp_path):
    server_build = tmp_path / "server-dist"
    server_build.mkdir()
    (server_build / "index.html").write_text("<html><head></head></html>")
    with pytest.raises(ExportError, match="not a static build"):
        export_static(tmp_path / "a", server_build)
    other = tmp_path / "project"
    other.mkdir()
    (other / "README.md").write_text("not a site")
    with pytest.raises(ExportError, match="refusing to overwrite"):
        export_static(other, dist)
    assert (other / "README.md").exists()


# ---------------------------------------------------------------- GitHub review

class FakeGitHub:
    """In-memory stand-in for :class:`github_ops.GitHub`."""

    def __init__(self):
        self.issues_by_no: dict[int, dict] = {}
        self.comments_by_issue: dict[int, list[dict]] = {}
        self.label_events: dict[tuple[int, str], str] = {}
        self._next = 1

    def issues(self, label):
        return [json.loads(json.dumps(i)) for i in self.issues_by_no.values() if label in {lb["name"] for lb in i["labels"]}]

    def label_actor(self, number, label):
        return self.label_events.get((number, label))

    def comments(self, number):
        return list(self.comments_by_issue.get(number, []))

    def create_issue(self, title, body, labels):
        n = self._next
        self._next += 1
        self.issues_by_no[n] = {"number": n, "title": title, "body": body, "state": "open", "labels": [{"name": x} for x in labels]}
        return self.issues_by_no[n]

    def comment(self, number, body, created_at=None):
        c = {"id": number * 1000 + len(self.comments_by_issue.get(number, [])), "body": body,
             "created_at": (created_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")}
        self.comments_by_issue.setdefault(number, []).append(c)
        return c

    def delete_comment(self, comment_id):
        for cs in self.comments_by_issue.values():
            cs[:] = [c for c in cs if c["id"] != comment_id]

    def update_issue(self, number, **fields):
        issue = self.issues_by_no[number]
        if "labels" in fields:
            issue["labels"] = [{"name": x} for x in fields.pop("labels")]
        issue.update(fields)
        return issue

    def ensure_labels(self):
        pass

    # reviewer actions
    def add_label(self, number, label, actor):
        self.issues_by_no[number]["labels"].append({"name": label})
        self.label_events[(number, label)] = actor


HOSTILE_TITLE = "SYNTHETIC @someone ``` </code><img src=x onerror=alert(1)> [click](http://evil.invalid) #1"


def _alert_with_cluster(s):
    src = source(s, "test_news", SourceCategory.NEWS)
    doc = Document(source_id=src.id, external_id="n1", url="https://news.example.invalid/a?b=1", title=HOSTILE_TITLE,
                   content_hash="h1", text_minimized="SYNTHETIC body", published_at=datetime.now(UTC), is_synthetic=True)
    s.add(doc)
    s.flush()
    cl = SignalCluster(region_id=region(s, "COD").id, claim_type="case_report", summary="SYNTHETIC cluster", corroboration="none",
                       assessment="Possible emerging signal requiring verification.", is_synthetic=True)
    s.add(cl)
    s.flush()
    s.add(Signal(document_id=doc.id, cluster_id=cl.id, origin_group="g1", claim_type="case_report", report_kind="firsthand",
                 relevance="likely", languages=["en"], is_synthetic=True))
    alert = Alert(region_id=region(s, "COD").id, kind="unofficial_signal", message="Possible emerging signal requiring verification.",
                  confidence="low", evidence={"cluster_id": cl.id, "summary": "SYNTHETIC"}, relies_on_unofficial=True,
                  dedupe_key="test-alert", is_synthetic=True)
    s.add(alert)
    s.flush()
    return alert, enqueue(s, "alert", alert.id, "alert relies on unofficial reports", priority=1)


def test_review_through_github_issues_publishes_only_after_approval(db):
    gh = FakeGitHub()
    with session_scope() as s:
        alert, item = _alert_with_cluster(s)
        alert_id, item_id = alert.id, item.id
        old = add_series(s, "COD", date(2000, 1, 1), [3], status="pending_review")[0]
        enqueue(s, "observation", old.id, "historical extraction", priority=2)  # not sent to GitHub
    with session_scope() as s:
        res = sync_to_github(s, gh)
    assert res["created"] == 1
    issue = gh.issues_by_no[1]
    assert f"<!-- ew-review:{item_id} -->" in issue["body"] and HOSTILE_TITLE not in issue["body"]
    excerpt = gh.comments_by_issue[1][0]["body"]
    # untrusted text appears only inside a fence that it cannot close
    fenced = fence(HOSTILE_TITLE + "\n\nSYNTHETIC body")
    assert fenced in excerpt and excerpt.count(HOSTILE_TITLE) == 1
    assert "<https://news.example.invalid/a?b=1>" in excerpt
    assert {"has-excerpts", "ew-review", "review:alert"} <= {lb["name"] for lb in issue["labels"]}

    with session_scope() as s:  # nothing decided yet: nothing applied, no duplicate issue
        assert apply_from_github(s, gh)["decisions"] == []
        assert sync_to_github(s, gh)["created"] == 0
        assert not s.get(Alert, alert_id).published

    gh.add_label(1, "approve", "alice")
    with session_scope() as s:
        res = apply_from_github(s, gh)
        assert res["decisions"] == [{"issue": 1, "review_item": item_id, "decision": "approved"}]
        assert s.get(Alert, alert_id).published
        assert s.scalar(select(AuditLog).where(AuditLog.action == "review_decision")).actor == "github:alice"
    with session_scope() as s:
        sync_to_github(s, gh)
    assert gh.issues_by_no[1]["state"] == "closed" and "approved" in gh.comments_by_issue[1][-1]["body"]


def test_conflicting_labels_apply_nothing(db):
    gh = FakeGitHub()
    with session_scope() as s:
        alert, _ = _alert_with_cluster(s)
        alert_id = alert.id
        sync_to_github(s, gh)
    gh.add_label(1, "approve", "alice")
    gh.add_label(1, "reject", "bob")
    with session_scope() as s:
        assert apply_from_github(s, gh)["decisions"] == []
        sync_to_github(s, gh)
        assert not s.get(Alert, alert_id).published
    assert "conflict" in {lb["name"] for lb in gh.issues_by_no[1]["labels"]} and gh.issues_by_no[1]["state"] == "open"


def test_retraction_request_needs_apply_label_and_reports_failures(db):
    gh = FakeGitHub()
    with session_scope() as s:
        alert, item = _alert_with_cluster(s)
        alert.published, alert_id = True, alert.id
        item.status = "approved"
    form = "### Target type\n\nalert\n\n### Target ID\n\n{id}\n\n### Public note\n\nSYNTHETIC: the source was a satire site."
    good = gh.create_issue("[Retraction]", form.format(id=alert_id), ["ew-action", "retraction"])
    bad = gh.create_issue("[Retraction]", form.format(id="abc"), ["ew-action", "retraction"])
    with session_scope() as s:
        assert apply_from_github(s, gh)["actions"] == []  # not authorised yet
    gh.add_label(good["number"], "apply", "carol")
    gh.add_label(bad["number"], "apply", "carol")
    with session_scope() as s:
        statuses = {a["issue"]: a["status"] for a in apply_from_github(s, gh)["actions"]}
        assert statuses == {good["number"]: "applied", bad["number"]: "failed"}
        assert s.get(Alert, alert_id).retracted and not s.get(Alert, alert_id).published
    with session_scope() as s:
        sync_to_github(s, gh)
        assert apply_from_github(s, gh)["actions"] == []  # applied once only
    assert gh.issues_by_no[good["number"]]["state"] == "closed"
    bad_labels = {lb["name"] for lb in gh.issues_by_no[bad["number"]]["labels"]}
    assert "apply-failed" in bad_labels and "apply" not in bad_labels
    assert "Target ID must be a number" in gh.comments_by_issue[bad["number"]][-1]["body"]


def test_source_excerpts_are_deleted_after_retention(db):
    gh = FakeGitHub()
    with session_scope() as s:
        _alert_with_cluster(s)
        sync_to_github(s, gh)
    gh.comments_by_issue[1][0]["created_at"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    with session_scope() as s:
        assert sync_to_github(s, gh)["excerpt_comments_deleted"] == 1
    assert gh.comments_by_issue[1] == [] and "has-excerpts" not in {lb["name"] for lb in gh.issues_by_no[1]["labels"]}


def test_markdown_helpers_neutralise_untrusted_text():
    nasty = "a ```` b"
    assert fence(nasty).startswith("`````text\n")
    assert github_ops.plain("@team [x](y)") == "@​team \\[x\\]\\(y\\)"
    assert github_ops.link("javascript:alert(1)") == "(no link)" and github_ops.link("https://ok.example/a(b)") == "(no link)"
    assert parse_form("### Edge key\n\nlake-1\n\n### Evidence\n\n_No response_\n") == {"edge key": "lake-1", "evidence": None}


# ---------------------------------------------------------------- scheduling, configuration, codes

def test_due_only_skips_reference_data_and_backs_off_failing_sources(db):
    from ebolawatch.pipeline.ingest import is_due
    from ebolawatch.sources.reference import WorldBankPopulationConnector
    from ebolawatch.sources.who_don import WhoDonConnector

    now = datetime.now(UTC)
    with session_scope() as s:
        wb, don = WorldBankPopulationConnector(), WhoDonConnector()
        assert is_due(s, wb, now)
        s.add(ConnectorRun(source_key=wb.info.key, status="ok", started_at=now - timedelta(days=2)))
        for h in (3, 2, 1):
            s.add(ConnectorRun(source_key=don.info.key, status="unavailable", started_at=now - timedelta(hours=h)))
        s.flush()
        assert not is_due(s, wb, now) and is_due(s, wb, now + timedelta(days=31))
        assert not is_due(s, don, now) and is_due(s, don, now + timedelta(hours=24))


def test_registry_entry_adopts_an_auto_registered_outbreak(db, tmp_path):
    from ebolawatch.config import get_settings
    from ebolawatch.db.models import Outbreak
    from ebolawatch.pipeline.seed import seed_outbreaks

    with session_scope() as s:
        auto = Outbreak(key="AUTO-TZA-BDBV-20310301", name="auto", pathogen="BDBV", primary_iso3="TZA", declared_on=date(2031, 3, 1))
        s.add(auto)
        s.flush()
        review = enqueue(s, "outbreak", auto.id, "outbreak auto-registered from official bulletin; verify dates and pathogen")
        auto_id, review_id = auto.id, review.id
    (tmp_path / "outbreaks.yaml").write_text(
        "outbreaks:\n  - {key: TZA-BDBV-2031, name: SYNTHETIC, pathogen: BDBV, iso3: TZA, declared_on: 2031-02-27,"
        " replaces: AUTO-TZA-BDBV-20310301, citation: SYNTHETIC declaration}\n")
    with session_scope() as s:
        seed_outbreaks(s, get_settings().model_copy(update={"data_dir": tmp_path}))
    with session_scope() as s:
        ob = s.get(Outbreak, auto_id)
        assert ob.key == "TZA-BDBV-2031" and ob.declared_on == date(2031, 2, 27) and ob.notes == "SYNTHETIC declaration"
        item = s.get(ReviewItem, review_id)
        assert item.status == "approved" and item.resolved_by == "registry"


def test_static_deployment_may_use_sqlite_in_production():
    secrets = {"secret_key": "k" * 40, "pseudonym_salt": "s" * 40, "database_url": "sqlite:///x.db", "env": "production"}
    Settings(**secrets, deployment="static").validate_for_production()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Settings(**secrets, deployment="server").validate_for_production()
    with pytest.raises(RuntimeError, match="EW_SECRET_KEY"):
        Settings(**(secrets | {"secret_key": "short"}), deployment="static").validate_for_production()


def test_admin1_codes_are_url_safe_and_unique():
    assert admin1_code({"iso3": "CAF", "name": "Ouham-Pendé", "iso_3166_2": "CF=OP"}) == "CF-OP"
    assert admin1_code({"iso3": "SDN", "name": "Abyei PCA", "iso_3166_2": "N/A"}) == "SDN-ABYEI-PCA"
    assert admin1_code({"iso3": "CAF", "name": "Sangha-Mbaéré", "iso_3166_2": "CF-HS"}) == "CF-SE"


def test_seeded_region_codes_are_valid(db):
    import re

    with session_scope() as s:
        from ebolawatch.db.models import Region

        codes = [r.code for r in s.scalars(select(Region).where(Region.level <= 1))]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"[A-Z0-9-]+", c) for c in codes)
    assert {"CF-OP", "CF-SE", "CF-HS", "SDN-ABYEI-PCA"} <= set(codes)


def test_review_items_are_sent_only_once_per_item(db):
    gh = FakeGitHub()
    with session_scope() as s:
        _alert_with_cluster(s)
        assert sync_to_github(s, gh, max_new=1)["created"] == 1
        assert sync_to_github(s, gh)["created"] == 0
        assert len(list(s.scalars(select(ReviewItem)))) == 1
