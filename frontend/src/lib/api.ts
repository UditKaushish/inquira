import type {
  AuditEvent,
  Conversation,
  ConversationSummary,
  DatasourceSettings,
  KnowledgeDoc,
  KnowledgeKind,
  LlmInput,
  LlmSettings,
  ModelList,
  Providers,
  Rating,
  Role,
  SchemaResponse,
  SetupStatus,
  Settings,
  TestResult,
  User,
} from "./types";

export const API_BASE = "/api/v1";
export const CLIENT_HEADER = { "X-Inquira-Client": "web" } as const;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function toApiError(res: Response): Promise<ApiError> {
  let code = `http_${res.status}`;
  let message = res.statusText || "Request failed";
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "error" in body) {
      const err = (body as { error: { code?: string; message?: string } }).error;
      code = err.code ?? code;
      message = err.message ?? message;
    } else if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      message = typeof detail === "string" ? detail : message;
    }
  } catch {
    /* non-JSON body */
  }
  if (res.status === 429 && message === res.statusText) message = "Too many attempts. Please wait a moment.";
  return new ApiError(res.status, code, message);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") Object.assign(headers, CLIENT_HEADER);
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(API_BASE + path, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the Inquira server. Is the API running?");
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T>(p: string) => request<T>("GET", p);
const post = <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const put = <T>(p: string, b: unknown) => request<T>("PUT", p, b);
const patch = <T>(p: string, b: unknown) => request<T>("PATCH", p, b);
const del = <T>(p: string) => request<T>("DELETE", p);

type Ok = { ok: true };

export const api = {
  health: () => get<{ status: string; version: string }>("/health"),

  setupStatus: () => get<SetupStatus>("/setup/status"),
  createAdmin: (b: { name: string; email: string; password: string }) => post<{ user: User }>("/setup/admin", b),

  login: (b: { email: string; password: string }) => post<{ user: User }>("/auth/login", b),
  logout: () => post<Ok>("/auth/logout"),
  me: () => get<{ user: User }>("/auth/me"),

  users: () => get<{ users: User[] }>("/users"),
  createUser: (b: { email: string; name: string; password: string; role: Role }) => post<{ user: User }>("/users", b),
  updateUser: (id: User["id"], b: { role?: Role; name?: string }) => patch<{ user: User }>(`/users/${id}`, b),
  deleteUser: (id: User["id"]) => del<Ok>(`/users/${id}`),

  settings: () => get<Settings>("/settings"),
  providers: () => get<Providers>("/settings/providers"),
  llmModels: (b: { provider: string; api_key?: string; base_url?: string }) =>
    post<ModelList>("/settings/llm/models", b),
  testLlm: (b: LlmInput) => post<TestResult>("/settings/llm/test", b),
  saveLlm: (b: LlmInput) => put<{ llm: LlmSettings }>("/settings/llm", b),
  testDatasource: (b: { kind: string; config: Record<string, string> }) => post<TestResult>("/settings/datasource/test", b),
  saveDatasource: (b: { kind: string; name: string; config: Record<string, string> }) =>
    put<{ datasource: DatasourceSettings }>("/settings/datasource", b),
  useDemo: () => post<{ datasource: DatasourceSettings }>("/settings/datasource/demo"),

  schema: () => get<SchemaResponse>("/schema"),
  refreshSchema: () => post<SchemaResponse>("/schema/refresh"),
  suggestions: () => get<{ questions: string[] }>("/suggestions"),

  conversations: () => get<{ conversations: ConversationSummary[] }>("/conversations"),
  conversation: (id: string) => get<Conversation>(`/conversations/${id}`),
  deleteConversation: (id: string) => del<Ok>(`/conversations/${id}`),
  feedback: (messageId: string, rating: Rating) => post<Ok>(`/messages/${messageId}/feedback`, { rating }),

  knowledge: () => get<{ documents: KnowledgeDoc[] }>("/knowledge"),
  addKnowledge: (b: { title: string; kind: KnowledgeKind; content: string }) => post<{ document: KnowledgeDoc }>("/knowledge", b),
  updateKnowledge: (id: KnowledgeDoc["id"], b: { title?: string; kind?: KnowledgeKind; content?: string }) =>
    patch<{ document: KnowledgeDoc }>(`/knowledge/${id}`, b),
  deleteKnowledge: (id: KnowledgeDoc["id"]) => del<Ok>(`/knowledge/${id}`),

  audit: (limit = 100) => get<{ events: AuditEvent[] }>(`/audit?limit=${limit}`),
};
