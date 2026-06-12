// Thin typed fetch wrapper over the backend REST API. All endpoints return
// either the resource or the {error: {code, message, details}} envelope.

import type {
  AnalysisDetail,
  AuditEntry,
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
  RunStartResponse,
  Source,
  SourceCreateManual,
  SourceOverrideBody,
} from "./types";

export const API_BASE: string = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "/api";

export class ApiError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const err = body?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "unknown_error",
      err?.message ?? `Request failed (${res.status})`,
      err?.details ?? {},
    );
  }
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = (path: string) => request<void>(path, { method: "DELETE" });

const qs = (params: Record<string, string | number | undefined | null>): string => {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // Projects
  listProjects: (limit = 100, offset = 0) =>
    get<Page<Project>>(`/projects${qs({ limit, offset })}`),
  getProject: (id: string) => get<Project>(`/projects/${id}`),
  createProject: (body: ProjectCreate) => post<Project>("/projects", body),
  updateProject: (id: string, body: ProjectUpdate) => patch<Project>(`/projects/${id}`, body),
  deleteProject: (id: string) => del(`/projects/${id}`),

  // Runs
  startRun: (projectId: string) => post<RunStartResponse>(`/projects/${projectId}/runs`),
  listRuns: (projectId: string) => get<Run[]>(`/projects/${projectId}/runs`),
  getRun: (runId: string) => get<Run>(`/runs/${runId}`),
  pauseRun: (runId: string) => post<Run>(`/runs/${runId}/pause`),
  resumeRun: (runId: string) => post<Run>(`/runs/${runId}/resume`),
  stopRun: (runId: string, reason?: string) => post<Run>(`/runs/${runId}/stop`, { reason }),
  adjustBudget: (runId: string, body: BudgetAdjustBody) => post<Run>(`/runs/${runId}/budget`, body),

  // Escalations
  listEscalations: (projectId: string, status?: string) =>
    get<Escalation[]>(`/projects/${projectId}/escalations${qs({ status })}`),
  resolveEscalation: (escalationId: string, userResponse: Record<string, unknown>) =>
    post<Escalation>(`/escalations/${escalationId}/resolve`, { user_response: userResponse }),

  // Sources
  listSources: (
    projectId: string,
    filters: {
      triage_status?: string;
      discovery_channel?: string;
      cluster_id?: string;
      q?: string;
      limit?: number;
      offset?: number;
    } = {},
  ) => get<Page<Source>>(`/projects/${projectId}/sources${qs({ limit: 500, ...filters })}`),
  getSource: (sourceId: string) => get<Source>(`/sources/${sourceId}`),
  addSource: (projectId: string, body: SourceCreateManual) =>
    post<Source>(`/projects/${projectId}/sources`, body),
  overrideSource: (sourceId: string, body: SourceOverrideBody) =>
    post<Source>(`/sources/${sourceId}/override`, body),
  getAnalysis: (sourceId: string) => get<AnalysisDetail>(`/sources/${sourceId}/analysis`),

  // Field map / gaps / provenance
  getFieldMap: (projectId: string) => get<FieldMap>(`/projects/${projectId}/comparison`),
  listGaps: (projectId: string) => get<Gap[]>(`/projects/${projectId}/gaps`),
  listProvenance: (
    projectId: string,
    filters: { ref_id?: string; source_id?: string; context?: string } = {},
  ) => get<Provenance[]>(`/projects/${projectId}/provenance${qs(filters)}`),

  // Reports
  listReports: (projectId: string) => get<Report[]>(`/projects/${projectId}/reports`),
  getReport: (reportId: string) => get<Report>(`/reports/${reportId}`),
  patchReport: (reportId: string, contentMarkdown: string) =>
    patch<Report>(`/reports/${reportId}`, { content_markdown: contentMarkdown }),
  rewriteReport: (reportId: string, body: ReportRewriteRequest) =>
    post<Report>(`/reports/${reportId}/rewrite`, body),
  reportExportUrl: (reportId: string, format: "md" | "docx") =>
    `${API_BASE}/reports/${reportId}/export?format=${format}`,

  // Presentations
  listPresentations: (projectId: string) =>
    get<Presentation[]>(`/projects/${projectId}/presentations`),
  getPresentation: (presentationId: string) =>
    get<Presentation>(`/presentations/${presentationId}`),
  presentationExportUrl: (presentationId: string, format: "pptx" | "md") =>
    `${API_BASE}/presentations/${presentationId}/export?format=${format}`,

  // Audit
  listAudit: (projectId: string, limit = 100, offset = 0) =>
    get<Page<AuditEntry>>(`/projects/${projectId}/audit${qs({ limit, offset })}`),
};
