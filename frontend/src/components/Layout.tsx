import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { API_DOCS_URL, STATIC, type Meta } from "../api";
import { fmtDateTime } from "../format";
import { useApi } from "../hooks";

const MetaContext = createContext<Meta | null>(null);
export const useMeta = () => useContext(MetaContext);

const SERVER_ONLY = new Set(["/ask", "/review"]); // need the live API (questions, authenticated review)
const STALE_AFTER_MS = 36 * 3600 * 1000;

const NAV: [string, string][] = ([
  ["/", "Overview"],
  ["/map", "Map"],
  ["/regions", "Regions"],
  ["/evidence", "Evidence"],
  ["/evaluation", "Forecasts & evaluation"],
  ["/transport", "Transport"],
  ["/reports", "Reports"],
  ["/sources", "Sources"],
  ["/ask", "Ask"],
  ["/methodology", "Methodology & ethics"],
  ["/report-error", "Report an error"],
  ["/review", "Review"],
] as [string, string][]).filter(([to]) => !(STATIC && SERVER_ONLY.has(to)));

type Theme = "system" | "light" | "dark";

function readTheme(): Theme {
  try {
    const t = localStorage.getItem("ew-theme");
    return t === "light" || t === "dark" ? t : "system";
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
  return (
    <button type="button" className="theme-toggle" onClick={() => setTheme(next)} aria-label={`Colour theme: ${theme}. Switch to ${next}.`}>
      Theme: {theme === "system" ? "System" : theme === "light" ? "Light" : "Dark"}
    </button>
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
        Skip to main content
      </a>
      <header className="site-header">
        <div className="header-inner">
          <NavLink to="/" className="brand" aria-label="Ebola Watch home">
            <span className="brand-name">Ebola Watch</span>
            <span className="brand-org">Open Mission of Hope · epidemiological intelligence</span>
          </NavLink>
          <ThemeToggle />
        </div>
        <nav className="main-nav" aria-label="Main">
          <ul>
            {NAV.map(([to, label]) => (
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
            <span>SYNTHETIC DATA PRESENT — not real outbreak data. Items marked synthetic are generated for testing or demonstration.</span>
          </div>
        )}
        <StaleSnapshot meta={meta.data} />
        <Disclaimer />
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="footer-inner">
          <p>
            <strong>Not a medical service.</strong> {meta.data?.disclaimer ?? "Ebola Watch provides epidemiological intelligence and does not provide clinical advice."}
          </p>
          <p>
            Official counts, model estimates, forecasts and unverified signals are shown as separate quantities. Published at first-level
            administrative resolution at most; no patient, household or individual-level information is collected or shown.
          </p>
          <p className="small">
            Model {meta.data?.model_version ?? "—"} · latest model run {fmtDateTime(meta.data?.latest_model_run)} · <a href={API_DOCS_URL}>{STATIC ? "Data files" : "API documentation"}</a> ·{" "}
            <a href="https://github.com/openmissionofhope/ebola-watch" rel="noopener noreferrer">Source code</a> · Released under the Christian Open Source
            License (COSL) 1.0 · Boundaries: Natural Earth; geoBoundaries (see NOTICE).
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
        <strong>Out of date.</strong> This page has not been updated since {fmtDateTime(meta.snapshot_generated_at)}. Automatic updates may have stopped; check official sources for
        the latest information.
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
        <strong>Epidemiological intelligence, not medical advice.</strong> Ebola Watch does not diagnose, recommend treatments, medicines or vaccines,
        or assess anyone's symptoms. If someone may be ill or exposed, contact a health professional or your national public-health authority.
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
        aria-label="Dismiss notice for this session"
      >
        Dismiss
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
