// Types mirroring docs/API.md (v1).

export type Role = "admin" | "member";

export interface User {
  id: string | number;
  email: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface SetupStatus {
  needs_admin: boolean;
  has_datasource: boolean;
  has_llm: boolean;
  completed: boolean;
  demo_available: boolean;
}

export interface LlmSettings {
  provider: string;
  model: string;
  base_url: string | null;
  has_key: boolean;
}

export interface DatasourceSettings {
  kind: string;
  name: string;
  details: Record<string, string>;
}

export interface Settings {
  llm: LlmSettings | null;
  datasource: DatasourceSettings | null;
}

export type FieldType = "text" | "password" | "number";

export interface ProviderField {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  secret: boolean;
  placeholder?: string;
  help?: string;
}

export interface ProviderSpec {
  id: string;
  label: string;
  description: string;
  default_model?: string;
  models?: string[];
  fields: ProviderField[];
}

export interface Providers {
  llm: ProviderSpec[];
  datasource: ProviderSpec[];
}

export interface TestResult {
  ok: boolean;
  message: string;
  latency_ms?: number;
  table_count?: number;
}

export interface LlmInput {
  provider: string;
  model: string;
  api_key?: string;
  base_url?: string;
}

export interface SchemaColumn {
  name: string;
  type: string;
}

export interface SchemaTable {
  name: string;
  row_count: number | null;
  columns: SchemaColumn[];
}

export interface SchemaResponse {
  datasource: string;
  tables: SchemaTable[];
}

export type ColumnType = "number" | "string" | "date" | "boolean";

export interface Column {
  name: string;
  type: ColumnType;
}

export type Cell = string | number | boolean | null;

export type ChartType = "bar" | "line" | "pie" | "kpi" | "table";

export interface Chart {
  type: ChartType;
  x?: string;
  y?: string[];
  title?: string;
}

export type StepStatus = "running" | "done" | "error";

export interface Step {
  id: string;
  label: string;
  status: StepStatus;
  detail?: string;
}

export interface ResultPayload {
  columns: Column[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export type Rating = 1 | -1;

export interface Message {
  id: string;
  question: string;
  status: "ok" | "error";
  sql: string | null;
  answer: string | null;
  error: string | null;
  chart: Chart | null;
  columns: Column[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  rating: Rating | null;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
}

export type KnowledgeKind = "metric" | "glossary" | "note";

export interface KnowledgeDoc {
  id: string | number;
  title: string;
  kind: KnowledgeKind;
  chars: number;
  created_at: string;
}

export interface AuditEvent {
  id: string | number;
  user_email: string;
  question: string;
  status: string;
  sql: string | null;
  row_count: number | null;
  elapsed_ms: number | null;
  created_at: string;
}

/** Server-sent events emitted by POST /ask. */
export type AskEvent =
  | { event: "meta"; data: { conversation_id: string; message_id: string } }
  | { event: "step"; data: Step }
  | { event: "sql"; data: { sql: string } }
  | { event: "result"; data: ResultPayload }
  | { event: "chart"; data: Chart }
  | { event: "answer"; data: { text: string } }
  | { event: "error"; data: { code: string; message: string } }
  | { event: "done"; data: { message_id: string; conversation_id: string; elapsed_ms: number } };

export interface ModelInfo {
  id: string;
  label: string | null;
}

export interface ModelList {
  models: ModelInfo[];
  source: "live" | "curated";
  message: string | null;
  default_model: string;
}
