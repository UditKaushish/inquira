# Reverse-engineering report: QueryZen → Inquira

Inquira is a ground-up rebuild of an earlier prototype called *QueryZen*. This document records what
the original system did, how it was analysed, what was wrong with it, and how each finding was
resolved. It is kept in the repo so contributors understand why the architecture looks the way it does.

## Method

| Step | Tooling | Evidence |
|---|---|---|
| Archive inventory of the shipped artifact (`QueryZen-main.zip`, sha256 `7f3c21fb…2b6180`) | REA `open_binary` + `inspect_artifact` | `ev_e393ee0a…ace1b`: 216 entries (164 files, 52 dirs), no integrity contradictions |
| Static application graph of the React frontend (`web/src`) | REA `analyze_javascript_application` | `ev_d6fc9ed9…58ca4`: 31 modules parsed, 0 parse failures, 13 network request relations, 1 timer |
| Manual source review of the FastAPI backend (≈11k LOC Python) and data assets | ripgrep / reading | Findings below |
| Runtime verification of the rebuild | pytest (41 tests), live end-to-end runs against the demo warehouse and Gemini | `backend/tests/` |

REA results are static observations. They show which code and requests exist, not that they executed.

## What QueryZen was

A natural-language → SQL assistant for one Snowflake database (the Olist e-commerce dataset):

```
React (Vite) ──fetch──► FastAPI ──► "LangGraph" pipeline (hand-rolled, sequential)
                                     ├─ query analyzer (LLM)
                                     ├─ Pinecone retrieval (+ optional Cohere rerank)
                                     ├─ intent normaliser (LLM) → IR builder (LLM) → refiner (LLM loop)
                                     ├─ quality gate → SQL compiler (LLM + regex "fixes") → SQL review (LLM)
                                     └─ Snowflake execution → chart pick → answer composer (LLM)
          MySQL for users
```

Up to about 7 LLM calls per question, four managed services (Snowflake, Pinecone, Cohere, MySQL) needed just to
boot, and a schema fetch that called *its own HTTP API* (`http://localhost:8080/schemas`), which re-ran a live
Snowflake introspection on every question.

## Findings

### Critical (security)

| # | Finding | Impact | Resolution in Inquira |
|---|---|---|---|
| S1 | **Plaintext credentials committed to source**: Snowflake account, user and password (role `ACCOUNTADMIN`) in `app/data/schema_sync/run.py`; MySQL password default in `app/core/config.py`. | Full warehouse takeover by anyone with repo access. | No credential defaults anywhere. Secrets come from env or onboarding and are Fernet-encrypted at rest. **The original credentials must be rotated, because they remain in the old repo's git history.** |
| S2 | `GET /auth/all` was **unauthenticated** and returned `User.__dict__`, including **password hashes**. | Credential dump. | Removed. `GET /users` is admin-only and serialises an explicit allow-list of fields. Covered by a test. |
| S3 | `PUT /auth/update_role/{id}` was **unauthenticated** and promoted any user to ADMIN. | Anyone could become admin. | Admin-only `PATCH /users/{id}`. Role changes revoke existing sessions. Covered by a test. |
| S4 | LLM-generated SQL executed with only a `;`-count check, as an `ACCOUNTADMIN` role. | Prompt injection → `DROP`, `COPY INTO @stage`, data exfiltration. | `sql_guard` AST validation (single SELECT only, forbidden nodes and functions, table allow-list, forced LIMIT), plus read-only sessions in every adapter. 26 guard tests. |
| S5 | `/admin/docs/upload` and `/schemas` had **no auth**. | Anyone could poison the RAG corpus or trigger warehouse scans. | Every route requires a session. Writes are admin-only. |
| S6 | Default JWT secret (`"change-me"`), 8-hour tokens in `localStorage`, no revocation. | Token forgery, XSS token theft. | Boot fails without a ≥32-char secret in production. httpOnly `SameSite=Lax` cookie. Per-user token version enables logout and role-change revocation. CSRF header check. |
| S7 | Gemini API key `print()`ed to stdout on every client init (`llm_client.py`). | Key leakage via logs. | Removed. Provider errors are scrubbed of key-like strings. |
| S8 | No rate limiting, and a bcrypt 4-char minimum password. | Brute force. | Login and ask rate limits (memory or Redis), argon2id, minimum 10 characters, timing-equalised login. |

### Correctness and reliability

| # | Finding | Resolution |
|---|---|---|
| C1 | Login form used `<div onSubmit>` and the sign-up toggle button had **no label**, so new users couldn't find sign-up. | Onboarding wizard creates the first admin. Admins invite members. A real `<form>`. |
| C2 | `QueryInput` defined local `Input`/`Button` components that silently dropped `onKeyPress`/`variant`, so **Enter did nothing**. | Rebuilt composer: Enter sends, Shift+Enter adds a newline, ⌘K focuses. |
| C3 | Admin upload `fetch` sent **no Authorization header**. REA request relation in `pages/AdminPage.jsx`. | Single typed API client with cookie credentials. |
| C4 | Executor error path referenced undefined `sources`/`conf_label` (a `NameError` that masked the real error). | Pipeline errors are typed (`PipelineError`) and streamed to the UI as `error` events. |
| C5 | Global mutable LLM singleton; `llm_choice` from one request leaked into others. | Provider built per request from workspace settings. No shared mutable state. |
| C6 | Hard-coded Olist knowledge (column "fixes" like `STATUS → ORDER_STATUS`, fixed date windows) inside generic code. | Engine is dataset-agnostic. Demo knowledge lives in data (`DEMO_KNOWLEDGE`) and is editable in the UI. |
| C7 | `requirements.txt` was UTF-16 encoded and pinned `torch`, `transformers` and `sentence-transformers` (multi-GB) for a 384-dim embedder. | `pyproject.toml` with ~15 direct deps. BM25 context retrieval needs no ML runtime. |
| C8 | Committed `__pycache__/`, `.docx`, `.pptx`, and an `env.example` that didn't match variable names used in code (`SNOWFLAKE_*` vs `SF_*`). | Clean `.gitignore`. A single documented `INQUIRA_*` config namespace. |

### Architecture

| Before | After |
|---|---|
| Requires Snowflake + Pinecone + Cohere + MySQL to start | Runs with **zero services** (SQLite + bundled DuckDB demo). Scales to Postgres + Redis. |
| Up to ~7 sequential LLM calls per question | 2 calls (plan + summarise), plus bounded self-repair only on failure |
| Single warehouse (Snowflake) | Adapter interface: DuckDB, Postgres, MySQL, Snowflake, SQLite |
| Single LLM wired at import time | Gemini, Claude, OpenAI, and any OpenAI-compatible endpoint (Ollama, vLLM, Groq…) |
| Blocking request returns everything at the end | Server-sent events stream each pipeline stage live |
| Monolithic node files sharing a mutable state bag | Pure pipeline function → testable with a scripted LLM |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the resulting design.
