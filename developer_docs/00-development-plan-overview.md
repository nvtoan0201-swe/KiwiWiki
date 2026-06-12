# Autonomous Research Agent — Development Plan (Overview)

This is the master plan. It defines the technology stack, conventions, the shared data model, and the phase breakdown. Each phase has its own detailed spec file (`phase-N-*.md`) intended to be handed to a coding agent as a self-contained unit of work.

**How to use this set:** Build phases in order. Each phase file lists its prerequisites, the exact modules/files to create, data-model additions, API/event contracts, and a Definition of Done with testable acceptance criteria. Do not start a phase until its prerequisites' acceptance criteria pass.

---

## 1. Product summary (for context)

An autonomous agent that takes a research question and produces a literature review, comparative analysis, gap analysis, a written report, and a presentation. It runs autonomously through a looping workflow but pauses to ask the user at defined escalation points. Every claim it produces is traceable to a source. See the behavioral plan and the screen-design spec (companion documents) for the *why*; this set covers the *how*.

Workflow stages: `scoping → literature_search → paper_analysis → comparative_analysis → gap_analysis → report_writing → presentation_generation`, with loop-backs and human escalations.

---

## 2. Recommended stack

These are defaults chosen to fit the workload. A coding agent may substitute equivalents but must keep the contracts (data model, API shapes, events) stable across phases.

**Backend**
- Python 3.11+
- FastAPI (HTTP API + WebSocket/SSE for live events)
- SQLAlchemy 2.0 (ORM) + Alembic (migrations)
- PostgreSQL 15 with the `pgvector` extension (relational state + embeddings for saturation/clustering)
- Redis (cache, pub/sub for live events, task broker)
- A background task runner for long autonomous runs: **arq** or **Celery** (arq recommended for async simplicity)
- Pydantic v2 for all schemas/validation

**LLM & embeddings**
- Anthropic Claude via the official `anthropic` Python SDK for all reasoning/extraction/writing
- An embeddings model for similarity (saturation detection, clustering, dedup) — provider-agnostic behind an interface

**External literature sources** (all behind a common adapter interface)
- OpenAlex, arXiv, Semantic Scholar, Crossref

**Document/Presentation generation**
- `python-docx` (report → .docx), `python-pptx` (presentation → .pptx); Markdown as the canonical intermediate

**Frontend**
- React 18 + TypeScript + Vite
- TanStack Query (server state), a lightweight client-state store (Zustand)
- WebSocket client for the live Activity Monitor
- A component library is optional; styling approach is left to the frontend phase

**Tooling**
- Tests: `pytest` (backend), `vitest` + React Testing Library (frontend)
- Lint/format: `ruff` + `black` (backend), `eslint` + `prettier` (frontend)
- Typing: `mypy` (backend, strict on core modules)

---

## 3. Repository layout

```
research-agent/
  backend/
    app/
      core/            # config, logging, errors, constants/enums
      db/              # SQLAlchemy models, session, migrations (alembic/)
      schemas/         # Pydantic request/response/event schemas
      orchestrator/    # state machine, stage runner, budget, escalation, audit
      stages/          # one module per workflow stage
        scoping/
        search/
        analysis/
        comparison/
        gap/
        report/
        presentation/
      adapters/
        llm/           # Claude client wrapper + prompt templates
        embeddings/
        sources/       # OpenAlex, arXiv, S2, Crossref adapters
        export/        # docx, pptx writers
      api/             # FastAPI routers (REST + WS)
      events/          # event bus, pub/sub, event types
      services/        # cross-cutting services (provenance, project mgmt)
    tests/
  frontend/
    src/
      api/             # generated/typed client, query hooks
      screens/         # one folder per screen (see screen-design spec)
      components/
      store/
      ws/              # websocket client + event handlers
    tests/
  docs/                # the three planning documents live here
```

---

## 4. Shared conventions (apply to every phase)

- **Enums** (define once in `core/constants.py`, mirror in frontend `api/types.ts`):
  - `ProjectStatus`: `draft, scoping, awaiting_input, running, paused, complete, failed`
  - `Stage`: `scoping, literature_search, paper_analysis, comparative_analysis, gap_analysis, report_writing, presentation_generation`
  - `ConfidenceLabel`: `well_established, emerging, contested, speculative`
  - `TriageStatus`: `deep_read, skimmed, set_aside, excluded`
  - `DiscoveryChannel`: `keyword_search, citation_snowball, user_supplied`
  - `EscalationStatus`: `open, resolved, auto_resolved`
  - `AuditActionType`: `stage_start, stage_complete, search_run, query_reformulated, paper_triaged, paper_analyzed, loop_back, escalation_raised, escalation_resolved, budget_warning, stopped, error`
- **Every state-changing operation writes an AuditLogEntry** with a human-readable `description` and a `reasoning` field. This is non-negotiable — auditability is a core product requirement, not an add-on.
- **Provenance is mandatory.** Any agent-produced claim that ends up in an output must carry a `Provenance` link (to a source passage) or be explicitly marked `is_inference = true`. Writing code that emits an unsourced, un-flagged claim is a bug.
- **LLM calls go through the `adapters/llm` wrapper only** — never call the SDK directly from stage code. The wrapper handles retries, token accounting (feeds the budget ledger), structured-output parsing, and prompt versioning.
- **Budget accounting is centralized** in the orchestrator. Stages request budget and report consumption; they never decide unilaterally to keep going past a ceiling.
- **All long-running work is resumable.** State lives in the DB, not in memory. A run can be killed and resumed from the last completed step.
- **IDs** are UUIDs (string) everywhere. Timestamps are UTC ISO-8601.
- **Errors**: typed exceptions in `core/errors.py`; API returns a consistent error envelope `{error: {code, message, details}}`.

---

## 5. Shared data model (created in Phase 0, extended later)

Tables and key fields. Phase files specify which tables they add/extend. (`jsonb` columns noted; FKs implied by `_id`.)

- **projects**: `id, title, original_request, research_question, scope(jsonb), audience, outputs_requested(jsonb), budget(jsonb), status, current_stage, created_at, updated_at`
- **runs**: `id, project_id, status, started_at, ended_at, stopping_criterion(enum: saturation|coverage|stable_map|budget|user_stopped|error), budget_consumed(jsonb)`
- **stage_executions**: `id, run_id, stage, status, started_at, ended_at, summary(jsonb), loop_back_from(nullable stage)`
- **sources**: `id, project_id, title, authors(jsonb), venue, year, doi, url, abstract, discovery_channel, relevance_score(float), credibility_score(float), triage_status, triage_reason, cluster_id(nullable), raw_metadata(jsonb), embedding(vector)`
- **paper_analyses**: `id, source_id, core_claim, method, results(jsonb), datasets(jsonb), author_limitations(jsonb), agent_critique, credibility_breakdown(jsonb), confidence_label, created_at`
- **provenance**: `id, project_id, claim_text, source_id(nullable), passage, is_inference(bool), confidence_label, context(enum: analysis|comparison|gap|report|presentation), ref_id(the output entity it supports)`
- **contradictions**: `id, project_id, source_a_id, source_b_id, description, investigation(nullable), resolution(nullable), resolved(bool)`
- **clusters**: `id, project_id, label, description, defining_characteristics(jsonb)`
- **comparisons**: `id, project_id, dimensions(jsonb), matrix(jsonb), consensus_points(jsonb), contested_points(jsonb)`
- **gaps**: `id, project_id, description, supporting_evidence(jsonb), importance(enum: high|medium|low), confidence_label`
- **reports**: `id, project_id, audience, content_markdown, self_check_result(jsonb), stopping_criterion, version, created_at`
- **presentations**: `id, project_id, through_line, key_messages(jsonb), slides(jsonb), speaker_notes(jsonb), version, created_at`
- **escalations**: `id, project_id, run_id, trigger(enum: ambiguous_scope|thin_literature|unresolved_contradiction|high_stakes), question, context(jsonb), options(jsonb), status, user_response(jsonb,nullable), created_at, resolved_at`
- **audit_log**: `id, project_id, run_id(nullable), timestamp, action_type, stage(nullable), description, reasoning, payload(jsonb)`
- **budget_ledger**: `id, run_id, timestamp, category(enum: llm_tokens|search_calls|papers_read|time), amount, running_total, note`

---

## 6. Cross-phase event contract (live updates)

The Activity Monitor and Notifications depend on a stable event stream. Events are published to Redis and relayed over WebSocket. Define in `events/types.py` in Phase 1; consumed by frontend in Phase 6.

Event envelope: `{ id, project_id, run_id, type, stage, timestamp, payload }`

Event types: `stage_changed, activity (human-readable line), counter_update (papers_found/triaged/read, searches, budget), loop_back, saturation_update, escalation_raised, escalation_resolved, output_ready (report|presentation), run_finished, error`.

Every event also corresponds to an audit_log entry where applicable; the event stream is the live view, the audit log is the durable record.

---

## 7. Phase breakdown

| Phase | Title | Produces | Depends on | Difficulty |
|---|---|---|---|---|
| 0 | Foundation & Scaffolding | repo, config, DB + models, migrations, API skeleton, LLM/embeddings adapters, event bus, audit + provenance services | — | MEDIUM |
| 1 | Orchestration Engine | state machine, stage runner, budget ledger, escalation mechanism, run lifecycle, resumability | 0 | HARD |
| 2 | Literature Search | source adapters, iterative search, query reformulation, triage, snowballing, saturation detection | 0,1 | VERY HARD |
| 3 | Paper Analysis | fetch + tiered reading, structured extraction, credibility scoring, contradiction flagging, provenance capture | 0,1,2 | HARD |
| 4 | Comparative & Gap Analysis | clustering, comparison matrix, consensus/contested, gap synthesis | 0,1,3 | VERY HARD |
| 5 | Report & Presentation | report writer + self-check, presentation distillation, docx/pptx export | 0,1,4 | HARD |
| 6 | Frontend | all 16 screens, live monitor, escalation flow, output viewers | 0–5 (against contracts) | HARD |
| 7 | Integration & Hardening | end-to-end wiring, eval harness, observability, deployment | 0–6 | HARD |

Phase 6 can begin against the API/event contracts as soon as those are frozen (end of Phase 1 for shell screens; per-stage screens follow their backend phase).

### Difficulty ratings — rationale

Difficulty reflects conceptual hardness and correctness risk, not just line count.

- **Phase 0 — MEDIUM.** Large surface area (full schema, adapters, services, API skeleton) but well-trodden patterns; mostly boilerplate with no fuzzy logic. The only subtlety is the `complete_json` repair loop and getting migrations reversible.
- **Phase 1 — HARD.** A resumable state machine with loop-backs, bounded loop-back caps, escalation pause/resume, and centralized budget accounting that must survive process kills. Correctness-critical and concurrency-sensitive; bugs here corrupt every downstream phase.
- **Phase 2 — VERY HARD.** Four live external APIs with rate limits and dedup, an iterative search loop, query reformulation, echo-chamber detection, and **idea-saturation detection** (embedding novelty + LLM judgment) — an open-ended, tunable heuristic with no obviously correct answer. Most behavior is fuzzy and hard to test deterministically.
- **Phase 3 — HARD.** Tiered reading, structured extraction, and method-based credibility scoring are tractable, but mandatory per-claim provenance, contradiction detection across pairs, loop-back triggers, and bounded-concurrency resumability without double-charging budget add real correctness risk.
- **Phase 4 — VERY HARD.** The most reasoning-heavy phase: data-driven clustering and comparison dimensions (no templates), investigating *why* sources disagree before resolving, and refusing to invent consensus. Quality is subjective and hard to verify; "it depends" must survive instead of being flattened to a ranking.
- **Phase 5 — HARD.** Audience-pitched writing and presentation distillation are LLM-heavy, and the **self-check that can block completion** plus deterministic citation-marker → provenance mapping and clean docx/pptx export carry real correctness and formatting risk.
- **Phase 6 — HARD.** Not conceptually deep but very broad: 16 screens, live WebSocket state with reconnect/polling fallback, provenance overlays reachable everywhere, and the escalation/awaiting-input flow that must be impossible to miss. Difficulty is volume + live-state integration.
- **Phase 7 — HARD.** End-to-end wiring is straightforward, but the **eval harness** (groundedness as a 100% invariant, confidence calibration, escalation precision/recall) and fault-injection resilience under mid-stage kills require measuring trust properties, not just asserting them.

---

## 8. Global Definition of Done

A phase is complete only when: its acceptance criteria pass; new code has unit tests and the critical paths have integration tests; migrations run cleanly up and down; lin/type checks pass; every new state-changing path writes audit entries; and any new agent-produced claims carry provenance. Manual demo steps in each phase file must be reproducible from a clean checkout.
