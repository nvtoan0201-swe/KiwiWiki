# Runbook — Autonomous Research Agent

Operational guide: clean-checkout setup, deployment, running a project,
reading the audit trail, tuning, and on-call notes. (Phase 7 part E.)

---

## 1. Setup from a clean checkout

### Local development

```bash
git clone <repo> && cd KiwiWiki

# Backend
cd backend
python3.11 -m venv .venv
make install                       # pip install -e ".[dev]"
cp .env.example .env 2>/dev/null || true   # or create .env (see §2)
docker compose up -d db redis      # from repo root: Postgres+pgvector, Redis
make migrate                       # alembic upgrade head
make run                           # uvicorn app.main:app --reload  → :8000

# Frontend
cd ../frontend
npm install
npm run dev                        # Vite on :5173, /api proxied to :8000
```

Verification gates (all must pass before merging):

```bash
cd backend
make check     # ruff + black + mypy + pytest (includes the e2e suite)
make eval      # eval scorecard — deterministic quality gates, exits 1 on regression
cd ../frontend
npm run lint && npm run test && npm run build
```

The whole test suite runs against in-memory SQLite and fakes: no Postgres,
Redis, network, or API key needed.

### Staging / production

```bash
# Managed Postgres(+pgvector) and Redis: set DATABASE_URL / REDIS_URL in env.
export ANTHROPIC_API_KEY=...       # from your secret store — never committed
docker compose -f docker-compose.prod.yml up -d --build

# Staging without managed infra (bundled Postgres + Redis):
docker compose -f docker-compose.prod.yml --profile bundled up -d --build
```

Migrations run automatically on deploy (`migrate` service); the API starts
only after they succeed, and its `/health` healthcheck gates readiness.

Post-deploy smoke test (runs one tiny real project end to end):

```bash
cd backend
API_URL=http://localhost:8000 make smoke    # python -m scripts.smoke_test
```

It health-checks, creates a small-budget project, runs it (auto-resolving any
escalation with the first offered option), then verifies the audit log, the
run trace, the report, and the export bundle. Exit code 0 = pass.

---

## 2. Environment variables

All config is env-driven (`backend/app/core/config.py`); nothing secret goes
in code, URLs, or logs.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | local Postgres | `postgresql+asyncpg://…` (needs pgvector) |
| `REDIS_URL` | local Redis | event bus for the live monitor |
| `ANTHROPIC_API_KEY` | — | required for real runs (tests/eval use fakes) |
| `AGENT_MODEL` | `claude-opus-4-8` | model used by the LLM wrapper |
| `OPENALEX_MAILTO`, `CROSSREF_MAILTO` | empty | polite-pool contact (not secret) |
| `SEMANTIC_SCHOLAR_API_KEY` | empty | sent as a header, never in URLs |
| `DEFAULT_BUDGET_*` | 2M tokens / 500 searches / 100 papers / 3600 s | per-project ceilings when a project sets none |
| `GLOBAL_LLM_TOKEN_CEILING` | 50,000,000 | **hard system-wide token stop across all runs**; 0 disables |
| `MAX_CONCURRENT_RUNS` | 3 | runs executing at once; extra launches queue |
| `LLM_MAX_CONCURRENT` | 4 | in-flight Anthropic calls, process-wide |
| `ESCALATION_SENSITIVITY` | `medium` | low / medium / high — how readily the agent asks |
| `LOG_LEVEL` | `INFO` | JSON logs on stdout |

---

## 3. Running a project

Via the UI: New Research → describe the request → confirm scope → watch the
Activity Monitor. Via the API:

```bash
curl -X POST :8000/projects -H 'content-type: application/json' \
  -d '{"original_request": "Do transformers beat RNNs for time-series forecasting?",
       "budget": {"llm_tokens": 500000, "papers_read": 30}}'
curl -X POST :8000/projects/<id>/runs            # → {"run_id": ...}
curl :8000/runs/<run_id>                         # status / stopping_criterion
```

- **Escalations**: when status is `paused` and the project is
  `awaiting_input`, list `GET /projects/<id>/escalations?status=open` and
  answer with `POST /escalations/<id>/resolve {"user_response": {...}}`
  (`{"selected_option": "..."}` for flat options, `{"resolutions": {amb_id:
  option_id}}` for scope ambiguities). Resolving re-queues the run.
- **Pause / resume / stop**: `POST /runs/<id>/pause|resume|stop`. Stops are
  graceful; resume never redoes completed work (state is in the DB).
- **Budget mid-run**: `POST /runs/<id>/budget {"llm_tokens": 800000}` —
  ceilings re-read at the next stage step.
- **Outputs**: `GET /projects/<id>/reports`, `/presentations…`, and
  `GET /projects/<id>/export` for the full zip bundle (report + deck +
  sources + audit log).

---

## 4. Reading the audit log and the run trace

**Audit log** (`GET /projects/<id>/audit`, or the Audit Log screen) is the
durable decision record: every state change has a human-readable
`description` *and* a `reasoning`. Useful filters: `action_type=`
`escalation_raised`, `loop_back`, `budget_warning`, `error`,
`self_check_completed`. If you wonder "why did the agent do X", the answer is
in `reasoning` — e.g. why queries were reformulated, why a paper was triaged
out, why a consensus label was downgraded.

**Run trace** (`GET /runs/<id>/trace`, internal/debugging) threads the whole
run: per-stage spans (status, duration, loop-back origin), every LLM call
(model, prompt version, exact input/output tokens, duration, errors), every
source call (adapter + operation), and rolled-up metrics (tokens by stage,
calls by prompt version, papers read, escalation/loop-back/error counts,
budget snapshot). First stop when debugging cost or latency.

---

## 5. Tuning thresholds

All in `app/core/config.py`, overridable by env (upper-cased name):

- **Asking too often / too rarely** → `ESCALATION_SENSITIVITY` (low: only
  clearly material forks escalate; high: every ambiguity does).
- **Search stops too early / never** → `SATURATION_NOVELTY_FLOOR` (default
  0.2), `SATURATION_CONSECUTIVE_ITERATIONS` (2), `SEARCH_ITERATION_CAP` (5).
- **Too much junk triaged in / good papers dropped** →
  `RELEVANCE_DEEP_READ_THRESHOLD` (0.7), `RELEVANCE_SKIM_THRESHOLD` (0.4).
- **Loop-back storms** → `LOOP_BACK_MAX` (3; beyond it the agent escalates).
- **Consensus labels too confident** → `CONSENSUS_CREDIBILITY_FLOOR` (0.6 —
  below this mean credibility, `well_established` is capped to `emerging`).
- **Spend** → per-project `DEFAULT_BUDGET_*`; system-wide
  `GLOBAL_LLM_TOKEN_CEILING`; concurrency `MAX_CONCURRENT_RUNS`,
  `LLM_MAX_CONCURRENT`.

After tuning, re-run `make eval` — the scorecard (groundedness, calibration,
escalation precision/recall, saturation, self-check, budget adherence) is the
regression net for exactly these behaviors.

---

## 6. On-call notes — common failure modes

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Run `failed`, criterion `error` | LLM persistently failing (auth, model id) or a handler bug | `GET /runs/<id>/trace` → look for `error` on llm_calls; fix the cause, then **start a new run on the same project** — it resumes from checkpointed work, nothing is redone |
| Run `paused` + "All literature sources are currently unreachable" | every source adapter down (network egress, provider outage) | check provider status; resolve the escalation with `retry` once reachable, or `stop` |
| Audit shows `Source adapter outage: <name>` but run continued | single-provider outage | informational — search continued on the others; verify coverage note in the report |
| Run `stopped`, criterion `budget` | a per-project ceiling or the global ceiling hit | this is graceful by design; outputs exist for completed work. Raise the budget (`POST /runs/<id>/budget`) and start a new run, or accept the partial result. Audit `budget_warning` with `scope: global` means the *system* ceiling — raise `GLOBAL_LLM_TOKEN_CEILING` deliberately |
| Runs sit in `running` but nothing happens | queued behind `MAX_CONCURRENT_RUNS`, or the API process restarted mid-run | trace shows no new events: if queued, wait or raise the cap; if the process restarted, `POST /runs/<id>/resume` — resume is safe and idempotent |
| Token spend spiking | runaway loop-back or oversized corpus | trace metrics → `llm_tokens_by_stage` + audit `loop_back` entries; lower budgets, check `LOOP_BACK_MAX` |
| WebSocket monitor silent but run progresses | Redis down (events are best-effort; audit log is the durable record) | restore Redis; nothing is lost — replay from the audit log |
| `/health` degraded | `db` / `redis` flag false | check managed-service connectivity; the API serves but runs should not be started until healthy |

**Process kills are safe.** Every stage step commits before the next begins,
and handlers checkpoint mid-stage; killing a worker mid-run and resuming is a
tested path (`backend/tests/e2e/test_resume_after_kill.py`,
`test_fault_injection.py`).

**Known limitation — single-process worker.** Runs execute as in-process
background tasks inside the API process (one uvicorn worker; see
`docker-compose.prod.yml`). The seam for a separate scaled worker is
`RunEngine.launch` (`backend/app/orchestrator/runner.py`) — an external queue
(arq) can replace it without touching stage logic. Until then: scale
vertically, bound load with `MAX_CONCURRENT_RUNS`, and rely on resume-safety
across restarts.
