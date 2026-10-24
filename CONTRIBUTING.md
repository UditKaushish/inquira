# Contributing to Inquira

Thanks for helping. Inquira aims to be the most trustworthy open-source way to ask questions of data.

## Development setup

```bash
cd backend && uv venv && uv pip install -e ".[dev]"
.venv/bin/uvicorn inquira.main:app --reload        # http://127.0.0.1:8000/api/docs

cd frontend && npm install && npm run dev          # http://localhost:5173
```

## Before you open a PR

```bash
cd backend  && .venv/bin/ruff check inquira tests && .venv/bin/pytest -q
cd frontend && npx tsc --noEmit && npm run build
```

CI runs the same checks.

## Guidelines

- **Keep the engine framework-free.** `backend/inquira/engine` must not import FastAPI or the DB layer.
  That keeps it testable with a scripted LLM (see `tests/test_pipeline.py`).
- **Never weaken `sql_guard`** without a test that shows why. Every new rule should come with an attack case.
- **New warehouse adapter?** Subclass `Warehouse` in `engine/warehouse/adapters.py`, open a *read-only*
  session, implement `introspect()` and `_run()`, declare `fields`, and register it in `ADAPTERS`.
  Driver imports must be lazy and installed through a pip extra.
- **New LLM provider?** Subclass `LLMProvider` in `engine/llm/providers.py` and register it in `PROVIDERS`.
- **Frontend:** TypeScript strict, Tailwind design tokens (no hard-coded colours), and accessible components.
  Mirror API types in `src/lib/types.ts` and keep `docs/API.md` in sync.
- Small, focused PRs with a clear description are reviewed fastest.

## Code of conduct

Be kind, assume good intent, and keep discussions about the work. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
