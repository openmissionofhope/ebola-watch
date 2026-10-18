import { useState } from "react";
import { ApiError, postJSON, type QueryAnswer } from "../api";
import { t, tx } from "../i18n";

export function AskBox({ compact }: { compact?: boolean }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<QueryAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await postJSON<QueryAnswer>("/query", { question: q.trim() }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("Could not reach the service."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} aria-label={t("Ask about the data")}>
      <div className="field">
        <label htmlFor="ask-q">{t("Ask about reported data, estimates, forecasts or severity")}</label>
        <input
          id="ask-q"
          type="text"
          value={q}
          maxLength={500}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("e.g. How many confirmed cases in Ituri?")}
        />
      </div>
      <div className="btn-row">
        <button className="btn" type="submit" disabled={busy}>{busy ? t("Asking…") : t("Ask")}</button>
      </div>
      {!compact && (
        <p className="small muted" style={{ marginTop: 8 }}>
          {t(
            "Answers come only from published Ebola Watch data. Questions about treatment, medicines, vaccines, symptoms, or identifying or locating people are not answered.",
          )}
        </p>
      )}
      <div aria-live="polite">
        {error && <p className="error-box answer">{error}</p>}
        {answer && (
          <div className={`answer callout ${answer.answered ? "" : "warn"}`}>
            {!answer.answered && <p className="small" style={{ margin: "0 0 4px", fontWeight: 600 }}>{t("Outside the scope of Ebola Watch")}</p>}
            <p style={{ margin: 0 }}>{tx(answer.message)}</p>
          </div>
        )}
      </div>
    </form>
  );
}
