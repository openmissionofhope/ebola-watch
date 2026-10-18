import { Link } from "react-router-dom";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";
import { LANGUAGES, T, t, useLanguage } from "../i18n";

const GUIDE = "https://github.com/openmissionofhope/ebola-watch/blob/main/docs/TRANSLATION.md";

export function LanguagesPage() {
  useDocumentTitle(t("Languages"));
  const { lang, setLang } = useLanguage();
  return (
    <>
      <PageHead title={t("Languages")} />
      <p className="secondary">
        {t(
          "Ebola Watch is written in English. The interface and the generated explanations, alerts and reports are also available in the languages below. You can change the language at the top of every page.",
        )}
      </p>
      <section className="card section" aria-labelledby="builtin-h">
        <h2 id="builtin-h">{t("Built-in languages")}</h2>
        <ul className="lang-list">
          {LANGUAGES.map((l) => (
            <li key={l.code}>
              <button type="button" className="link-button" lang={l.code} onClick={() => setLang(l.code)} aria-current={l.code === lang ? "true" : undefined} translate="no">
                {l.name}
              </button>{" "}
              <span className="small muted">
                {l.code === "en"
                  ? t("Original version")
                  : l.reviewed
                    ? t("Reviewed by a native speaker")
                    : t("Machine-assisted translation, not yet reviewed by a native speaker")}
              </span>
            </li>
          ))}
        </ul>
        <p className="small muted">
          {t(
            "Source titles, citations, licences and some technical notes stay in their original language. Area names are shown as officially published. Anything that has no translation yet is shown in English.",
          )}
        </p>
      </section>

      <section className="card section" aria-labelledby="other-h">
        <h2 id="other-h">{t("Other languages")}</h2>
        <p>{t("Your browser can translate this site into many other languages. Availability depends on your browser.")}</p>
        <ul className="trigger-list">
          <li>{t("Chrome or Edge on a computer: right-click the page and choose “Translate to…”.")}</li>
          <li>{t("Chrome on Android: open the ⋮ menu and choose “Translate…”.")}</li>
          <li>{t("Safari on iPhone, iPad or Mac: use the page menu (aA) or the translate icon in the address bar.")}</li>
          <li>{t("Firefox: use the translation icon in the address bar, if your language is offered. Firefox translates on your own device.")}</li>
        </ul>
        <div className="callout warn">
          {t(
            "Machine translation can be wrong, especially for medical wording. Figures on this site are protected from being changed by translation, but check important information against the English version or official sources.",
          )}
        </div>
        <p className="small muted">
          {t(
            "Except in Firefox, browser translation sends the text of the page to the browser maker's translation service. The pages contain no personal information.",
          )}
        </p>
      </section>

      <section className="card section" aria-labelledby="help-h">
        <h2 id="help-h">{t("Help improve a translation")}</h2>
        <p>
          <T
            k="If you speak one of these languages, you can review or correct its translation: see the {guide}, or {report}."
            guide={
              <a href={GUIDE} rel="noopener noreferrer">
                {t("translation guide")}
              </a>
            }
            report={<Link to="/report-error">{t("report a translation error")}</Link>}
          />
        </p>
      </section>
    </>
  );
}
