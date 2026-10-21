// Interface languages. English is the source; other languages are loaded on
// demand from locales/<code>.json (see engine.ts for the catalog format and
// docs/TRANSLATION.md for how to review or add a language).
//
// Components call t()/tx()/fmt helpers directly; the provider remounts the
// application when the language changes, so nothing needs to subscribe.

import { Fragment, createContext, useContext, useEffect, useState, type ReactNode } from "react";
import countries from "./countries.json";
import { Translator, parseNumber, type Catalog } from "./engine";

export type Lang = "en" | "fr" | "sw" | "ln" | "pt" | "ar" | "ha" | "yo" | "ig" | "am" | "om" | "lg" | "rw";

export interface LanguageInfo {
  code: Lang;
  name: string; // in the language itself
  english: string;
  dir: "ltr" | "rtl";
  locale: string; // for numbers and dates
  reviewed: boolean; // set once a native speaker has reviewed the catalog (docs/TRANSLATION.md)
}

export const LANGUAGES: LanguageInfo[] = [
  { code: "en", name: "English", english: "English", dir: "ltr", locale: "en-GB", reviewed: true },
  { code: "fr", name: "Français", english: "French", dir: "ltr", locale: "fr", reviewed: false },
  { code: "sw", name: "Kiswahili", english: "Swahili", dir: "ltr", locale: "sw", reviewed: false },
  { code: "ln", name: "Lingála", english: "Lingala", dir: "ltr", locale: "ln", reviewed: false },
  { code: "pt", name: "Português", english: "Portuguese", dir: "ltr", locale: "pt", reviewed: false },
  { code: "ar", name: "العربية", english: "Arabic", dir: "rtl", locale: "ar-u-nu-latn", reviewed: false },
  // Nigeria, Ethiopia, Uganda and Rwanda (added October 2026)
  { code: "ha", name: "Hausa", english: "Hausa", dir: "ltr", locale: "ha-NG", reviewed: false },
  { code: "yo", name: "Yorùbá", english: "Yoruba", dir: "ltr", locale: "yo-NG", reviewed: false },
  { code: "ig", name: "Igbo", english: "Igbo", dir: "ltr", locale: "ig-NG", reviewed: false },
  { code: "am", name: "አማርኛ", english: "Amharic", dir: "ltr", locale: "am-ET", reviewed: false },
  { code: "om", name: "Afaan Oromoo", english: "Oromo", dir: "ltr", locale: "om-ET", reviewed: false },
  { code: "lg", name: "Luganda", english: "Luganda", dir: "ltr", locale: "lg-UG", reviewed: false },
  { code: "rw", name: "Ikinyarwanda", english: "Kinyarwanda", dir: "ltr", locale: "rw-RW", reviewed: false },
];

const STORAGE_KEY = "ew-lang";
const COUNTRIES = countries as unknown as Record<string, [string | null, string]>;
const ISO2_BY_NAME = new Map(Object.values(COUNTRIES).filter(([a2]) => a2).map(([a2, name]) => [name, a2 as string]));
const loaders = import.meta.glob<{ default: Catalog }>("./locales/*.json");

let info: LanguageInfo = LANGUAGES[0];
let catalog: Catalog = {};
let locale = "en-GB";
let regionNames: Intl.DisplayNames | null = null;
let numberLocale = "en-GB";
let translator = makeTranslator();

function supported(loc: string): string | null {
  try {
    return Intl.NumberFormat.supportedLocalesOf([loc]).length ? loc : null;
  } catch {
    return null;
  }
}

function makeTranslator(): Translator {
  return new Translator(catalog, {
    number: (raw) => {
      const { value, decimals } = parseNumber(raw);
      return Number.isFinite(value) ? fmtNumber(value, decimals) : raw;
    },
    date: (iso) => fmtDate(iso),
    place: (name) => {
      const a2 = ISO2_BY_NAME.get(name);
      return a2 ? countryName(a2, name) : name;
    },
  });
}

function countryName(iso2: string, english: string): string {
  const iso3 = Object.keys(COUNTRIES).find((k) => COUNTRIES[k][0] === iso2);
  if (iso3 && catalog.places?.[iso3]) return catalog.places[iso3];
  if (info.code === "en" || !regionNames) return english;
  try {
    const n = regionNames.of(iso2);
    return n && n !== iso2 ? n : english;
  } catch {
    return english;
  }
}

async function activate(code: Lang): Promise<void> {
  const next = LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
  const loaded = code === "en" ? {} : ((await loaders[`./locales/${code}.json`]?.())?.default ?? {});
  info = next;
  catalog = loaded;
  // Locales without number/date data in the browser fall back to French (Lingala) or English.
  locale = supported(next.locale) ?? (code === "ln" ? "fr" : "en-GB");
  numberLocale = locale;
  try {
    regionNames = code === "en" ? null : new Intl.DisplayNames([locale], { type: "region" });
  } catch {
    regionNames = null;
  }
  translator = makeTranslator();
  document.documentElement.lang = code;
  document.documentElement.dir = next.dir;
}

export function initialLanguage(): Lang {
  const codes = LANGUAGES.map((l) => l.code) as string[];
  const fromUrl = new URLSearchParams(window.location.search).get("lang");
  if (fromUrl && codes.includes(fromUrl)) return fromUrl as Lang;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && codes.includes(stored)) return stored as Lang;
  } catch {
    /* storage unavailable */
  }
  for (const pref of navigator.languages ?? []) {
    const base = pref.toLowerCase().split("-")[0];
    if (codes.includes(base)) return base as Lang;
  }
  return "en";
}

// ---------------------------------------------------------------- public API

/** Dashboard text: t("Overview"), t("Updated {when}", { when }). The key must be a literal (it is extracted). */
export function t(en: string, params?: Record<string, string | number>): string {
  return translator.t(en, params);
}

/** Dashboard text with React elements in placeholders: <T k="Read the {link}." link={<a …/>} />. */
export function T({ k, ...parts }: { k: string } & Record<string, ReactNode>) {
  const s = translator.ui[k] ?? k;
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of s.matchAll(/\{(\w+)\}/g)) {
    out.push(s.slice(last, m.index));
    out.push(<Fragment key={out.length}>{m[1] in parts ? parts[m[1]] : m[0]}</Fragment>);
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(s.slice(last));
  return <>{out}</>;
}

/** Text generated by the backend (explanations, notes, alerts): translated when the catalog has it, else English. */
export function tx(text: string | null | undefined): string {
  return translator.tx(text);
}

/** A controlled value such as "pending_review" or "moderate", humanised and translated. */
export function tv(value: string | null | undefined): string {
  if (!value) return "—";
  const human = value.replace(/_/g, " ");
  const en = human.charAt(0).toUpperCase() + human.slice(1);
  const lower = translator.server[value] ?? translator.server[human];
  return translator.ui[en] ?? translator.server[en] ?? (lower ? lower.charAt(0).toLocaleUpperCase() + lower.slice(1) : en);
}

/** Name of an area: countries in the reader's language, sub-national units as published. */
export function placeName(region: { code: string; name: string; level?: number } | null | undefined): string {
  if (!region) return "—";
  const c = COUNTRIES[region.code];
  if ((region.level ?? 0) === 0 && c?.[0]) return countryName(c[0], region.name);
  return region.name;
}

export function currentLanguage(): LanguageInfo {
  return info;
}

export function isRtl(): boolean {
  return info.dir === "rtl";
}

export function fmtNumber(v: number, decimals = 0): string {
  return new Intl.NumberFormat(numberLocale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(v);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(locale, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

// ---------------------------------------------------------------- provider

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: "en", setLang: () => {} });
export const useLanguage = () => useContext(LangContext);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLanguage);
  const [ready, setReady] = useState<Lang | null>(null);
  useEffect(() => {
    let live = true;
    activate(lang).then(
      () => live && setReady(lang),
      () => live && setReady(lang), // a missing catalog leaves English in place
    );
    return () => {
      live = false;
    };
  }, [lang]);
  const setLang = (l: Lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* keep in memory */
    }
    const url = new URL(window.location.href);
    if (url.searchParams.has("lang")) {
      url.searchParams.set("lang", l);
      window.history.replaceState(window.history.state, "", url);
    }
    setLangState(l);
  };
  if (ready === null) return null;
  // the previous language stays on screen until the next catalog has loaded
  return (
    <LangContext.Provider value={{ lang: ready, setLang }}>
      <Fragment key={ready}>{children}</Fragment>
    </LangContext.Provider>
  );
}
