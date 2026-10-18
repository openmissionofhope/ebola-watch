import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks";
import { T, t } from "../i18n";

export function NotFound() {
  useDocumentTitle(t("Not found"));
  return (
    <div className="card">
      <h1>{t("Page not found")}</h1>
      <p>
        <T k="This page does not exist. Return to the {link}." link={<Link to="/">{t("overview")}</Link>} />
      </p>
    </div>
  );
}
