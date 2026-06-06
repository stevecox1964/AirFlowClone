import type {
  Connection,
  ConnectionIn,
  DagSpec,
  DagSummary,
  LogResponse,
  OutputResponse,
  PreviewResponse,
  RunDetail,
  RunSummary,
  Variable,
  VariableIn,
} from "./types";

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
    } catch {
      // not JSON; keep statusText
    }
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    throw new Error(`${res.status}: ${msg}`);
  }
  return res.json() as Promise<T>;
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return http<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function putJson<T>(url: string, body: unknown): Promise<T> {
  return http<T>(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function del(url: string): Promise<void> {
  const res = await fetch(url, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json())?.detail ?? detail;
    } catch {
      // not JSON
    }
    throw new Error(
      `${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
    );
  }
}

export const api = {
  listDags: () => http<DagSummary[]>("/api/dags"),
  getDag: (dagId: string) => http<DagSummary>(`/api/dags/${dagId}`),
  listDagRuns: (dagId: string) =>
    http<RunSummary[]>(`/api/dags/${dagId}/runs`),
  triggerDag: (dagId: string, params?: Record<string, unknown>) =>
    postJson<RunSummary>(`/api/dags/${dagId}/runs`, { params: params ?? {} }),
  getRun: (runId: string) => http<RunDetail>(`/api/runs/${runId}`),
  retryTask: (runId: string, taskId: string) =>
    http<RunDetail>(`/api/runs/${runId}/tasks/${taskId}/retry`, {
      method: "POST",
    }),
  getLog: (runId: string, taskId: string, attempt?: number) => {
    const qs = attempt ? `?attempt=${attempt}` : "";
    return http<LogResponse>(`/api/runs/${runId}/tasks/${taskId}/log${qs}`);
  },
  getOutput: (runId: string, taskId: string) =>
    http<OutputResponse>(`/api/runs/${runId}/tasks/${taskId}/output`),
  reload: () => http<{ found: number; errors: number }>("/api/reload", { method: "POST" }),
  pauseDag: (dagId: string) =>
    http<DagSummary>(`/api/dags/${dagId}/pause`, { method: "POST" }),
  unpauseDag: (dagId: string) =>
    http<DagSummary>(`/api/dags/${dagId}/unpause`, { method: "POST" }),
  previewDag: (spec: DagSpec) =>
    postJson<PreviewResponse>("/api/dags/preview", spec),
  createDag: (spec: DagSpec) => postJson<DagSummary>("/api/dags", spec),
  getDagSpec: (dagId: string) => http<DagSpec>(`/api/dags/${dagId}/spec`),
  updateDag: (dagId: string, spec: DagSpec) =>
    http<DagSummary>(`/api/dags/${dagId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    }),
  deleteDag: (dagId: string) => del(`/api/dags/${dagId}`),
  clearDagRuns: (dagId: string) =>
    http<{ deleted_runs: number }>(`/api/dags/${dagId}/runs`, { method: "DELETE" }),

  // Variables
  listVariables: () => http<Variable[]>("/api/variables"),
  upsertVariable: (key: string, body: VariableIn) =>
    putJson<Variable>(`/api/variables/${key}`, body),
  deleteVariable: (key: string) => del(`/api/variables/${key}`),

  // Connections
  listConnections: () => http<Connection[]>("/api/connections"),
  upsertConnection: (connId: string, body: ConnectionIn) =>
    putJson<Connection>(`/api/connections/${connId}`, body),
  deleteConnection: (connId: string) => del(`/api/connections/${connId}`),
};
