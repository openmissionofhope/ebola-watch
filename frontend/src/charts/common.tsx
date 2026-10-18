import type { ReactNode } from "react";
import { fmtCompact } from "../format";

export const M = { top: 16, right: 16, bottom: 34, left: 52 };

export function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  const steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  return (steps.find((s) => n <= s) ?? 10) * p;
}

export function YGrid({ ticks, y, width, left, format = fmtCompact }: { ticks: number[]; y: (v: number) => number; width: number; left: number; format?: (v: number) => string }) {
  return (
    <g>
      {ticks.map((t) => (
        <g key={t}>
          <line className="grid-line" x1={left} x2={width - M.right} y1={y(t)} y2={y(t)} />
          <text className="tick-label" x={left - 6} y={y(t)} dy="0.32em" textAnchor="end">
            {format(t)}
          </text>
        </g>
      ))}
    </g>
  );
}

export function XAxisDates({ ticks, x, y0, fmt }: { ticks: Date[]; x: (d: Date) => number; y0: number; fmt?: (d: Date) => string }) {
  const f = fmt ?? ((d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }));
  // keep labels at least 64px apart so they never collide on narrow screens
  const shown: Date[] = [];
  for (const t of ticks) if (!shown.length || x(t) - x(shown[shown.length - 1]) >= 64) shown.push(t);
  return (
    <g>
      {shown.map((t) => (
        <text key={t.toISOString()} className="tick-label" x={x(t)} y={y0 + 16} textAnchor="middle">
          {f(t)}
        </text>
      ))}
    </g>
  );
}

export function Tooltip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const left = Math.min(Math.max(x + 12, 4), Math.max(width - 250, 4));
  return (
    <div className="chart-tooltip" style={{ left, top: Math.max(y - 10, 0) }} role="status" aria-live="polite">
      {children}
    </div>
  );
}

export function utc(iso: string): Date {
  return new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
}

export function addDays(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 86_400_000);
}

export function HatchDefs({ id, color = "var(--series-1)" }: { id: string; color?: string }) {
  return (
    <defs>
      <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="6" height="6" fill="var(--series-1-wash)" />
        <line x1="0" y1="0" x2="0" y2="6" stroke={color} strokeWidth="1.5" strokeOpacity="0.55" />
      </pattern>
    </defs>
  );
}
