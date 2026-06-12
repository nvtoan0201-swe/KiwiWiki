# Phase 7 — Integration, Evaluation & Hardening

**Goal:** Make it a real system: wired end to end, observable, evaluated for quality (not just "it runs"), resilient to the failure modes a long autonomous run hits, and deployable. This phase is where the trust properties (groundedness, calibrated confidence, right-moment escalation) get *measured*, not just asserted.

**Prerequisites:** Phases 0–6 pass.

---

## Part A — End-to-end integration

- `backend/tests/e2e/` — full-pipeline tests against fake source adapters and a mocked/recorded LLM: scoping → search → analysis → comparison → gap → report → presentation, including one run that loops back and one that escalates and is resolved.
- Verify cross-stage contracts hold: provenance survives from extraction into the report; confidence labels propagate; the stopping criterion recorded by the engine matches what the report states.
- A "resume" e2e: kill mid-analysis, resume, confirm identical final outputs (modulo nondeterminism) without duplicated work.

## Part B — Evaluation harness

`backend/eval/` — quality gates, runnable in CI (LLM-gated tests skippable):
- **Groundedness check** — sample claims from generated reports; verify each has resolvable provenance or an inference flag; fail if any unsourced/un-flagged claim appears. Target: 100% (this is a correctness invariant, not a metric to optimize).
- **Confidence calibration** — on a labeled fixture set where ground-truth strength is known, check the agent's labels track strength (e.g., weak-evidence fixtures don't get `well_established`).
- **Escalation precision/recall** — a fixture suite of ambiguous/thin/contradictory/high-stakes cases vs. clear cases; measure that the agent escalates on the former and *not* on the latter (asking rarely but correctly). Report both false-escalations and missed-escalations.
- **Saturation sanity** — saturating fixtures stop; diverse fixtures keep going to the cap.
- **Self-check efficacy** — inject unsupported claims into drafts; measure catch rate.
- **Budget adherence** — runs never exceed ceilings; budget stops are graceful.
- Produce a scorecard artifact per run; wire thresholds as CI gates where deterministic.

## Part C — Observability

- Structured logs already in place; add **per-run tracing**: a trace id threading stage executions, LLM calls (with token + prompt-version tags), and source calls.
- Metrics: run duration per stage, tokens per stage, papers/run, escalation rate, loop-back rate, budget-stop rate, error rate by source adapter.
- A lightweight internal `GET /runs/{id}/trace` for debugging; optional OpenTelemetry export.
- Dashboards/alerts (if infra allows): error spikes, source-adapter outages, runaway token spend.

## Part D — Resilience & hardening

- **LLM failures:** retries/backoff in the wrapper (Phase 0) exercised under fault injection; a persistent failure fails the stage cleanly with a resumable checkpoint, not a corrupt state.
- **Source outages:** one adapter down → search continues on others, audited; all down → escalate or stop gracefully.
- **Idempotency/resumability** verified under process kills at each stage boundary and mid-stage.
- **Rate limiting & backpressure:** bound concurrency on LLM and source calls; queue runs so one project can't starve others.
- **Input safety:** scope/request inputs sanitized; uploaded seed files size/type-checked; treat all source/web content as data, never as instructions to the agent (no acting on text found inside fetched papers).
- **Privacy/permissions:** no credentials or sensitive data in URLs/logs; respect access controls when fetching papers (open-access/abstract only; never bypass paywalls or CAPTCHAs).
- **Data lifecycle:** project archive/delete cascades correctly; export bundles (report + deck + source list + audit log) generate.
- **Cost guardrails:** hard global spend ceiling independent of per-project budgets.

## Part E — Deployment

- Production `docker-compose` / container manifests; managed Postgres+pgvector and Redis; secrets via env/secret store (never committed).
- DB migrations run on deploy; health checks gate readiness.
- Background task workers scaled separately from the API.
- A staging environment and a smoke-test script that runs one tiny end-to-end project post-deploy.
- README/runbook: setup from clean checkout, env vars, how to run a project, how to read the audit log, how to tune thresholds, on-call notes for the common failure modes.

---

## Acceptance criteria (Definition of Done)

1. The e2e suite (including loop-back, escalation-resolution, and resume-after-kill) passes against fakes/mocks.
2. The eval scorecard runs and reports groundedness (must be 100% sourced-or-flagged), calibration, escalation precision/recall, saturation behavior, self-check catch rate, and budget adherence; deterministic gates block merge on regression.
3. Fault injection (LLM errors, one/all source adapters down, mid-stage process kill) results in graceful, resumable behavior — never corrupt state or silent data loss.
4. Per-run tracing links stages → LLM calls (with tokens/prompt versions) → source calls; key metrics are emitted.
5. Global spend ceiling halts runs independent of per-project budgets.
6. Archive/delete cascades; an export bundle (report + deck + sources + audit) is produced.
7. A clean-checkout deploy to staging passes the post-deploy smoke test; the runbook reproduces setup and a sample run.

## Manual demo
Deploy to staging from a clean checkout; run the smoke-test project; pull its run trace and eval scorecard; kill a worker mid-run and show it resumes; take an adapter offline and show search continues and audits the outage.

---

## Suggested build order recap (whole project)

0 Foundation → 1 Orchestration (stubs prove the pipeline) → 2 Search → 3 Analysis → 4 Comparison+Gap → 5 Report+Presentation → 6 Frontend (start against contracts after Phase 1; finish after 5) → 7 Integration & Hardening. Frontend shell and the Monitor/Escalation screens can be built in parallel with Phases 2–5 since their contracts freeze in Phase 1.
