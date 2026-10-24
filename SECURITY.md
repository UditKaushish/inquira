# Security

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's
[private vulnerability reporting](https://github.com/UditKaushish/inquira/security/advisories/new) instead.
We aim to acknowledge reports within 72 hours and to ship a fix or mitigation within 14 days for
high-severity issues.

## Threat model

Inquira sits between users, an LLM provider, and a data warehouse. We assume:

- **Model output is untrusted.** A user (or text inside the data) may try to make the model emit harmful SQL.
- **Users are authenticated but not all trusted equally.** Members can ask questions. Only admins configure
  credentials, models, knowledge, and users.
- **The metadata database and logs may be read by operators.** Secrets in them are encrypted, and passwords are hashed.

## Controls

| Layer | Control |
|---|---|
| SQL execution | sqlglot AST validation: single read query, forbidden statement types (DDL/DML/`COPY`/`ATTACH`/`SET`/`PRAGMA`/`SELECT INTO`), forbidden file/network/sleep functions, system catalogs blocked, table allow-list from the introspected schema, mandatory `LIMIT` |
| Warehouse sessions | Read-only at the driver/session level for every adapter, plus statement timeouts. DuckDB also disables external access and locks its configuration |
| Authentication | argon2id password hashing, timing-equalised login, minimum 10-character passwords, rate-limited login (per IP and per account) |
| Sessions | Signed JWT in an `httpOnly`, `SameSite=Lax` cookie scoped to `/api`, `Secure` in production. Server-side revocation via per-user token version (logout, role change) |
| CSRF | All state-changing requests require the `X-Inquira-Client` header, which cross-site forms cannot send. CORS is limited to configured origins |
| Authorisation | Role checks on every route. Conversations, messages, and feedback are scoped to their owner |
| Secrets | LLM keys and DB passwords are Fernet-encrypted at rest, never returned by the API, and scrubbed from provider error messages |
| Transport and headers | HSTS (production), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, and a CSP from nginx |
| Abuse | Per-user and per-IP rate limits on `/ask` (Redis-backed when scaled out) |
| Data minimisation | Only schema, admin knowledge, and at most 40 result rows are sent to the model. Use a local model for zero egress |

## Operator checklist

- [ ] Set a unique `INQUIRA_SECRET_KEY` (≥ 32 chars) and keep it secret. Rotating it invalidates sessions and stored credentials.
- [ ] Serve over HTTPS and set `INQUIRA_COOKIE_SECURE=true`.
- [ ] Connect warehouses with a **dedicated read-only role** limited to the schemas users should query.
- [ ] Use Postgres for metadata and back it up.
- [ ] Set `INQUIRA_REDIS_URL` when running more than one API replica.
- [ ] Note that file-based datasources (DuckDB/SQLite paths) can read any file the API process can access. Only admins can configure them, so run the container as the provided non-root user.
