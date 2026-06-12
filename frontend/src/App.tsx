import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ProvenanceProvider } from "./components/ProvenancePopover";
import { ActivityMonitor } from "./screens/ActivityMonitor/ActivityMonitor";
import { AuditLog } from "./screens/AuditLog/AuditLog";
import { BudgetSettings } from "./screens/BudgetSettings/BudgetSettings";
import { ComparativeAnalysis } from "./screens/ComparativeAnalysis/ComparativeAnalysis";
import { EscalationScreen } from "./screens/Escalation/Escalation";
import { GapAnalysis } from "./screens/GapAnalysis/GapAnalysis";
import { NewResearch } from "./screens/NewResearch/NewResearch";
import { Notifications } from "./screens/Notifications/Notifications";
import { Onboarding } from "./screens/Onboarding/Onboarding";
import { PaperAnalysisDetail } from "./screens/PaperAnalysisDetail/PaperAnalysisDetail";
import { PresentationViewer } from "./screens/PresentationViewer/PresentationViewer";
import { ProjectsDashboard } from "./screens/ProjectsDashboard/ProjectsDashboard";
import { ReportViewer } from "./screens/ReportViewer/ReportViewer";
import { ScopeConfirmation } from "./screens/ScopeConfirmation/ScopeConfirmation";
import { SourceLibrary } from "./screens/SourceLibrary/SourceLibrary";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ProvenanceProvider>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<ProjectsDashboard />} />
              <Route path="onboarding" element={<Onboarding />} />
              <Route path="new" element={<NewResearch />} />
              <Route path="settings" element={<BudgetSettings />} />
              <Route path="notifications" element={<Notifications />} />
              <Route path="projects/:projectId">
                <Route index element={<Navigate to="monitor" replace />} />
                <Route path="scope" element={<ScopeConfirmation />} />
                <Route path="monitor" element={<ActivityMonitor />} />
                <Route path="escalations" element={<EscalationScreen />} />
                <Route path="sources" element={<SourceLibrary />} />
                <Route path="sources/:sourceId" element={<PaperAnalysisDetail />} />
                <Route path="fieldmap" element={<ComparativeAnalysis />} />
                <Route path="gaps" element={<GapAnalysis />} />
                <Route path="report" element={<ReportViewer />} />
                <Route path="presentation" element={<PresentationViewer />} />
                <Route path="audit" element={<AuditLog />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </ProvenanceProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
