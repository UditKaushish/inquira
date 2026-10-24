# Data model

Inquira keeps two kinds of data apart:

| Store | What lives there | Who writes it |
|---|---|---|
| **Metadata database** (SQLite locally, Postgres in production) | Users, workspace settings, conversations, answers, knowledge | Inquira |
| **Your warehouse** (DuckDB, Postgres, MySQL, Snowflake, SQLite, or the bundled demo) | Your business data | You. Inquira only ever **reads** it, through read-only sessions |

The schema is versioned with Alembic (`backend/inquira/migrations/`). It upgrades automatically at
startup, or explicitly with `python -m inquira migrate`.

## Entity relationships

```mermaid
erDiagram
    users ||--o{ conversations : owns
    users ||--o{ messages : asked
    users |o--o{ knowledge_docs : wrote
    conversations ||--|{ messages : contains

    users {
        string id PK "uuid hex"
        string email UK "lower-cased"
        string name
        string password_hash "argon2id"
        string role "admin | member"
        int token_version "bumped to revoke sessions"
        datetime created_at
    }
    conversations {
        string id PK
        string user_id FK
        string title "first question, truncated"
        datetime created_at
        datetime updated_at "sidebar ordering"
    }
    messages {
        string id PK
        string conversation_id FK
        string user_id FK
        text question
        string status "pending | ok | error"
        text sql "validated SQL that ran"
        text answer "markdown summary"
        text error
        json chart "type, x, y, title"
        json result "columns + up to 500 rows"
        int row_count
        int elapsed_ms
        int rating "1 | -1 | null"
        datetime created_at
    }
    knowledge_docs {
        string id PK
        string title
        string kind "metric | glossary | note"
        text content
        string created_by FK "nullable"
        datetime created_at
    }
    app_settings {
        string key PK "llm | datasource"
        json value "non-secret config"
        text secret "Fernet-encrypted JSON"
        datetime updated_at
    }
```

## Tables

**`users`**: people who can sign in. The first account is created in onboarding as `admin`; admins
invite `member`s. `token_version` lives in every session token, and incrementing it (logout, role change)
invalidates all of that user's sessions immediately.

**`conversations`**: a thread of questions owned by one user. Users only ever see their own.

**`messages`**: one question and everything Inquira produced for it: the validated SQL, the answer, the
chart spec, a result preview (so history renders without re-querying the warehouse), timing, and the
user's thumbs-up/down. The audit log is a view over this table.

**`knowledge_docs`**: business context written by admins (metric definitions, glossary terms, notes).
Relevant entries are added to the prompt for every question.

**`app_settings`**: workspace configuration as key/value rows. `llm` holds the provider and model, and
`datasource` holds the connection. Anything secret (API keys, database passwords) is stored only in
`secret`, encrypted with a key derived from `INQUIRA_SECRET_KEY` (HKDF + MultiFernet, rotatable), and is
never returned by the API.

## Indexes

| Index | Serves |
|---|---|
| `users.email` (unique) | sign-in |
| `conversations (user_id, updated_at)` | the sidebar: a user's conversations, newest first |
| `messages (conversation_id, created_at)` | opening a conversation in order |
| `messages.created_at` | the audit log |
| `messages.user_id` | per-user queries, cascades |

## Lifecycle and privacy

- Deleting a user cascades to their conversations and messages; their knowledge docs are kept with
  `created_by = NULL`.
- `messages.result` stores a **copy of up to 500 result rows** from your warehouse. Treat the metadata
  database with the same sensitivity as the data users query, back it up, and restrict access.
- The LLM provider receives the schema, relevant knowledge, conversation history (questions and SQL), and at
  most 40 result rows for the summary. Use a local model via the OpenAI-compatible provider to keep
  everything in your network.

## Planned evolution

From the [reliability and scaling roadmap](ARCHITECTURE.md#roadmap), in migration order:

1. **`verified_queries`**: question → SQL pairs promoted from thumbs-up answers, used as few-shot examples.
2. **Column descriptions and sample values** cached per datasource, to improve accuracy on real warehouses.
3. **`usage_events`**: tokens and cost per LLM call, for budgets and model tiering.
4. **Multi-tenancy**: a `workspaces` table, a `workspace_id` on every row, and Postgres row-level security;
   `app_settings` splits into `datasources` and `llm_configs`.
5. **Retention**: configurable expiry for `messages.result` payloads.
