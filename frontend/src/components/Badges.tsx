// Severity and confidence are separate dimensions and always rendered as two
// distinct badges, each with a text label (never colour alone).

import { t } from "../i18n";

export function sevClass(level: number | null | undefined, status?: string): string {
  if (status === "insufficient_information") return "sev-swatch-insufficient";
  if (status === "not_assessed" || level === null || level === undefined) return "sev-swatch-none";
  return `sev-swatch-${level}`;
}

const SEV_ICON: Record<string, string> = {
  "0": "○",
  "1": "◔",
  "2": "◑",
  "3": "◕",
  "4": "●",
  insufficient: "?",
  none: "–",
};

/** Translated name of a severity level. */
export function levelName(level: number): string {
  const names: Record<number, string> = {
    0: t("No current evidence"),
    1: t("Watch"),
    2: t("Elevated"),
    3: t("High"),
    4: t("Critical"),
  };
  return names[level] ?? String(level);
}

const LABEL_LEVEL: Record<string, number> = { "NO CURRENT EVIDENCE": 0, WATCH: 1, ELEVATED: 2, HIGH: 3, CRITICAL: 4 };

export function SeverityBadge({ level, status, label }: { level: number | null | undefined; status?: string; label?: string }) {
  const insufficient = status === "insufficient_information";
  const none = !insufficient && (status === "not_assessed" || level === null || level === undefined);
  const key = insufficient ? "insufficient" : none ? "none" : String(level);
  const labelLevel = label ? LABEL_LEVEL[label.toUpperCase()] : undefined;
  const text = insufficient
    ? t("Insufficient information")
    : none
      ? t("Not assessed")
      : levelName(labelLevel ?? (level as number));
  return (
    <span className="badge" title={t("Severity (how serious the epidemiological situation appears)")}>
      <span className={`swatch ${sevClass(level, status)}`} aria-hidden="true" />
      <span aria-hidden="true">{SEV_ICON[key]}</span>
      <span>
        <span className="visually-hidden">{t("Severity:")} </span>
        {!insufficient && !none ? `${t("Level {n}", { n: level as number })} · ` : ""}
        {text}
      </span>
    </span>
  );
}

export function ConfidenceBadge({ confidence, prefix }: { confidence: string | null | undefined; prefix?: string }) {
  const c = (confidence || "").toLowerCase();
  const n = c === "high" ? 3 : c === "moderate" ? 2 : c === "low" ? 1 : 0;
  const names: Record<string, string> = { high: t("High"), moderate: t("Moderate"), low: t("Low"), very_low: t("Very low") };
  return (
    <span className="badge conf" title={t("Confidence in the assessment (separate from severity)")}>
      <span className="conf-dots" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <i key={i} className={i <= n ? "on" : ""} />
        ))}
      </span>
      <span>
        {prefix ?? t("Confidence")}: {c ? (names[c] ?? titleCase(c)) : t("n/a")}
      </span>
    </span>
  );
}

export function KindTag({ kind }: { kind: "official" | "estimate" | "forecast" | "scenario" | "unverified" | "synthetic" }) {
  const text: Record<string, string> = {
    official: t("Official report"),
    estimate: t("Model estimate"),
    forecast: t("Forecast"),
    scenario: t("Scenario"),
    unverified: t("Unverified"),
    synthetic: t("Synthetic"),
  };
  return <span className="kind-tag">{text[kind]}</span>;
}

const STATUS_STYLE: Record<string, { color: string; icon: string; label: () => string }> = {
  ok: { color: "var(--status-good)", icon: "✓", label: () => t("OK") },
  configured: { color: "var(--status-good)", icon: "✓", label: () => t("Configured (not yet run)") },
  partial: { color: "var(--status-warning)", icon: "!", label: () => t("Partial") },
  unavailable: { color: "var(--status-serious)", icon: "!", label: () => t("Unavailable") },
  requires_configuration: { color: "var(--status-warning)", icon: "⚙", label: () => t("Requires configuration") },
  requires_acknowledgement: { color: "var(--status-warning)", icon: "§", label: () => t("Requires acknowledgement of data-use terms") },
  unsupported: { color: "var(--axis-muted)", icon: "×", label: () => t("Unsupported (no lawful automated access)") },
  disabled: { color: "var(--axis-muted)", icon: "–", label: () => t("Disabled") },
  error: { color: "var(--status-critical)", icon: "✕", label: () => t("Error") },
  unknown: { color: "var(--axis-muted)", icon: "?", label: () => t("Unknown") },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  return (
    <span className="status-pill">
      <span className="status-dot" style={{ background: s.color }} aria-hidden="true" />
      <span aria-hidden="true">{s.icon}</span>
      {s.label()}
    </span>
  );
}

export function titleCase(s: string): string {
  return s
    .toLowerCase()
    .split(/[\s_]+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
