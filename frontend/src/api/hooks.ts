// TanStack Query hooks — one per resource (phase 6 foundation contract).

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AnalysisDetail,
  BudgetAdjustBody,
  Escalation,
  FieldMap,
  Gap,
  Page,
  Presentation,
  Project,
  ProjectCreate,
  ProjectUpdate,
  Provenance,
  Report,
  ReportRewriteRequest,
  Run,
  Source,
  SourceCreateManual,
  SourceOverrideBody,
} from "./types";

export const keys = {
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  runs: (projectId: string) => ["projects", projectId, "runs"] as const,
  run: (runId: string) => ["runs", runId] as const,
  escalations: (projectId: string, status?: string) =>
    ["projects", projectId, "escalations", status ?? "all"] as const,
  sources: (projectId: string, filters?: object) =>
    ["projects", projectId, "sources", filters ?? {}] as const,
  analysis: (sourceId: string) => ["sources", sourceId, "analysis"] as const,
  fieldMap: (projectId: string) => ["projects", projectId, "comparison"] as const,
  gaps: (projectId: string) => ["projects", projectId, "gaps"] as const,
  provenance: (projectId: string, filters?: object) =>
    ["projects", projectId, "provenance", filters ?? {}] as const,
  reports: (projectId: string) => ["projects", projectId, "reports"] as const,
  report: (reportId: string) => ["reports", reportId] as const,
  presentations: (projectId: string) => ["projects", projectId, "presentations"] as const,
  audit: (projectId: string, offset: number) => ["projects", projectId, "audit", offset] as const,
};

export function useProjects(): UseQueryResult<Page<Project>> {
  return useQuery({ queryKey: keys.projects, queryFn: () => api.listProjects() });
}

export function useProject(id: string | undefined, opts: { pollMs?: number | false } = {}) {
  return useQuery({
    queryKey: keys.project(id ?? ""),
    queryFn: () => api.getProject(id!),
    enabled: !!id,
    refetchInterval: opts.pollMs ?? false,
  });
}

export function useRuns(projectId: string | undefined): UseQueryResult<Run[]> {
  return useQuery({
    queryKey: keys.runs(projectId ?? ""),
    queryFn: () => api.listRuns(projectId!),
    enabled: !!projectId,
  });
}

export function useRun(runId: string | undefined, opts: { pollMs?: number | false } = {}) {
  return useQuery({
    queryKey: keys.run(runId ?? ""),
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: opts.pollMs ?? false,
  });
}

export function useEscalations(
  projectId: string | undefined,
  status?: string,
): UseQueryResult<Escalation[]> {
  return useQuery({
    queryKey: keys.escalations(projectId ?? "", status),
    queryFn: () => api.listEscalations(projectId!, status),
    enabled: !!projectId,
  });
}

export function useSources(
  projectId: string | undefined,
  filters: { triage_status?: string; discovery_channel?: string; q?: string } = {},
): UseQueryResult<Page<Source>> {
  return useQuery({
    queryKey: keys.sources(projectId ?? "", filters),
    queryFn: () => api.listSources(projectId!, filters),
    enabled: !!projectId,
  });
}

export function useAnalysis(sourceId: string | undefined): UseQueryResult<AnalysisDetail> {
  return useQuery({
    queryKey: keys.analysis(sourceId ?? ""),
    queryFn: () => api.getAnalysis(sourceId!),
    enabled: !!sourceId,
  });
}

export function useComparison(projectId: string | undefined): UseQueryResult<FieldMap> {
  return useQuery({
    queryKey: keys.fieldMap(projectId ?? ""),
    queryFn: () => api.getFieldMap(projectId!),
    enabled: !!projectId,
  });
}

export function useGaps(projectId: string | undefined): UseQueryResult<Gap[]> {
  return useQuery({
    queryKey: keys.gaps(projectId ?? ""),
    queryFn: () => api.listGaps(projectId!),
    enabled: !!projectId,
  });
}

export function useProvenance(
  projectId: string | undefined,
  filters: { ref_id?: string; source_id?: string; context?: string },
  enabled = true,
): UseQueryResult<Provenance[]> {
  return useQuery({
    queryKey: keys.provenance(projectId ?? "", filters),
    queryFn: () => api.listProvenance(projectId!, filters),
    enabled: !!projectId && enabled,
  });
}

export function useReports(projectId: string | undefined): UseQueryResult<Report[]> {
  return useQuery({
    queryKey: keys.reports(projectId ?? ""),
    queryFn: () => api.listReports(projectId!),
    enabled: !!projectId,
  });
}

export function useReport(reportId: string | undefined): UseQueryResult<Report> {
  return useQuery({
    queryKey: keys.report(reportId ?? ""),
    queryFn: () => api.getReport(reportId!),
    enabled: !!reportId,
  });
}

export function usePresentation(projectId: string | undefined): UseQueryResult<Presentation[]> {
  return useQuery({
    queryKey: keys.presentations(projectId ?? ""),
    queryFn: () => api.listPresentations(projectId!),
    enabled: !!projectId,
  });
}

export function useAudit(projectId: string | undefined, offset = 0, limit = 100) {
  return useQuery({
    queryKey: keys.audit(projectId ?? "", offset),
    queryFn: () => api.listAudit(projectId!, limit, offset),
    enabled: !!projectId,
  });
}

// ---------- Mutations ----------

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => api.createProject(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useUpdateProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectUpdate) => api.updateProject(projectId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.project(projectId) });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: string) => api.deleteProject(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useStartRun(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.startRun(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.runs(projectId) });
      qc.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });
}

export function useRunControl(projectId: string) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: keys.runs(projectId) });
    qc.invalidateQueries({ queryKey: keys.project(projectId) });
  };
  const pause = useMutation({
    mutationFn: (runId: string) => api.pauseRun(runId),
    onSuccess: invalidate,
  });
  const resume = useMutation({
    mutationFn: (runId: string) => api.resumeRun(runId),
    onSuccess: invalidate,
  });
  const stop = useMutation({
    mutationFn: ({ runId, reason }: { runId: string; reason?: string }) =>
      api.stopRun(runId, reason),
    onSuccess: invalidate,
  });
  const adjustBudget = useMutation({
    mutationFn: ({ runId, body }: { runId: string; body: BudgetAdjustBody }) =>
      api.adjustBudget(runId, body),
    onSuccess: invalidate,
  });
  return { pause, resume, stop, adjustBudget };
}

export function useResolveEscalation(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      escalationId,
      response,
    }: {
      escalationId: string;
      response: Record<string, unknown>;
    }) => api.resolveEscalation(escalationId, response),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects", projectId] });
    },
  });
}

export function useSourceOverride(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, body }: { sourceId: string; body: SourceOverrideBody }) =>
      api.overrideSource(sourceId, body),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["projects", projectId, "sources"] });
      qc.invalidateQueries({ queryKey: keys.analysis(vars.sourceId) });
    },
  });
}

export function useAddSource(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SourceCreateManual) => api.addSource(projectId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", projectId, "sources"] }),
  });
}

export function usePatchReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, content }: { reportId: string; content: string }) =>
      api.patchReport(reportId, content),
    onSuccess: (report: Report) => {
      qc.invalidateQueries({ queryKey: keys.reports(report.project_id) });
      qc.invalidateQueries({ queryKey: keys.report(report.id) });
    },
  });
}

export function useRewriteReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ reportId, body }: { reportId: string; body: ReportRewriteRequest }) =>
      api.rewriteReport(reportId, body),
    onSuccess: (report: Report) => {
      qc.invalidateQueries({ queryKey: keys.reports(report.project_id) });
    },
  });
}
