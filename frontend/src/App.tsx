import { BrowserRouter, Route, Routes } from "react-router-dom";
import { BASE, STATIC } from "./api";
import { Layout } from "./components/Layout";
import { AskPage } from "./pages/Ask";
import { EvaluationPage } from "./pages/Evaluation";
import { EvidencePage } from "./pages/Evidence";
import { LanguagesPage } from "./pages/Languages";
import { MapPage } from "./pages/MapPage";
import { MethodologyPage } from "./pages/Methodology";
import { NotFound } from "./pages/NotFound";
import { OverviewPage } from "./pages/Overview";
import { RegionDetailPage } from "./pages/RegionDetail";
import { RegionsPage } from "./pages/Regions";
import { ReportErrorPage } from "./pages/ReportError";
import { ReportsPage, ReportViewPage } from "./pages/Reports";
import { ReviewPage } from "./pages/Review";
import { SourcesPage } from "./pages/Sources";
import { TransportPage } from "./pages/Transport";

export function App() {
  return (
    <BrowserRouter basename={BASE.replace(/\/$/, "") || "/"}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
          <Route path="map" element={<MapPage />} />
          <Route path="regions" element={<RegionsPage />} />
          <Route path="region/:code" element={<RegionDetailPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="evaluation" element={<EvaluationPage />} />
          <Route path="transport" element={<TransportPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="reports/:id" element={<ReportViewPage />} />
          <Route path="sources" element={<SourcesPage />} />
          {!STATIC && <Route path="ask" element={<AskPage />} />}
          <Route path="methodology" element={<MethodologyPage />} />
          <Route path="report-error" element={<ReportErrorPage />} />
          <Route path="languages" element={<LanguagesPage />} />
          {!STATIC && <Route path="review" element={<ReviewPage />} />}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
