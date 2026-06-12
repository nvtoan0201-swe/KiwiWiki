# Phase 1 — Orchestration Engine

**Goal:** The brain that runs the workflow. A resumable state machine that advances a project through stages, enforces the budget, raises and resolves human escalations, supports loop-backs, and emits live events — all without yet knowing how any individual stage does its work. Stages are registered against this engine and called through a uniform interface.

**Prerequisites:** Phase 0 acceptance criteria pass.

---

## Core concepts

- A **Run** is one autonomous execution of a project. A project may have multiple runs (e.g., resume, re-run from a point).
- The engine advances through **Stages** by calling a registered **StageHandler** for the current stage. Each handler returns a typed **StageResult**.
- A `StageResult` tells the engine what to do next: `advance`, `loop_back(to_stage, reason)`, `escalate(escalation)`, `complete`, or `fail(error)`.
- All progress is persisted (`runs`, `stage_executions`) so a killed run resumes from the last completed stage.

---

## Deliverables (files/modules)

### Stage handler contract
- `backend/app/orchestrator/handler.py`
  - `class StageContext` — passed to every handler: `project`, `run`, `budget` (a `BudgetGuard`), `audit` (AuditService bound to project/run), `events` (publisher), `llm`, `embeddings`, `db session`, and accessors for prior-stage outputs.
  - `class StageResult` — discriminated union: `Advance`, `LoopBack(to_stage, reason)`, `Escalate(trigger, question, context, options)`, `Complete`, `Fail(error)`.
  - `class StageHandler(ABC)` — `stage: Stage`; `async run(ctx: StageContext) -> StageResult`. Handlers must be idempotent enough to be re-entered after resume (check for already-produced outputs before redoing work).

### State machine
- `backend/app/orchestrator/state_machine.py`
  - The legal transition table between stages (forward order) plus permitted loop-back targets (e.g., `paper_analysis → literature_search`, `comparative_analysis → paper_analysis|literature_search`, `report_writing → comparative_analysis`).
  - `next_stage(current)` and `can_loop_back(from, to)` guards.
- `backend/app/orchestrator/runner.py`
  - `class RunEngine` with `start(project_id) -> run_id`, `resume(run_id)`, `pause(run_id)`, `stop(run_id, reason)`.
  - Main loop: load current stage → create/find `stage_execution` → call handler → interpret `StageResult`:
    - `Advance`: mark stage complete, move to `next_stage`, emit `stage_changed`.
    - `LoopBack`: record loop-back on the target `stage_execution` (`loop_back_from`), write audit `loop_back` with reason, emit `loop_back`, set current stage to target.
    - `Escalate`: persist `escalation` (status `open`), set project `awaiting_input`, pause the run, emit `escalation_raised`, exit loop until resolved.
    - `Complete`: set run `complete` with stopping_criterion, project `complete`, emit `run_finished`.
    - `Fail`: set run/project `failed`, emit `error`.
  - Runs inside the background task runner (arq/celery); the engine itself is transport-agnostic so it can also be driven synchronously in tests.

### Budget
- `backend/app/orchestrator/budget.py`
  - `class BudgetGuard` constructed from the project's `budget` (ceilings for llm_tokens, search_calls, papers_read, wall-clock). Methods: `charge(category, amount, note)` → writes `budget_ledger`, updates running totals, emits `counter_update`; `remaining(category)`; `check(category, needed) -> bool`; `would_exceed(category, needed)`.
  - At ~80% of any ceiling, emit `budget_warning` and audit it.
  - Wire the LLM wrapper's `on_usage` callback to `charge('llm_tokens', ...)`.
  - When a ceiling is hit, raise `BudgetExceeded`; the runner converts that into a graceful stop with `stopping_criterion = budget` (produces outputs from whatever exists — not a hard crash).

### Escalation
- `backend/app/orchestrator/escalation.py`
  - `raise_escalation(ctx, trigger, question, context, options)` — persists the escalation, returns the `Escalate` result.
  - `resolve_escalation(escalation_id, user_response)` — validates the response against `options`, stores it, sets status `resolved`, audits `escalation_resolved`, emits event, and **re-queues the run to resume** at the stage that raised it (passing the response into `StageContext` so the handler can act on it).
  - `escalation_sensitivity` setting (from project/settings) modulates whether borderline triggers escalate or proceed-with-noted-assumption.

### Run lifecycle API
- `backend/app/api/runs.py`
  - `POST /projects/{id}/runs` — start a run (returns run id; kicks off background execution).
  - `GET /projects/{id}/runs` and `GET /runs/{run_id}` — status, current stage, budget consumed, stopping criterion.
  - `POST /runs/{run_id}/pause`, `POST /runs/{run_id}/resume`, `POST /runs/{run_id}/stop`.
  - `GET /projects/{id}/escalations?status=open` and `POST /escalations/{id}/resolve` (body = user_response).
  - `POST /runs/{run_id}/budget` — adjust ceilings mid-run.

### Stage registry + test stubs
- `backend/app/orchestrator/registry.py` — register `StageHandler`s by `Stage`. Unknown/unregistered stage → controlled failure.
- `backend/app/stages/_stubs.py` — temporary trivial handlers for every stage (each just audits, emits an activity line, and returns `Advance`) so the full pipeline runs end-to-end before real stages exist. Include one stub variant that returns `Escalate` and one that returns `LoopBack`, toggleable, for testing those paths.

---

## Implementation notes

- The engine must treat handler re-entry as normal: on resume, a handler should detect its own prior partial output and continue, not duplicate. Provide a helper `ctx.get_stage_output(stage)` and encourage handlers to checkpoint.
- Persist enough in `stage_executions.summary` that the Activity Monitor and Audit Log can reconstruct what happened without re-running.
- Loop-back must be bounded: track loop-back count per (from,to) pair in the run; if it exceeds a configurable max (default 3), escalate (`high_stakes`/"agent is stuck") instead of looping again. This prevents infinite loops.
- All transitions, loop-backs, escalations, budget warnings, and stops write audit entries and emit events.

---

## Acceptance criteria (Definition of Done)

1. With only the stub handlers registered, `POST /projects/{id}/runs` drives a project from `scoping` through `presentation_generation` to `complete`, writing `stage_execution` rows and emitting `stage_changed` events for each.
2. The loop-back stub causes a recorded loop-back (audit + event + `loop_back_from` set) and the run continues correctly afterward.
3. The escalation stub pauses the run, creates an `open` escalation, and sets project `awaiting_input`; calling `POST /escalations/{id}/resolve` resumes the run from the raising stage with the response available in context.
4. Killing the process mid-run and calling `resume` continues from the last completed stage without re-doing completed stages.
5. Setting a tiny `llm_tokens` ceiling and having a stub "spend" tokens triggers a `budget_warning` at 80% and a graceful stop with `stopping_criterion = budget` at 100% (no crash; run ends `complete`-with-budget-stop or `stopped`).
6. The loop-back cap converts the 4th identical loop-back into an escalation.
7. Unit tests cover the state-machine transition table and each `StageResult` branch; an integration test drives the full stub pipeline.

## Manual demo
Start a run with stubs; watch `stage_changed` events arrive over the WS in order; trigger the escalation stub, resolve it via the API, and watch the run finish.
