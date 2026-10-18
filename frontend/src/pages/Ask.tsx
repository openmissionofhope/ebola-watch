import { AskBox } from "../components/AskBox";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";
import { t } from "../i18n";

export function AskPage() {
  useDocumentTitle(t("Ask"));
  return (
    <>
      <PageHead title={t("Ask about the data")} />
      <div className="card">
        <AskBox />
      </div>
      <div className="callout section">
        <strong>{t("For health concerns:")}</strong>{" "}
        {t(
          "Ebola Watch cannot give medical advice. If someone may be ill or may have been exposed, contact a health professional, a health facility, or your national public-health authority or Ebola hotline.",
        )}
      </div>
    </>
  );
}
