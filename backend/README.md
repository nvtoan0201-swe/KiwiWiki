# Research Agent — Backend (Phase 0)

The foundation: project structure, config, the full shared database schema with
migrations, the LLM/embeddings/source/export adapter contracts, the event bus,
and the audit + provenance services. No agent behavior yet — "the lights turn on
and the contracts exist."

## Layout

```
app/
  core/         config, logging, errors, constants/enums
  db/           SQLAlchemy base + models (one per shared table), session
  schemas/      Pydantic request/response schemas (the API contract)
  adapters/     llm/ embeddings/ sources/ export/  (interfaces + minimal impls)
  events/       event envelope + bus (Redis pub/sub, in-memory fallback)
  services/     audit, provenance, projects
  api/          FastAPI routers: health, projects, audit, ws
  main.py       app factory
alembic/        async migrations (initial schema enables pgvector)
scripts/seed.py one sample draft project
tests/          pytest suite (runs on SQLite + in-memory bus, no infra needed)
```

## Run the stack (Docker)

From the repo root:

```bash
docker compose up        # Postgres+pgvector, Redis, and the API (runs migrations on start)
curl localhost:8000/health
```

## Run locally (without Docker)

Point `DATABASE_URL`/`REDIS_URL` at running services, then:

```bash
make install     # pip install -e ".[dev]"
make migrate     # alembic upgrade head
make run         # uvicorn app.main:app --reload
make seed        # insert a sample draft project
```

## Quality gate (Phase 0 Definition of Done)

```bash
make check       # ruff + black --check, mypy, pytest
make migrate && make downgrade   # migration applies and reverses cleanly
```

Tests run against in-memory SQLite and the in-memory event bus, so `make test`
needs no Postgres or Redis.

## Manual demo

1. `docker compose up`
2. `curl -X POST localhost:8000/projects -H 'Content-Type: application/json' -d '{"original_request":"Survey RAG methods"}'`
   → returns a project; note its `id`.
3. Open the WS: `websocat ws://localhost:8000/ws/projects/<id>` (or any WS client).
4. Publish a test event for that project (e.g. via a small script using
   `app.events.bus.get_event_bus().publish(...)`) and watch it arrive on the WS.
5. `curl localhost:8000/projects/<id>/audit` → see the project-creation entry.
