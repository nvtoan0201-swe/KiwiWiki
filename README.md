# Autonomous Research Agent

An agent that turns a research question into a literature review, comparative
analysis, report, and presentation — pausing to ask a human at the right
moments. See [AGENT_DESIGN.MD](AGENT_DESIGN.MD) (screens) and
[RESEARCH_WORKFLOW.md](RESEARCH_WORKFLOW.md) (behavior).

## Status

All build phases (0–7) are complete: the full pipeline — scoping →
literature search → paper analysis → comparative analysis → gap analysis →
report → presentation — runs end to end with provenance, budgets,
escalations, per-run tracing, an eval scorecard, and deployment artifacts.

**Operations:** see [RUNBOOK.md](RUNBOOK.md) for clean-checkout setup, env
vars, staging deploys (`docker-compose.prod.yml`), the post-deploy smoke test,
how to read the audit log / run trace, threshold tuning, and on-call notes.

## Stack

- **Backend** — Python, FastAPI, Anthropic SDK (`claude-opus-4-8`, adaptive
  thinking, structured output via `messages.parse`).
- **Frontend** — React + Vite + TypeScript.

## Running it

You need an Anthropic API key.

### Backend

```bash
cd backend
cp .env.example .env          # then put your real ANTHROPIC_API_KEY in .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload   # serves on http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                   # serves on http://localhost:5173
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

## Layout

```
backend/app/
  agent/        LLM wrapper + per-stage logic (scoping.py = Stage 0)
  routers/      HTTP endpoints
  schemas.py    Pydantic models (also the structured-output schema)
  store.py      in-memory project store (swap for a DB later)
frontend/src/
  api/client.ts API types + fetch helpers
  pages/        NewResearch (screen 3), ScopeConfirmation (screen 4)
```
