# Inquira HTTP API (v1)

Base path: `/api/v1`. JSON everywhere unless noted.

## Conventions

- **Auth** is a session JWT in an `httpOnly`, `SameSite=Lax` cookie named `inquira_session`.
  The browser sends it automatically; always use `credentials: "include"`.
- **CSRF**: every non-GET request must carry the header `X-Inquira-Client: web`.
  Requests without it get `403`.
- **Errors** have the shape `{"error": {"code": "string", "message": "human readable"}}`
  with an appropriate HTTP status. `401` means "not signed in", `403` means "not allowed".
- Timestamps are ISO-8601 UTC strings.

## Health

| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{status: "ok", version: "1.0.0"}` |

## Onboarding (first run)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/setup/status` | – | `{needs_admin: bool, has_datasource: bool, has_llm: bool, completed: bool, demo_available: bool}` |
| POST | `/setup/admin` | `{name, email, password}` | `{user}` + session cookie. `409` once an admin exists. Password ≥ 10 chars. |

`completed` is true when an admin exists **and** a datasource **and** an LLM are configured.
The frontend should send unauthenticated visitors to the setup wizard while `needs_admin` is true,
and send a signed-in admin to the remaining wizard steps while `completed` is false.

## Auth

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/auth/login` | `{email, password}` | `{user}` + cookie. `401` on bad creds, `429` when rate limited. |
| POST | `/auth/logout` | – | `{ok: true}` (clears cookie) |
| GET | `/auth/me` | – | `{user}` or `401` |

`user` = `{id, email, name, role: "admin" | "member", created_at}`

## Users (admin only)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/users` | – | `{users: [user]}` |
| POST | `/users` | `{email, name, password, role}` | `{user}` |
| PATCH | `/users/{id}` | `{role?, name?}` | `{user}` |
| DELETE | `/users/{id}` | – | `{ok: true}` (cannot delete yourself) |

## Settings (admin only, except `GET /settings` which members may read)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/settings` | – | `{llm: LlmSettings \| null, datasource: DatasourceSettings \| null}` |
| GET | `/settings/providers` | – | `{llm: [ProviderSpec], datasource: [ProviderSpec]}` |
| POST | `/settings/llm/models` | `{provider, api_key?, base_url?}` | `{models: [{id, label}], source: "live" \| "curated", message, default_model}`. Lists models live from the provider API (using the typed or stored key), falling back to curated suggestions. |
| POST | `/settings/llm/test` | `{provider, model, api_key?, base_url?}` | `{ok, message, latency_ms}` |
| PUT | `/settings/llm` | `{provider, model, api_key?, base_url?}` | `{llm: LlmSettings}` (omit `api_key` to keep the stored one) |
| POST | `/settings/datasource/test` | `{kind, config}` | `{ok, message, table_count}` |
| PUT | `/settings/datasource` | `{kind, name, config}` | `{datasource: DatasourceSettings}` |
| POST | `/settings/datasource/demo` | – | `{datasource: DatasourceSettings}`. Loads the bundled e-commerce demo. |

```ts
LlmSettings        = { provider: string, model: string, base_url: string | null, has_key: boolean }
DatasourceSettings = { kind: string, name: string, details: Record<string, string> /* secrets removed */ }
ProviderSpec = {
  id: string, label: string, description: string,
  default_model?: string,          // llm only
  models?: string[],               // llm only, suggestions
  fields: Array<{ name: string, label: string, type: "text" | "password" | "number",
                  required: boolean, secret: boolean, placeholder?: string, help?: string }>
}
```

LLM provider ids: `gemini`, `anthropic`, `openai`, `openai_compatible` (Ollama, vLLM, LM Studio, Groq…).
Datasource kinds: `demo`, `duckdb`, `sqlite`, `postgres`, `mysql`, `snowflake`.

## Schema

| Method | Path | Response |
|---|---|---|
| GET | `/schema` | `{datasource: string, tables: [{name, row_count: number \| null, columns: [{name, type}]}]}` |
| POST | `/schema/refresh` | same as above (admin) |
| GET | `/suggestions` | `{questions: string[]}`: starter questions for the empty state |

## Ask (streaming)

`POST /ask` with body `{question: string, conversation_id?: string}` returns **`text/event-stream`**.
Use `fetch` and read the body stream (EventSource can't POST). Each event looks like:

```
event: step
data: {"id":"schema","label":"Reading schema","status":"running"}

```

| event | data |
|---|---|
| `meta` | `{conversation_id, message_id}` (first event) |
| `step` | `{id, label, status: "running" \| "done" \| "error", detail?: string}`. Step ids, in order: `schema`, `context`, `plan`, `validate`, `execute`, `summarize`. `plan`/`validate`/`execute` may repeat on self-repair. |
| `sql` | `{sql: string}` (final validated SQL) |
| `result` | `{columns: [{name, type: "number" \| "string" \| "date" \| "boolean"}], rows: any[][], row_count, truncated: bool, elapsed_ms}` |
| `chart` | `{type: "bar" \| "line" \| "pie" \| "kpi" \| "table", x?: string, y?: string[], title?: string}` |
| `answer` | `{text: string}`: a short natural-language summary (markdown allowed: bold, lists) |
| `error` | `{code, message}`. The stream ends after this. |
| `done` | `{message_id, conversation_id, elapsed_ms}` |

## Conversations

| Method | Path | Response |
|---|---|---|
| GET | `/conversations` | `{conversations: [{id, title, updated_at, message_count}]}` (newest first, the current user's own) |
| GET | `/conversations/{id}` | `{id, title, messages: [Message]}` |
| DELETE | `/conversations/{id}` | `{ok: true}` |
| POST | `/messages/{id}/feedback` | body `{rating: 1 \| -1}` → `{ok: true}` |

```ts
Message = { id, question, status: "ok" | "error", sql: string | null, answer: string | null,
            error: string | null, chart: Chart | null, columns: Column[], rows: any[][],
            row_count: number, truncated: boolean, elapsed_ms: number, rating: 1 | -1 | null, created_at }
```

## Knowledge (business context the AI should know: metric definitions, glossary, join notes)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/knowledge` | – | `{documents: [{id, title, kind, chars, created_at}]}` |
| POST | `/knowledge` | `{title, kind: "metric" \| "glossary" \| "note", content}` | `{document}` (admin) |
| DELETE | `/knowledge/{id}` | – | `{ok: true}` (admin) |

## Audit (admin)

| Method | Path | Response |
|---|---|---|
| GET | `/audit?limit=100` | `{events: [{id, user_email, question, status, sql, row_count, elapsed_ms, created_at}]}` |
