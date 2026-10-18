import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks";

export function NotFound() {
  useDocumentTitle("Not found");
  return (
    <div className="card">
      <h1>Page not found</h1>
      <p>
        This page does not exist. Return to the <Link to="/">overview</Link>.
      </p>
    </div>
  );
}
