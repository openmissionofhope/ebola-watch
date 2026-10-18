import { AskBox } from "../components/AskBox";
import { PageHead } from "../components/Layout";
import { useDocumentTitle } from "../hooks";

export function AskPage() {
  useDocumentTitle("Ask");
  return (
    <>
      <PageHead title="Ask about the data" />
      <div className="card">
        <AskBox />
      </div>
      <div className="callout section">
        <strong>For health concerns:</strong> Ebola Watch cannot give medical advice. If someone may be ill or may have been exposed, contact a health
        professional, a health facility, or your national public-health authority or Ebola hotline.
      </div>
    </>
  );
}
