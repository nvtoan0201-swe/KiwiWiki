# Phase 0 — Foundation & Scaffolding

**Goal:** Stand up the skeleton everything else builds on: project structure, configuration, database with the full shared schema, migrations, a running API, the LLM/embeddings/event/audit/provenance plumbing. No agent behavior yet — this phase is "the lights turn on and the contracts exist."

**Prerequisites:** none.

---

## Deliverables (files/modules)

### Backend skeleton
- `backend/pyproject.toml` — dependencies, ruff/black/mypy/pytest config.
- `backend/app/main.py` — FastAPI app factory, router registration, CORS, startup/shutdown hooks (DB pool, Redis, task runner).
- `backend/app/core/config.py` — Pydantic `Settings` from env: DB URL, Redis URL, Anthropic API key, embeddings config, source API keys, budget defaults, environment.
- `backend/app/core/logging.py` — structured JSON logging; request-id middleware.
- `backend/app/core/errors.py` — base `AppError` + typed subclasses (`NotFound`, `ValidationError`, `BudgetExceeded`, `LLMError`, `SourceUnavailable`, `EscalationRequired`); FastAPI exception handlers returning the `{error:{code,message,details}}` envelope.
- `backend/app/core/constants.py` — all enums from the overview (§4).

### Database & models
- `backend/app/db/session.py` — async engine, session factory, dependency.
- `backend/app/db/base.py` — declarative base, common mixins (`id` UUID pk, `created_at`, `updated_at`).
- `backend/app/db/models/*.py` — one model file per table in the shared data model (§5). Include `pgvector` `Vector` column on `sources.embedding`.
- `backend/alembic/` — Alembic configured for async; an initial migration creating **all** shared tables and enabling the `pgvector` extension.

### Schemas
- `backend/app/schemas/*.py` — Pydantic models for each entity: a `*Create`, `*Read`, and `*Update` where relevant. These are the API contract; keep them stable.

### Adapters (interfaces + minimal impls)
- `backend/app/adapters/llm/client.py` — `LLMClient` wrapper. Methods: `complete(messages, system, max_tokens, response_schema=None)` and `complete_json(...)` (parses/validates structured output against a Pydantic schema, with one repair retry). Responsibilities: retry/backoff, token accounting hook (calls a budget callback), prompt-version tagging, error mapping to `LLMError`. **Stage code must never import the SDK directly.**
- `backend/app/adapters/llm/prompts/` — directory for versioned prompt templates (empty now; populated per stage).
- `backend/app/adapters/embeddings/client.py` — `EmbeddingsClient` with `embed(texts) -> list[vector]`; provider behind an interface.
- `backend/app/adapters/sources/base.py` — `SourceAdapter` ABC: `search(query, filters) -> list[SourceHit]`, `fetch(id) -> SourceRecord`, `references(id)`, `citations(id)`. Concrete adapters land in Phase 2; create the ABC and the `SourceHit`/`SourceRecord` dataclasses now.
- `backend/app/adapters/export/base.py` — `Exporter` ABC (`render(content) -> bytes`); concrete docx/pptx in Phase 5.

### Events, audit, provenance services
- `backend/app/events/types.py` — event envelope + event type literals (overview §6).
- `backend/app/events/bus.py` — `EventBus` over Redis pub/sub: `publish(event)`, `subscribe(project_id)`. In-memory fallback for tests.
- `backend/app/services/audit.py` — `AuditService.record(project_id, action_type, description, reasoning, payload, run_id=None, stage=None)`; writes a row and (where applicable) publishes a matching event. This is the single entry point for audit writes.
- `backend/app/services/provenance.py` — `ProvenanceService.attach(claim_text, context, ref_id, source_id=None, passage=None, is_inference=False, confidence_label=None)` and `trace(ref_id) -> list[Provenance]`. Enforces the rule: either `source_id+passage` is set or `is_inference=True`.
- `backend/app/services/projects.py` — CRUD for projects (create draft, get, list, update status/stage, archive).

### API skeleton
- `backend/app/api/projects.py` — REST: `POST /projects` (create draft), `GET /projects`, `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}` (archive).
- `backend/app/api/audit.py` — `GET /projects/{id}/audit` (paginated).
- `backend/app/api/health.py` — `GET /health` (checks DB + Redis).
- `backend/app/api/ws.py` — `GET /ws/projects/{id}` WebSocket that relays EventBus events for the project. (No producers yet; verify it connects and echoes a test event.)

### Dev infra
- `docker-compose.yml` — Postgres+pgvector, Redis, backend.
- `backend/scripts/seed.py` — insert one sample draft project for manual testing.
- `Makefile` / task scripts: `migrate`, `run`, `test`, `lint`.

---

## Implementation notes

- Make the LLM wrapper's token-accounting hook a simple callback `on_usage(input_tokens, output_tokens, model)` injected by the orchestrator later; in Phase 0 it can log only.
- `complete_json` must: instruct the model to return only JSON, strip code fences, validate against the provided Pydantic schema, and on failure do exactly one repair call ("your previous output failed validation: {error}; return valid JSON only"). Raise `LLMError` if it still fails.
- Models should use proper FK constraints and indexes on `project_id`, `source_id`, and `audit_log.timestamp`.
- Keep `embedding` nullable (populated in Phase 2/3).

---

## Acceptance criteria (Definition of Done)

1. `docker-compose up` brings up Postgres (with pgvector enabled), Redis, and the API.
2. `make migrate` applies the initial migration; `downgrade` reverses it cleanly.
3. `GET /health` returns OK with DB + Redis connectivity confirmed.
4. CRUD on `/projects` works end-to-end; creating a project writes an `audit_log` row via `AuditService`.
5. A unit test calls the `LLMClient` wrapper against a mocked SDK and verifies: retry on transient error, JSON parse + schema validation, and one repair retry on invalid JSON.
6. `ProvenanceService.attach` rejects a claim that has neither a source passage nor `is_inference=True`.
7. The WebSocket endpoint accepts a connection and delivers a manually published test event.
8. `ruff`, `black --check`, and `mypy` pass on `core/`, `services/`, `adapters/`; `pytest` is green.

## Manual demo
Create a project via `POST /projects`, open the WS for it, publish a test event with a script, see it arrive, then fetch `/projects/{id}/audit` and see the creation entry.
