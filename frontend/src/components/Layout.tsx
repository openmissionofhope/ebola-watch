import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { API_DOCS_URL, STATIC, type Meta } from "../api";
import { fmtDateTime } from "../format";
import { useApi } from "../hooks";
import { LANGUAGES, T, currentLanguage, t, useLanguage, type Lang } from "../i18n";

const MetaContext = createContext<Meta | null>(null);
export const useMeta = () => useContext(MetaContext);

const SERVER_ONLY = new Set(["/ask", "/review"]); // need the live API (questions, authenticated review)
const STALE_AFTER_MS = 36 * 3600 * 1000;

function navItems(): [string, string][] {
  const items: [string, string][] = [
    ["/", t("Overview")],
    ["/map", t("Map")],
    ["/regions", t("Regions")],
    ["/evidence", t("Evidence")],
    ["/evaluation", t("Forecasts & evaluation")],
    ["/transport", t("Transport")],
    ["/reports", t("Reports")],
    ["/sources", t("Sources")],
    ["/ask", t("Ask")],
    ["/methodology", t("Methodology & ethics")],
    ["/report-error", t("Report an error")],
    ["/review", t("Review")],
  ];
  return items.filter(([to]) => !(STATIC && SERVER_ONLY.has(to)));
}

type Theme = "system" | "light" | "dark";

function readTheme(): Theme {
  try {
    const v = localStorage.getItem("ew-theme");
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("ew-theme", theme);
    } catch {
      /* storage unavailable: keep in memory */
    }
  }, [theme]);
  const next: Theme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
  const names: Record<Theme, string> = { system: t("System"), light: t("Light"), dark: t("Dark") };
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(next)}
      aria-label={t("Colour theme: {current}. Switch to {next}.", { current: names[theme], next: names[next] })}
    >
      {t("Theme: {name}", { name: names[theme] })}
    </button>
  );
}

function LanguageMenu() {
  const { lang, setLang } = useLanguage();
  return (
    <div className="lang-menu">
      <label htmlFor="ew-lang" className="visually-hidden">
        {t("Language")}
      </label>
      <span aria-hidden="true" className="lang-icon">
        文A
      </span>
      <select id="ew-lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)} translate="no">
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.name}
          </option>
        ))}
      </select>
      <Link to="/languages" className="small">
        {t("Other languages")}
      </Link>
    </div>
  );
}

export function Layout() {
  const meta = useApi<Meta>("/meta");
  const loc = useLocation();
  useEffect(() => {
    const main = document.getElementById("main");
    if (main) main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [loc.pathname]);
  return (
    <MetaContext.Provider value={meta.data}>
      <a className="skip-link" href="#main">
        {t("Skip to main content")}
      </a>
      <header className="site-header">
        <div className="header-inner">
          <NavLink to="/" className="brand" aria-label={t("Ebola Watch home")}>
            <span className="brand-name" translate="no">
              Ebola Watch
            </span>
            <span className="brand-org">
              <span translate="no">Open Mission of Hope</span> · {t("epidemiological intelligence")}
            </span>
          </NavLink>
          <LanguageMenu />
          <ThemeToggle />
        </div>
        <nav className="main-nav" aria-label={t("Main")}>
          <ul>
            {navItems().map(([to, label]) => (
              <li key={to}>
                <NavLink to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : undefined)}>
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        {meta.data?.contains_synthetic_data && (
          <div className="banner synthetic" role="alert">
            <span className="icon" aria-hidden="true">⚠</span>
            <span>{t("SYNTHETIC DATA PRESENT — not real outbreak data. Items marked synthetic are generated for testing or demonstration.")}</span>
          </div>
        )}
        <StaleSnapshot meta={meta.data} />
        <TranslationNotice />
        <Disclaimer />
        {/* a fresh subtree per page keeps browser translators and React in step */}
        <Outlet key={loc.pathname} />
      </main>
      <footer className="site-footer">
        <div className="footer-inner">
          <p>
            <strong>{t("Not a medical service.")}</strong>{" "}
            {t(
              "Ebola Watch provides epidemiological observation, burden estimation, forecasting and public-health intelligence. It is not a medical service and does not provide diagnosis, treatment, medicine, vaccine or other clinical advice. Estimates and forecasts are uncertain and must not be used to make decisions about an individual's care.",
            )}
          </p>
          <p>
            {t(
              "Official counts, model estimates, forecasts and unverified signals are shown as separate quantities. Published at first-level administrative resolution at most; no patient, household or individual-level information is collected or shown.",
            )}
          </p>
          <p className="small">
            {t("Model {version} · latest model run {when}", { version: meta.data?.model_version ?? "—", when: fmtDateTime(meta.data?.latest_model_run) })} ·{" "}
            <a href={API_DOCS_URL}>{STATIC ? t("Data files") : t("API documentation")}</a> ·{" "}
            <a href="https://github.com/openmissionofhope/ebola-watch" rel="noopener noreferrer">
              {t("Source code")}
            </a>{" "}
            · {t("Released under the Christian Open Source License (COSL) 1.0 · Boundaries: Natural Earth; geoBoundaries (see NOTICE).")}
          </p>
        </div>
      </footer>
    </MetaContext.Provider>
  );
}

/** A published snapshot that has stopped updating must say so, not look current. */
function StaleSnapshot({ meta }: { meta: Meta | null }) {
  if (!meta?.static || !meta.snapshot_generated_at) return null;
  const age = Date.now() - new Date(meta.snapshot_generated_at).getTime();
  if (!(age > STALE_AFTER_MS)) return null;
  return (
    <div className="banner warn" role="alert">
      <span className="icon" aria-hidden="true">⚠</span>
      <span>
        <strong>{t("Out of date.")}</strong>{" "}
        {t(
          "This page has not been updated since {when}. Automatic updates may have stopped; check official sources for the latest information.",
          { when: fmtDateTime(meta.snapshot_generated_at) },
        )}
      </span>
    </div>
  );
}

/** Translations are machine-assisted until a native speaker has reviewed them. */
function TranslationNotice() {
  const { setLang } = useLanguage();
  const lang = currentLanguage();
  if (lang.reviewed) return null;
  return (
    <div className="banner info" role="note" lang={lang.code}>
      <span className="icon" aria-hidden="true">文A</span>
      <span>
        <T
          k="This translation was made with machine assistance and has not yet been reviewed by a native speaker. The English version is authoritative: {english}."
          english={
            <button type="button" className="link-button" onClick={() => setLang("en")} lang="en">
              Read in English
            </button>
          }
        />
      </span>
    </div>
  );
}

function Disclaimer() {
  const [hidden, setHidden] = useState(() => {
    try {
      return sessionStorage.getItem("ew-disclaimer-hidden") === "1";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  return (
    <div className="banner info" role="note">
      <span className="icon" aria-hidden="true">ℹ</span>
      <div style={{ flex: 1 }}>
        <strong>{t("Epidemiological intelligence, not medical advice.")}</strong>{" "}
        {t(
          "Ebola Watch does not diagnose, recommend treatments, medicines or vaccines, or assess anyone's symptoms. If someone may be ill or exposed, contact a health professional or your national public-health authority.",
        )}
      </div>
      <button
        type="button"
        className="theme-toggle"
        onClick={() => {
          setHidden(true);
          try {
            sessionStorage.setItem("ew-disclaimer-hidden", "1");
          } catch {
            /* ignore */
          }
        }}
        aria-label={t("Dismiss notice for this session")}
      >
        {t("Dismiss")}
      </button>
    </div>
  );
}

export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <h1>{title}</h1>
      {children}
    </div>
  );
}
