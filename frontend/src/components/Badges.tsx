// Severity and confidence are separate dimensions and always rendered as two
// distinct badges, each with a text label (never colour alone).

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

export const LEVEL_NAMES: Record<number, string> = {
  0: "No current evidence",
  1: "Watch",
  2: "Elevated",
  3: "High",
  4: "Critical",
};

export function SeverityBadge({ level, status, label }: { level: number | null | undefined; status?: string; label?: string }) {
  const insufficient = status === "insufficient_information";
  const none = !insufficient && (status === "not_assessed" || level === null || level === undefined);
  const key = insufficient ? "insufficient" : none ? "none" : String(level);
  const text = insufficient ? "Insufficient information" : none ? "Not assessed" : label ? titleCase(label) : LEVEL_NAMES[level as number];
  return (
    <span className="badge" title="Severity (how serious the epidemiological situation appears)">
      <span className={`swatch ${sevClass(level, status)}`} aria-hidden="true" />
      <span aria-hidden="true">{SEV_ICON[key]}</span>
      <span>
        <span className="visually-hidden">Severity: </span>
        {!insufficient && !none ? `Level ${level} · ` : ""}
        {text}
      </span>
    </span>
  );
}

export function ConfidenceBadge({ confidence, prefix = "Confidence" }: { confidence: string | null | undefined; prefix?: string }) {
  const c = (confidence || "").toLowerCase();
  const n = c === "high" ? 3 : c === "moderate" ? 2 : c === "low" ? 1 : 0;
  return (
    <span className="badge conf" title="Confidence in the assessment (separate from severity)">
      <span className="conf-dots" aria-hidden="true">
        {[1, 2, 3].map((i) => (
          <i key={i} className={i <= n ? "on" : ""} />
        ))}
      </span>
      <span>
        {prefix}: {c ? titleCase(c) : "n/a"}
      </span>
    </span>
  );
}

export function KindTag({ kind }: { kind: "official" | "estimate" | "forecast" | "scenario" | "unverified" | "synthetic" }) {
  const text: Record<string, string> = {
    official: "Official report",
    estimate: "Model estimate",
    forecast: "Forecast",
    scenario: "Scenario",
    unverified: "Unverified",
    synthetic: "Synthetic",
  };
  return <span className="kind-tag">{text[kind]}</span>;
}

const STATUS_STYLE: Record<string, { color: string; icon: string; label: string }> = {
  ok: { color: "var(--status-good)", icon: "✓", label: "OK" },
  configured: { color: "var(--status-good)", icon: "✓", label: "Configured (not yet run)" },
  partial: { color: "var(--status-warning)", icon: "!", label: "Partial" },
  unavailable: { color: "var(--status-serious)", icon: "!", label: "Unavailable" },
  requires_configuration: { color: "var(--status-warning)", icon: "⚙", label: "Requires configuration" },
  requires_acknowledgement: { color: "var(--status-warning)", icon: "§", label: "Requires acknowledgement of data-use terms" },
  unsupported: { color: "var(--axis-muted)", icon: "×", label: "Unsupported (no lawful automated access)" },
  disabled: { color: "var(--axis-muted)", icon: "–", label: "Disabled" },
  error: { color: "var(--status-critical)", icon: "✕", label: "Error" },
  unknown: { color: "var(--axis-muted)", icon: "?", label: "Unknown" },
};

export function StatusPill({ status }: { status: string }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.unknown;
  return (
    <span className="status-pill">
      <span className="status-dot" style={{ background: s.color }} aria-hidden="true" />
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
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
