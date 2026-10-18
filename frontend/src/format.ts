// Formatting helpers, in the reader's language (see i18n/). Numbers use
// proportional figures except in tables.

import { currentLanguage, fmtDate as i18nDate, fmtDateTime as i18nDateTime, fmtNumber, tv } from "./i18n";

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmtNumber(Math.round(v));
}

export function fmtCompact(v: number): string {
  try {
    return new Intl.NumberFormat(currentLanguage().code === "ln" ? "fr" : currentLanguage().locale, {
      notation: "compact",
      maximumFractionDigits: Math.abs(v) >= 10_000 ? 0 : 1,
    }).format(v);
  } catch {
    return `${Math.round(v)}`;
  }
}

export function fmtPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${fmtNumber(v * 100, digits)}%`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return fmtNumber(v, digits);
}

export const fmtDate = i18nDate;
export const fmtDateTime = i18nDateTime;

export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);
}

/** A controlled value ("pending_review") as readable, translated text. */
export const humanize = tv;

export function rangeText(lo: number | null | undefined, hi: number | null | undefined): string {
  return `${fmtInt(lo)}–${fmtInt(hi)}`;
}
