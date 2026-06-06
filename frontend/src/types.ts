export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "upstream_failed";

export type RunStatus = "pending" | "running" | "success" | "failed";

export interface DagTaskMeta {
  task_id: string;
  depends_on: string[];
}

export type ParamType = "str" | "int" | "float" | "bool";

export interface ParamSpec {
  name: string;
  type: ParamType;
  default?: string | number | boolean | null;
  required?: boolean;
}

export interface DagSummary {
  dag_id: string;
  description: string | null;
  schedule: string | null;
  is_paused: boolean;
  next_run_at: string | null;
  parse_error: string | null;
  is_ui_editable: boolean;
  tasks: DagTaskMeta[];
  params: ParamSpec[];
}

export interface TaskInstance {
  task_id: string;
  status: TaskStatus;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface RunSummary {
  id: string;
  dag_id: string;
  status: RunStatus;
  trigger_type: string;
  params: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail extends RunSummary {
  tasks: TaskInstance[];
}

export interface LogResponse {
  attempt: number;
  content: string;
}

export interface OutputResponse {
  present: boolean;
  value: unknown;
  error?: string;
}

export interface TaskSpec {
  task_id: string;
  depends_on: string[];
  body: string;
}

export interface DagSpec {
  dag_id: string;
  description: string | null;
  schedule: string | null;
  params: ParamSpec[];
  tasks: TaskSpec[];
}

export interface Variable {
  key: string;
  value: string | null; // null when secret (masked by the server)
  is_secret: boolean;
  description: string | null;
  updated_at: string | null;
}

export interface VariableIn {
  value: string;
  is_secret: boolean;
  description: string | null;
}

export interface Connection {
  conn_id: string;
  conn_type: string | null;
  host: string | null;
  port: number | null;
  login: string | null;
  has_password: boolean;
  extra: string | null;
  description: string | null;
  updated_at: string | null;
}

export interface ConnectionIn {
  conn_type: string | null;
  host: string | null;
  port: number | null;
  login: string | null;
  password: string | null; // null = unchanged, "" = clear, else set
  extra: string | null;
  description: string | null;
}

export interface SpecValidationError {
  field: string;
  message: string;
}

export interface PreviewResponse {
  source: string;
  errors: SpecValidationError[];
}
