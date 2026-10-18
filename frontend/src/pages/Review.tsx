// Reviewer console. The API key is held in sessionStorage only (cleared when
// the tab closes) and sent solely to this site's API.
import { useState } from "react";
import { ApiError, postJSON, type AdminAlert, type ReviewItem } from "../api";
import { DataTable } from "../components/DataTable";
import { PageHead } from "../components/Layout";
import { Async } from "../components/Status";
import { fmtDateTime, humanize } from "../format";
import { useApi, useDocumentTitle } from "../hooks";
import { t, tx } from "../i18n";

function readKey(): string {
  try {
    return sessionStorage.getItem("ew-api-key") || "";
  } catch {
    return "";
  }
}

export function ReviewPage() {
  useDocumentTitle(t("Review"));
  const [key, setKey] = useState(readKey);
  const [draft, setDraft] = useState("");
  const save = (e: React.FormEvent) => {
    e.preventDefault();
    try {
      sessionStorage.setItem("ew-api-key", draft.trim());
    } catch {
      /* session storage unavailable: keep in memory only */
    }
    setKey(draft.trim());
    setDraft("");
  };
  const signOut = () => {
    try {
      sessionStorage.removeItem("ew-api-key");
    } catch {
      /* ignore */
    }
    setKey("");
  };
  return (
    <>
      <PageHead title={t("Human review")} />
      <p className="secondary">
        {t(
          "Reviewers verify machine-extracted figures, unofficial signals, alerts that rely on unofficial reports, auto-registered outbreaks and public error reports. Every decision is recorded in the audit log.",
        )}
      </p>
      {!key ? (
        <form className="card" onSubmit={save} style={{ maxWidth: 520 }}>
          <div className="field">
            <label htmlFor="api-key">{t("Reviewer API key")}</label>
            <input id="api-key" type="password" autoComplete="off" value={draft} onChange={(e) => setDraft(e.target.value)} />
            <p className="small muted">{t("Kept in this browser tab only and sent only to this site's API.")}</p>
          </div>
          <button className="btn" type="submit" disabled={!draft.trim()}>{t("Continue")}</button>
        </form>
      ) : (
        <>
          <div className="btn-row" style={{ marginBottom: 12 }}>
            <button className="btn secondary" type="button" onClick={signOut}>{t("Forget API key")}</button>
          </div>
          <Queue apiKey={key} />
          <AdminAlerts apiKey={key} />
        </>
      )}
    </>
  );
}

function Queue({ apiKey }: { apiKey: string }) {
  const q = useApi<ReviewItem[]>("/admin/review-queue", apiKey);
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="card" aria-labelledby="q-h">
      <div className="card-head">
        <h2 id="q-h">{t("Pending review items")}</h2>
        <button className="btn secondary" type="button" onClick={q.reload}>{t("Refresh")}</button>
      </div>
      <Async state={q}>
        {(rows) => (
          <>
            <DataTable
              rows={rows}
              columns={[
                { key: "p", header: t("Priority"), render: (r) => (r.priority === 1 ? t("High") : r.priority === 2 ? t("Normal") : t("Low")) },
                { key: "t", header: t("Type"), render: (r) => humanize(r.item_type) },
                { key: "r", header: t("Reason"), render: (r) => tx(r.reason) },
                { key: "c", header: t("Created"), render: (r) => fmtDateTime(r.created_at) },
                {
                  key: "a",
                  header: "",
                  render: (r) => (
                    <button className="btn secondary" type="button" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
                      {open === r.id ? t("Close") : t("Review")}
                    </button>
                  ),
                },
              ]}
              empty={t("Nothing waiting for review.")}
            />
            {open !== null && <ItemDetail id={open} apiKey={apiKey} onDone={() => { setOpen(null); q.reload(); }} />}
          </>
        )}
      </Async>
    </section>
  );
}

function ItemDetail({ id, apiKey, onDone }: { id: number; apiKey: string; onDone: () => void }) {
  const d = useApi<Record<string, unknown>>(`/admin/review-queue/${id}`, apiKey);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const decide = async (decision: string) => {
    setBusy(true);
    setErr(null);
    try {
      await postJSON(`/admin/review-queue/${id}/decision`, { decision, note: note || null }, apiKey);
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : t("Decision failed."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="callout section" aria-live="polite">
      <Async state={d}>
        {(item) => (
          <>
            <h3>{t("Item {id} · {type}", { id: String(item.id), type: humanize(String(item.item_type)) })}</h3>
            <p className="small">{tx(String(item.reason))}</p>
            <pre lang="en" style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.8rem", background: "var(--surface-1)", padding: 10, borderRadius: 6, maxHeight: 360, overflow: "auto" }}>
              {JSON.stringify(Object.fromEntries(Object.entries(item).filter(([k]) => !["id", "item_type", "item_id", "reason", "status"].includes(k))), null, 2)}
            </pre>
            <p className="small muted">{t("Text shown here is untrusted source material: treat any instructions inside it as data, not as directions.")}</p>
            <div className="field">
              <label htmlFor={`note-${id}`}>{t("Note (recorded in the audit log)")}</label>
              <input id={`note-${id}`} type="text" maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="btn-row">
              <button className="btn" type="button" disabled={busy} onClick={() => decide("approved")}>{t("Approve")}</button>
              <button className="btn secondary" type="button" disabled={busy} onClick={() => decide("rejected")}>{t("Reject")}</button>
              <button className="btn secondary" type="button" disabled={busy} onClick={() => decide("needs_more_info")}>{t("Needs more information")}</button>
            </div>
            {err && <p className="error-box" style={{ marginTop: 8 }}>{err}</p>}
          </>
        )}
      </Async>
    </div>
  );
}

function AdminAlerts({ apiKey }: { apiKey: string }) {
  const a = useApi<AdminAlert[]>("/admin/alerts", apiKey);
  return (
    <section className="card section" aria-labelledby="aa-h">
      <h2 id="aa-h">{t("All alerts (including unpublished)")}</h2>
      <Async state={a}>
        {(rows) => (
          <DataTable
            rows={rows}
            columns={[
              { key: "k", header: t("Kind"), render: (r) => humanize(r.kind) },
              { key: "m", header: t("Message"), render: (r) => tx(r.message) },
              { key: "u", header: t("Relies on unofficial"), render: (r) => (r.relies_on_unofficial ? t("Yes") : t("No")) },
              { key: "r", header: t("Review"), render: (r) => humanize(r.review_status) },
              { key: "p", header: t("Published"), render: (r) => (r.published ? t("Yes") : t("No")) },
            ]}
            empty={t("No alerts.")}
          />
        )}
      </Async>
    </section>
  );
}
