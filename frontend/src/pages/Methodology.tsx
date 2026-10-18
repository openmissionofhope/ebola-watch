import { API_DOCS_URL, STATIC } from "../api";
import { SeverityBadge } from "../components/Badges";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";
import { T, t } from "../i18n";

const DOCS = "https://github.com/openmissionofhope/ebola-watch/tree/main/docs";

export function MethodologyPage() {
  useDocumentTitle(t("Methodology & ethics"));
  return (
    <>
      <PageHead title={t("Methodology and ethics")} />
      <div className="callout">
        <strong>{t("Not a medical service.")}</strong>{" "}
        {t(
          "Ebola Watch provides epidemiological observation, burden estimation, forecasting and public-health intelligence. It is not a medical service and does not provide diagnosis, treatment, medicine, vaccine or other clinical advice. Estimates and forecasts are uncertain and must not be used to make decisions about an individual's care.",
        )}
      </div>

      <section className="card section">
        <h2>{t("What each number means")}</h2>
        <p>{t("Ebola Watch never silently combines these categories, and model estimates are never presented as confirmed cases.")}</p>
        <dl className="kv">
          <dt>{t("Confirmed")}</dt>
          <dd>{t("Laboratory-confirmed cases as reported by official sources, with observation and publication dates.")}</dd>
          <dt>{t("Probable")}</dt>
          <dd>{t("Cases classified as probable by the reporting authority (often deaths with epidemiological links that could not be tested).")}</dd>
          <dt>{t("Suspected")}</dt>
          <dd>{t("Cases under investigation; many will not be Ebola.")}</dd>
          <dt>{t("Unverified signal")}</dt>
          <dd>
            {t(
              "Public reports (news, social media, community) that have not been confirmed. They are aggregated and paraphrased, and never counted as cases.",
            )}
          </dd>
          <dt>{t("Estimated")}</dt>
          <dd>{t("Model-based estimates of infections that occurred, reported or not, with 90% intervals and stated assumptions.")}</dd>
          <dt>{t("Forecast")}</dt>
          <dd>{t("Probabilistic projections of reported cases for up to 28 days.")}</dd>
          <dt>{t("Scenario")}</dt>
          <dd>{t("Projections beyond 28 days, or under assumed changes in response, which depend on assumptions more than on data.")}</dd>
        </dl>
        <p className="small">{t("A missing report is not a zero-case report. A lack of testing cannot establish a lack of disease.")}</p>
      </section>

      <section className="card section">
        <h2>{t("Severity levels")}</h2>
        <ul className="plain">
          <li>
            <SeverityBadge level={0} /> {t("No reliable evidence of current transmission. This does not necessarily establish zero cases.")}
          </li>
          <li>
            <SeverityBadge level={1} />{" "}
            {t(
              "Potential concern or weak early signals; for example unverified independent reports, a recent imported case, or strong connectivity to an affected area.",
            )}
          </li>
          <li>
            <SeverityBadge level={2} />{" "}
            {t("Credible evidence of meaningful risk: limited confirmed transmission, or a confirmed imported case without local spread.")}
          </li>
          <li>
            <SeverityBadge level={3} />{" "}
            {t("Established outbreak: substantial confirmed transmission, laboratory-confirmed geographic expansion, or growth.")}
          </li>
          <li>
            <SeverityBadge level={4} /> {t("Severe, sustained or rapidly expanding outbreak.")}
          </li>
          <li>
            <SeverityBadge level={null} status="insufficient_information" />{" "}
            {t("A previously affected area without recent official data. A data void is not treated as either safety or crisis.")}
          </li>
        </ul>
        <p>
          <strong>{t("Severity and confidence are separate.")}</strong>{" "}
          <T
            k="An area can be at a high level with low confidence (for example, few recent reports), or at an elevated level with high confidence. When incomplete surveillance could hide transmission, the assessment says so explicitly. Severity is based on epidemiological evidence, never on a country's identity or perceived institutional quality. Thresholds are documented in the {link}."
            link={
              <a href={`${DOCS}/SEVERITY.md`} rel="noopener noreferrer">
                {t("severity documentation")}
              </a>
            }
          />
        </p>
      </section>

      <section className="card section">
        <h2>{t("What the models do")}</h2>
        <ul className="trigger-list">
          <li>{t("Build case series from official bulletins, keeping every published version (vintage) and recording revisions.")}</li>
          <li>
            {t(
              "Estimate the reproduction number of reported cases and project reported cases with uncertainty (renewal model), comparing against a simpler growth model.",
            )}
          </li>
          <li>
            {t(
              "Estimate infections beyond reported cases from reported deaths, using species-specific fatality priors and assumptions about how completely deaths are recorded; and, where sourced mobility data are configured, from exported cases.",
            )}
          </li>
          <li>
            {t("Estimate the rate at which new areas become affected, and rank connected areas by relative transport connectivity under explicit scenarios.")}
          </li>
          <li>{t("Backtest forecasts against later reports and publish calibration results, including poor ones.")}</li>
        </ul>
        <h3>{t("What they do not do")}</h3>
        <ul className="trigger-list">
          <li>{t("They do not convert social-media volume into case counts.")}</li>
          <li>{t("They do not inflate estimates because a country has weak institutions; under-reporting is inferred from evidence or not at all.")}</li>
          <li>{t("They do not model individuals, track people, or predict infection in households.")}</li>
          <li>{t("They do not give clinical, treatment, medicine or vaccine advice.")}</li>
        </ul>
        <p>
          {t("Full details (in English):")}{" "}
          <a href={`${DOCS}/METHODOLOGY.md`} rel="noopener noreferrer">
            {t("scientific methodology")}
          </a>{" "}
          ·{" "}
          <a href={`${DOCS}/LIMITATIONS.md`} rel="noopener noreferrer">
            {t("known limitations")}
          </a>{" "}
          · <a href={API_DOCS_URL}>{STATIC ? t("data files") : t("API documentation")}</a>.
        </p>
      </section>

      <section className="card section">
        <h2>{t("Privacy and protection commitments")}</h2>
        <ul className="trigger-list">
          <li>{t("No patient identities, medical records, contact-tracing data, travel histories or household-level maps are collected or shown.")}</li>
          <li>
            {t(
              "Public posts are minimised: personal details are removed before storage, authors are reduced to keyed pseudonyms used only to tell independent sources from copies, and raw text is deleted after a retention period.",
            )}
          </li>
          <li>
            {t(
              "Outputs are limited to countries and first-level administrative units, with small-area and complementary suppression, applied identically to the dashboard, API, exports, alerts and reports.",
            )}
          </li>
          <li>
            {t(
              "Transport information is generalised to corridors between administrative units; no routes, crossings, facilities or response operations are shown.",
            )}
          </li>
          <li>{t("Alerts that rely on unofficial reports are reviewed by people before publication. Corrections and retractions are published.")}</li>
          <li>{t("No community, ethnicity, nationality, religion, language or displacement status is treated as a risk factor.")}</li>
        </ul>
        <p>
          <T
            k="Read the {link} (in English)."
            link={
              <a href={`${DOCS}/ETHICS_RISK_ASSESSMENT.md`} rel="noopener noreferrer">
                {t("ethical risk assessment")}
              </a>
            }
          />
        </p>
      </section>
    </>
  );
}
