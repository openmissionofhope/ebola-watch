import type { ReactNode } from "react";
import { t, tx } from "../i18n";

export function Loading({ lines = 3, label }: { lines?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="visually-hidden">{label ?? t("Loading…")}</span>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%`, margin: "8px 0" }} />
      ))}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <p style={{ margin: 0 }}>{message}</p>
      {onRetry && (
        <button type="button" className="btn secondary" style={{ marginTop: 8 }} onClick={onRetry}>
          {t("Try again")}
        </button>
      )}
    </div>
  );
}

export function Async<T>({ state, children, lines }: { state: { data: T | null; error: string | null; loading: boolean; reload: () => void }; children: (d: T) => ReactNode; lines?: number }) {
  if (state.error) return <ErrorBox message={state.error} onRetry={state.reload} />;
  if (!state.data) return <Loading lines={lines} />;
  return <>{children(state.data)}</>;
}

/** The fixed wording for estimates that cannot responsibly be given as numbers. */
export const INSUFFICIENT = "Insufficient evidence for a reliable numerical estimate.";

export function Insufficient({ text, reason }: { text?: string; reason?: string | null }) {
  return (
    <div>
      <p className="insufficient" style={{ margin: 0 }}>{text ?? t("Insufficient evidence for a reliable numerical estimate.")}</p>
      {reason && <p className="small muted" style={{ margin: "4px 0 0" }}>{tx(reason)}</p>}
    </div>
  );
}
