"""Human review through GitHub issues, for deployments without a server.

A private operations repository holds the review queue as issues. Each pipeline
run first applies the decisions reviewers recorded with labels
(:func:`apply_from_github`), and then, after the new state has been saved, closes
decided issues and opens issues for new review items (:func:`sync_to_github`).
Doing GitHub writes last keeps the two sides consistent when a run fails part-way:
a decision is only acknowledged once the database that contains it is saved.

Labels:
  ew-review       one issue per review item
  approve/reject  the decision; whoever adds the label is recorded as the reviewer
  ew-action       a retraction or transport-status request (issue forms)
  apply           authorises an ew-action issue
  has-excerpts    the issue has a comment with source excerpts (deleted after the
                  raw-content retention period)

Text taken from sources is untrusted: it is only ever placed inside fenced code
blocks, so GitHub renders no mentions, links, images or HTML from it.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.base import utcnow
from ..db.models import (
    Alert,
    AuditLog,
    Document,
    ErrorReport,
    Observation,
    Outbreak,
    Region,
    ReviewItem,
    Signal,
    SignalCluster,
)
from ..domain.enums import ReviewStatus
from ..review.queue import ReviewError, audit, decide, retract, set_transport_status

API = "https://api.github.com"
LABEL_REVIEW, LABEL_ACTION, LABEL_APPLY, LABEL_EXCERPTS = "ew-review", "ew-action", "apply", "has-excerpts"
DECISIONS = {"approve": ReviewStatus.APPROVED.value, "reject": ReviewStatus.REJECTED.value}
LABELS = {
    LABEL_REVIEW: ("5319e7", "Ebola Watch review item"),
    "approve": ("0e8a16", "Reviewer decision: approve"),
    "reject": ("b60205", "Reviewer decision: reject"),
    LABEL_ACTION: ("1d76db", "Retraction or transport-status request"),
    LABEL_APPLY: ("0e8a16", "Authorise this request"),
    "apply-failed": ("d93f0b", "The request could not be applied"),
    "retraction": ("c5def5", "Retraction request"),
    "transport-status": ("c5def5", "Transport service status change"),
    LABEL_EXCERPTS: ("fbca04", "Has a source-excerpt comment (deleted after the retention period)"),
    "conflict": ("d93f0b", "Both approve and reject were added"),
    **{f"review:{t}": ("ededed", f"Review item type: {t}") for t in ("alert", "cluster", "observation", "outbreak", "correction")},
}
MAX_EXCERPT_DOCS = 15
EXCERPT_CHARS = 600


class GitHubError(RuntimeError):
    pass


class GitHub:
    """Minimal GitHub REST client for one repository."""

    def __init__(self, repo: str, token: str, http: httpx.Client | None = None, pause_s: float = 1.0):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise GitHubError(f"invalid repository name {repo!r}")
        self.repo, self.pause_s = repo, pause_s
        self.http = http or httpx.Client(base_url=API, timeout=30, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ebolawatch-ops"})

    @classmethod
    def from_env(cls, repo: str) -> GitHub:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise GitHubError("set GITHUB_TOKEN (or GH_TOKEN) to a token with issues: write on the operations repository")
        return cls(repo, token)

    def _call(self, method: str, path: str, write: bool = False, **kw):
        if write and self.pause_s:
            time.sleep(self.pause_s)  # stay under GitHub's secondary rate limits for content creation
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise GitHubError(f"{method} {path}: HTTP {r.status_code}")
        return r.json() if r.content else None

    def _pages(self, path: str, params: dict | None = None) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._call("GET", path, params={**(params or {}), "per_page": 100, "page": page})
            out.extend(batch)
            if len(batch) < 100:
                return out
            page += 1

    def issues(self, label: str) -> list[dict]:
        return [i for i in self._pages(f"/repos/{self.repo}/issues", {"labels": label, "state": "all"}) if "pull_request" not in i]

    def label_actor(self, number: int, label: str) -> str | None:
        actor = None
        for e in self._pages(f"/repos/{self.repo}/issues/{number}/events"):
            if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label:
                actor = (e.get("actor") or {}).get("login")
        return actor

    def comments(self, number: int) -> list[dict]:
        return self._pages(f"/repos/{self.repo}/issues/{number}/comments")

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        return self._call("POST", f"/repos/{self.repo}/issues", write=True, json={"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> dict:
        return self._call("POST", f"/repos/{self.repo}/issues/{number}/comments", write=True, json={"body": body})

    def delete_comment(self, comment_id: int) -> None:
        self._call("DELETE", f"/repos/{self.repo}/issues/comments/{comment_id}")

    def update_issue(self, number: int, **fields) -> dict:
        return self._call("PATCH", f"/repos/{self.repo}/issues/{number}", json=fields)

    def ensure_labels(self) -> None:
        have = {lb["name"] for lb in self._pages(f"/repos/{self.repo}/labels")}
        for name, (color, desc) in LABELS.items():
            if name not in have:
                self._call("POST", f"/repos/{self.repo}/labels", write=True, json={"name": name, "color": color, "description": desc})


# ---------------------------------------------------------------- rendering

def fence(text: str) -> str:
    """A fenced code block that the text cannot close (untrusted text renders inert)."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    f = "`" * max(3, longest + 1)
    return f"{f}text\n{text}\n{f}"


def plain(text) -> str:
    """Escape trusted-but-free text (names, generated summaries) for Markdown."""
    s = re.sub(r"([\\`*_{}\[\]<>()#+!|~])", r"\\\1", str(text))
    return s.replace("@", "@​")


_SAFE_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~%!$&'*+,;=:@/?#-]*)?")


def link(url: str | None) -> str:
    if url and len(url) <= 500 and _SAFE_URL.fullmatch(url) and "(" not in url and ")" not in url:
        return f"<{url}>"
    return "(no link)"


def _marker(kind: str, value) -> str:
    return f"<!-- ew-{kind}:{value} -->"


def _parse_marker(body: str | None, kind: str) -> int | None:
    m = re.search(rf"<!-- ew-{kind}:(\d+) -->", body or "")
    return int(m.group(1)) if m else None


def _region(session: Session, region_id: int | None) -> str:
    r = session.get(Region, region_id) if region_id else None
    return f"{r.name} ({r.code})" if r else "unspecified area"


EFFECTS = {
    "alert": "**approve** publishes the alert on the public site; **reject** keeps it unpublished.",
    "cluster": "**approve** marks the signal cluster credible, **reject** not credible; the public signal list shows it was reviewed.",
    "observation": "**approve** marks the figure verified, so it is used in public series and models; **reject** marks it "
                   "disputed, so it stays excluded.",
    "outbreak": "the decision is recorded in the audit log. To change the outbreak's dates or pathogen, edit "
                "`data/outbreaks.yaml` in the public repository.",
    "correction": "the decision is recorded. To retract or correct published output, open a *Retraction* issue.",
}


def relevant(session: Session, item: ReviewItem, today: date) -> bool:
    """Items about historical data (e.g. bulletins from past outbreaks) are not
    sent to GitHub: they do not affect current public outputs."""
    if item.item_type == "observation":
        o = session.get(Observation, item.item_id)
        return o is not None and o.as_of >= today - timedelta(days=365)
    if item.item_type == "outbreak":
        ob = session.get(Outbreak, item.item_id)
        if ob is None:
            return False
        if ob.declared_on is None and ob.ended_on is None:
            return True
        return bool((ob.declared_on and ob.declared_on >= today - timedelta(days=730))
                    or (ob.ended_on and ob.ended_on >= today - timedelta(days=365)))
    return item.item_type in ("alert", "cluster", "correction")


def _cluster_documents(session: Session, cluster_id: int | None) -> list[tuple[Document, Signal]]:
    if not cluster_id:
        return []
    rows = session.execute(select(Document, Signal).join(Signal, Signal.document_id == Document.id)
                           .where(Signal.cluster_id == cluster_id).order_by(Document.published_at.desc())).all()
    seen, out = set(), []
    for doc, sig in rows:
        if doc.id not in seen:
            seen.add(doc.id)
            out.append((doc, sig))
    return out


def render_item(session: Session, item: ReviewItem) -> tuple[str, str, str | None]:
    """(title, body, excerpt comment or None) for a review item."""
    details: list[str] = []
    excerpts: list[tuple[Document, Signal]] = []
    error_text = None
    title = f"{item.item_type} {item.item_id}"
    if item.item_type == "alert" and (a := session.get(Alert, item.item_id)):
        title = f"Alert · {_region(session, a.region_id)}: {a.message[:90]}"
        ev = a.evidence or {}
        details += [f"- **Message:** {plain(a.message)}", f"- **Kind:** {plain(a.kind)} · **confidence:** {plain(a.confidence)}",
                    f"- **Relies on unofficial reports:** {'yes' if a.relies_on_unofficial else 'no'}"]
        if ev.get("summary"):
            details.append(f"- **Evidence:** {plain(ev['summary'])}")
        if ev.get("independent_origins") is not None:
            details.append(f"- **Independent origins:** {plain(ev['independent_origins'])}")
        excerpts = _cluster_documents(session, ev.get("cluster_id"))
    elif item.item_type == "cluster" and (cl := session.get(SignalCluster, item.item_id)):
        title = f"Signal cluster · {_region(session, cl.region_id)}: {cl.assessment[:90]}"
        details += [f"- **Assessment:** {plain(cl.assessment)}", f"- **Summary:** {plain(cl.summary)}",
                    f"- **Corroboration:** {plain(cl.corroboration)} · **documents:** {cl.n_documents} · "
                    f"**independent origins:** {cl.n_independent_origins}",
                    f"- **Languages:** {plain(', '.join(cl.languages or [])) or '—'} · **coordination suspected:** "
                    f"{'yes' if cl.coordination_suspected else 'no'} · **stale:** {'yes' if cl.stale else 'no'}",
                    "", "Evidence features:", fence(_json(cl.evidence))]
        excerpts = _cluster_documents(session, cl.id)
    elif item.item_type == "observation" and (o := session.get(Observation, item.item_id)):
        title = f"Official figure · {_region(session, o.region_id)}: {o.case_class} {o.metric} {o.as_of} = {o.value:g}"
        details += [f"- **Area:** {plain(_region(session, o.region_id))}",
                    f"- **Figure:** {plain(o.case_class)} {plain(o.metric)} ({plain(o.value_type)}, transmission {plain(o.transmission)}) "
                    f"as of {o.as_of}: **{o.value:g}**",
                    f"- **Extraction method:** {plain(o.extraction_method)}"]
        if o.quote:
            details += ["", "Quoted from the source:", fence(o.quote)]
        if o.citation:
            details += ["", "Citation:", fence(o.citation)]
        if o.validation_notes:
            details += ["", "Validation notes:", fence("\n".join(map(str, o.validation_notes)))]
    elif item.item_type == "outbreak" and (ob := session.get(Outbreak, item.item_id)):
        title = f"Outbreak record · {ob.key}"
        details += [f"- **Key:** {plain(ob.key)} · **name:** {plain(ob.name)}", f"- **Pathogen:** {plain(ob.pathogen)}",
                    f"- **Declared:** {ob.declared_on or 'unknown'} · **ended:** {ob.ended_on or 'not ended / unknown'}"]
        if ob.notes:
            details += ["", "Notes:", fence(ob.notes)]
    elif item.item_type == "correction" and (er := session.get(ErrorReport, item.item_id)):
        title = f"Error report · {er.target_type}"
        details += [f"- **About:** {plain(er.target_type)} {plain(er.target_ref or '')}"]
        error_text = er.description
    body = "\n".join([
        _marker("review", item.id),
        f"**Why this needs review:** {plain(item.reason)}", "",
        f"- **Record:** {plain(item.item_type)} {item.item_id}",
        *details, "",
        f"**What a decision does:** {EFFECTS.get(item.item_type, 'the decision is recorded.')}", "",
        "---",
        "Decide by adding the label **approve** or **reject**; whoever adds the label is recorded as the reviewer. "
        "To ask for more information, comment and leave the issue open: the item stays pending.",
    ])
    comment = _excerpt_comment(excerpts, error_text)
    return f"[Review {item.id}] {title}"[:250], body, comment


def _json(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _excerpt_comment(docs: list[tuple[Document, Signal]], error_text: str | None) -> str | None:
    settings = get_settings()
    parts = [_marker("excerpts", 1),
             f"**Source excerpts** — for reviewers only; this comment is deleted automatically "
             f"{settings.raw_content_retention_days} days after it was posted (retention policy). "
             "Excerpts are redacted, untrusted text: verify against the source."]
    if error_text:
        parts += ["", "Error report text:", fence(error_text)]
    for doc, sig in docs[:MAX_EXCERPT_DOCS]:
        when = doc.published_at.date().isoformat() if doc.published_at else "undated"
        langs = ", ".join(sig.languages or [doc.language or "?"])
        flags = "; ".join(sig.review_reasons or [])
        parts += ["", f"- {when} · {plain(langs)} · {plain(doc.source.key if doc.source else '?')} · {link(doc.url)}"
                      + (f" · review notes: {plain(flags)}" if flags else "")]
        text = (doc.title or "").strip()
        body = (doc.text_minimized or "").strip()
        if body and body != text:
            text += "\n\n" + body[:EXCERPT_CHARS] + ("…" if len(body) > EXCERPT_CHARS else "")
        if text.strip():
            parts.append(fence(text.strip()))
    if len(docs) > MAX_EXCERPT_DOCS:
        parts += ["", f"…and {len(docs) - MAX_EXCERPT_DOCS} more documents."]
    return "\n".join(parts) if (docs or error_text) else None


# ---------------------------------------------------------------- forms

def parse_form(body: str | None) -> dict[str, str | None]:
    """Fields of an issue created from an issue form (``### Label`` sections)."""
    out: dict[str, str | None] = {}
    for m in re.finditer(r"^###\s+(.+?)\s*\n(.*?)(?=^###\s|\Z)", body or "", flags=re.M | re.S):
        value = m.group(2).strip()
        out[m.group(1).strip().lower()] = None if value in ("", "_No response_") else value
    return out


def _applied(session: Session, number: int) -> AuditLog | None:
    return session.scalar(select(AuditLog).where(AuditLog.action == "github_action", AuditLog.target_type == "github_issue",
                                                 AuditLog.target_id == str(number)).order_by(AuditLog.at.desc()).limit(1))


def _apply_action(session: Session, issue: dict, actor: str) -> None:
    labels = {lb["name"] for lb in issue["labels"]}
    form = parse_form(issue.get("body"))
    if "retraction" in labels:
        target_id = (form.get("target id") or "").strip().lstrip("#")
        if not target_id.isdigit():
            raise ReviewError("Target ID must be a number")
        note = form.get("public note") or ""
        if not 10 <= len(note) <= 1000:
            raise ReviewError("Public note must be 10-1000 characters")
        retract(session, (form.get("target type") or "").strip(), int(target_id), note, actor)
    elif "transport-status" in labels:
        set_transport_status(session, (form.get("edge key") or "").strip(), (form.get("new service status") or "").strip(),
                             form.get("evidence") or "", actor)
    else:
        raise ReviewError("unknown request type (expected a retraction or transport-status issue)")


# ---------------------------------------------------------------- phases

def apply_from_github(session: Session, gh: GitHub) -> dict:
    """Phase 1: apply reviewer decisions and authorised requests (database writes only)."""
    decided, actions, skipped = [], [], []
    for issue in gh.issues(LABEL_REVIEW):
        if issue["state"] != "open":
            continue
        rid = _parse_marker(issue.get("body"), "review")
        chosen = [lb["name"] for lb in issue["labels"] if lb["name"] in DECISIONS]
        if rid is None or len(chosen) != 1:
            continue
        item = session.get(ReviewItem, rid)
        if item is None or item.status != ReviewStatus.PENDING.value:
            continue
        actor = gh.label_actor(issue["number"], chosen[0])
        if not actor:
            skipped.append(issue["number"])
            continue
        decide(session, rid, DECISIONS[chosen[0]], f"github:{actor}"[:64], f"GitHub issue #{issue['number']}")
        decided.append({"issue": issue["number"], "review_item": rid, "decision": DECISIONS[chosen[0]]})
    for issue in gh.issues(LABEL_ACTION):
        labels = {lb["name"] for lb in issue["labels"]}
        if issue["state"] != "open" or LABEL_APPLY not in labels:
            continue
        prior = _applied(session, issue["number"])
        if prior is not None and (prior.details or {}).get("status") == "applied":
            continue
        actor = gh.label_actor(issue["number"], LABEL_APPLY)
        if not actor:
            skipped.append(issue["number"])
            continue
        try:  # the review primitives validate before they change anything
            _apply_action(session, issue, f"github:{actor}"[:64])
            status, note = "applied", ""
        except (ReviewError, ValueError) as e:
            status, note = "failed", str(e)
        audit(session, f"github:{actor}", "github_action", "github_issue", issue["number"], {"status": status, "note": note})
        actions.append({"issue": issue["number"], "status": status})
    session.flush()
    return {"decisions": decided, "actions": actions, "skipped_no_actor": skipped}


def sync_to_github(session: Session, gh: GitHub, today: date | None = None, max_new: int = 25,
                   settings: Settings | None = None) -> dict:
    """Phase 2 (after the state is saved): acknowledge decisions, open issues for new
    items, delete expired excerpt comments."""
    settings = settings or get_settings()
    today = today or date.today()
    gh.ensure_labels()
    closed = created = excerpts_deleted = 0
    issues = gh.issues(LABEL_REVIEW)
    by_item = {rid: i for i in issues if (rid := _parse_marker(i.get("body"), "review")) is not None}

    for rid, issue in by_item.items():
        if issue["state"] != "open":
            continue
        labels = {lb["name"] for lb in issue["labels"]}
        item = session.get(ReviewItem, rid)
        if item is None:
            gh.comment(issue["number"], "This review item no longer exists in the database; closing.")
            gh.update_issue(issue["number"], state="closed", state_reason="not_planned")
            closed += 1
        elif item.status != ReviewStatus.PENDING.value:
            who = (item.resolved_by or "").removeprefix("github:")
            when = item.resolved_at.date().isoformat() if item.resolved_at else "?"
            gh.comment(issue["number"], f"Decision recorded: **{plain(item.status)}** by `{who}` on {when}. "
                                        "The public site was updated in the same run.")
            gh.update_issue(issue["number"], state="closed",
                            state_reason="completed" if item.status == ReviewStatus.APPROVED.value else "not_planned")
            closed += 1
        elif {"approve", "reject"} <= labels and "conflict" not in labels:
            gh.comment(issue["number"], "Both **approve** and **reject** are set, so nothing was applied. Remove one of them.")
            gh.update_issue(issue["number"], labels=sorted(labels | {"conflict"}))

    pending = session.scalars(select(ReviewItem).where(ReviewItem.status == ReviewStatus.PENDING.value, ReviewItem.priority <= 2)
                              .order_by(ReviewItem.priority, ReviewItem.created_at))
    for item in pending:
        if created >= max_new:
            break
        if item.id in by_item or not relevant(session, item, today):
            continue
        title, body, excerpt = render_item(session, item)
        issue = gh.create_issue(title, body, [LABEL_REVIEW, f"review:{item.item_type}"] + ([LABEL_EXCERPTS] if excerpt else []))
        if excerpt:
            gh.comment(issue["number"], excerpt)
        created += 1

    cutoff = utcnow() - timedelta(days=settings.raw_content_retention_days)
    for issue in issues:
        if LABEL_EXCERPTS not in {lb["name"] for lb in issue["labels"]}:
            continue
        remaining = 0
        for c in gh.comments(issue["number"]):
            if _parse_marker(c.get("body"), "excerpts") is None:
                continue
            if datetime.fromisoformat(c["created_at"].replace("Z", "+00:00")) < cutoff:
                gh.delete_comment(c["id"])
                excerpts_deleted += 1
            else:
                remaining += 1
        if not remaining:
            gh.update_issue(issue["number"], labels=sorted({lb["name"] for lb in issue["labels"]} - {LABEL_EXCERPTS}))

    acknowledged = 0
    for issue in gh.issues(LABEL_ACTION):
        labels = {lb["name"] for lb in issue["labels"]}
        if issue["state"] != "open" or LABEL_APPLY not in labels:
            continue
        prior = _applied(session, issue["number"])
        if prior is None:
            continue
        status, note = (prior.details or {}).get("status"), (prior.details or {}).get("note") or ""
        if status == "applied":
            gh.comment(issue["number"], f"Applied by `{prior.actor.removeprefix('github:')}`; the public site was updated in the same run.")
            gh.update_issue(issue["number"], state="closed", state_reason="completed")
        else:
            gh.comment(issue["number"], f"Could not apply this request: {plain(note)}\n\nEdit the issue, then add the **apply** label again.")
            gh.update_issue(issue["number"], labels=sorted((labels - {LABEL_APPLY}) | {"apply-failed"}))
        acknowledged += 1

    return {"closed": closed, "created": created, "excerpt_comments_deleted": excerpts_deleted, "actions_acknowledged": acknowledged}
