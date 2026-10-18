import { useState } from "react";
import { ApiError, ERROR_REPORT_URL, postJSON, STATIC } from "../api";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";
import { t, tx } from "../i18n";

const TARGETS = ["observation", "estimate", "forecast", "severity", "alert", "report", "signal", "transport", "other"];

function targetLabel(target: string): string {
  const labels: Record<string, string> = {
    observation: t("Observation"),
    estimate: t("Estimate"),
    forecast: t("Forecast"),
    severity: t("Severity"),
    alert: t("Alert"),
    report: t("Report"),
    signal: t("Signal"),
    transport: t("Transport"),
    other: t("Other"),
  };
  return labels[target] ?? target;
}

export function ReportErrorPage() {
  useDocumentTitle(t("Report an error"));
  return STATIC ? <ReportErrorLink /> : <ReportErrorForm />;
}

/** The published snapshot has no server to receive reports: they go to a public issue form. */
function ReportErrorLink() {
  return (
    <>
      <PageHead title={t("Report an error or request a correction")} />
      <p className="secondary">
        {t(
          "Communities, health authorities and organisations can tell us when something is wrong: a figure, a location, an alert, a translation or a transport status. Reports are read by people, and corrections and retractions are published with a public note.",
        )}
      </p>
      <div className="callout warn">
        <strong>{t("Reports are public.")}</strong>{" "}
        {t(
          "They are filed as issues on GitHub, where anyone can read them, and your GitHub username is shown. Do not include names, phone numbers, addresses, or any information about patients, contacts or other individuals.",
        )}
      </div>
      <div className="card">
        <p>
          {t(
            "Please say what is wrong, where you saw it (page, area or report), and, if possible, the public source that shows the correct information.",
          )}
        </p>
        <p>
          <a className="btn" href={ERROR_REPORT_URL} rel="noopener noreferrer">
            {t("Open the error report form on GitHub")}
          </a>
        </p>
        <p className="small muted">{t("A free GitHub account is required. The form is in English; you may write in any language.")}</p>
      </div>
    </>
  );
}

function ReportErrorForm() {
  const [target, setTarget] = useState("observation");
  const [ref, setRef] = useState("");
  const [org, setOrg] = useState("");
  const [desc, setDesc] = useState("");
  const [state, setState] = useState<{ ok?: string; err?: string; busy?: boolean }>({});
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (desc.trim().length < 10) {
      setState({ err: t("Please describe the problem in at least 10 characters.") });
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
      setState({ ok: `${tx(r.message)} ${t("Reference number {id}.", { id: r.id })}` });
      setDesc("");
      setRef("");
    } catch (err) {
      setState({ err: err instanceof ApiError ? err.message : t("Could not send the report.") });
    }
  };
  return (
    <>
      <PageHead title={t("Report an error or request a correction")} />
      <p className="secondary">
        {t(
          "Communities, health authorities and organisations can tell us when something is wrong: a figure, a location, an alert, a translation or a transport status. Reports are read by people, and corrections and retractions are published with a public note.",
        )}
      </p>
      <div className="callout warn">
        <strong>{t("Do not include personal information.")}</strong>{" "}
        {t(
          "Please do not include names, phone numbers, addresses, or any information about patients, contacts or other individuals. Personal details that are submitted are removed automatically.",
        )}
      </div>
      <form className="card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="er-target">{t("What is the report about?")}</label>
          <select id="er-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            {TARGETS.map((v) => (
              <option key={v} value={v}>
                {targetLabel(v)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="er-ref">{t("Area, report or page (optional)")}</label>
          <input
            id="er-ref"
            type="text"
            maxLength={128}
            value={ref}
            onChange={(e) => setRef(e.target.value)}
            placeholder={t("e.g. Ituri, daily report of 18 Oct")}
          />
        </div>
        <div className="field">
          <label htmlFor="er-org">{t("Organisation (optional)")}</label>
          <input id="er-org" type="text" maxLength={255} value={org} onChange={(e) => setOrg(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="er-desc">{t("Description")}</label>
          <textarea id="er-desc" maxLength={4000} value={desc} onChange={(e) => setDesc(e.target.value)} required aria-describedby="er-desc-help" />
          <p id="er-desc-help" className="small muted">{t("What is wrong, and if possible, the public source that shows the correct information.")}</p>
        </div>
        <button className="btn" type="submit" disabled={state.busy}>{state.busy ? t("Sending…") : t("Send report")}</button>
        <div aria-live="polite" style={{ marginTop: 10 }}>
          {state.ok && <p className="callout">{state.ok}</p>}
          {state.err && <p className="error-box">{state.err}</p>}
        </div>
      </form>
    </>
  );
}
