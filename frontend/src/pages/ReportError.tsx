import { useState } from "react";
import { ApiError, postJSON } from "../api";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";

const TARGETS = ["observation", "estimate", "forecast", "severity", "alert", "report", "signal", "transport", "other"];

export function ReportErrorPage() {
  useDocumentTitle("Report an error");
  const [target, setTarget] = useState("observation");
  const [ref, setRef] = useState("");
  const [org, setOrg] = useState("");
  const [desc, setDesc] = useState("");
  const [state, setState] = useState<{ ok?: string; err?: string; busy?: boolean }>({});
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (desc.trim().length < 10) {
      setState({ err: "Please describe the problem in at least 10 characters." });
      return;
    }
    setState({ busy: true });
    try {
      const r = await postJSON<{ id: number; message: string }>("/error-reports", {
        target_type: target,
        target_ref: ref.trim() || null,
        organisation: org.trim() || null,
        description: desc.trim(),
      });
      setState({ ok: `${r.message} Reference number ${r.id}.` });
      setDesc("");
      setRef("");
    } catch (err) {
      setState({ err: err instanceof ApiError ? err.message : "Could not send the report." });
    }
  };
  return (
    <>
      <PageHead title="Report an error or request a correction" />
      <p className="secondary">
        Communities, health authorities and organisations can tell us when something is wrong: a figure, a location, an alert, a translation or a transport
        status. Reports are read by people, and corrections and retractions are published with a public note.
      </p>
      <div className="callout warn">
        <strong>Do not include personal information.</strong> Please do not include names, phone numbers, addresses, or any information about patients,
        contacts or other individuals. Personal details that are submitted are removed automatically.
      </div>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="er-target">What is the report about?</label>
          <select id="er-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            {TARGETS.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="er-ref">Area, report or page (optional)</label>
          <input id="er-ref" type="text" maxLength={128} value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. Ituri, daily report of 18 Oct" />
        </div>
        <div className="field">
          <label htmlFor="er-org">Organisation (optional)</label>
          <input id="er-org" type="text" maxLength={255} value={org} onChange={(e) => setOrg(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="er-desc">Description</label>
          <textarea id="er-desc" maxLength={4000} value={desc} onChange={(e) => setDesc(e.target.value)} required aria-describedby="er-desc-help" />
          <p id="er-desc-help" className="small muted">What is wrong, and if possible, the public source that shows the correct information.</p>
        </div>
        <button className="btn" type="submit" disabled={state.busy}>{state.busy ? "Sending…" : "Send report"}</button>
        <div aria-live="polite" style={{ marginTop: 10 }}>
          {state.ok && <p className="callout">{state.ok}</p>}
          {state.err && <p className="error-box">{state.err}</p>}
        </div>
      </form>
    </>
  );
}
