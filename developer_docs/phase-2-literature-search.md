# Phase 2 — Literature Search

**Goal:** Implement the Scoping handler and the Literature Search handler. Scoping turns the request into a confirmed research question (escalating on ambiguity). Search runs iteratively — broaden/tighten, snowball via citations, triage hits by relevance, and stop at *idea saturation* rather than a count.

**Prerequisites:** Phases 0–1 pass.

---

## Part A — Scoping handler

`backend/app/stages/scoping/handler.py` (`Stage.scoping`)

**Behavior:**
1. Take `project.original_request` and any user-supplied scope fields.
2. Via the LLM (`complete_json` against a `ScopeProposal` schema), produce: a restated `research_question`, proposed scope (time_window, included/excluded subfields, depth, audience, outputs), and a list of **ambiguities** each with 2–4 resolution options.
3. Also classify `answerable_from_literature: bool` with reasoning.
4. If there are material ambiguities **or** `answerable_from_literature` is false → return `Escalate(trigger=ambiguous_scope or thin_literature, question, context=proposal, options)`. (Sensitivity setting decides borderline cases.)
5. On resume with the user's response, merge resolutions into the scope, persist `research_question`/`scope`/`audience`/`outputs_requested` on the project, audit `stage_complete`, return `Advance`.

**Files:** `schemas/scoping.py` (`ScopeProposal`, `Ambiguity`), `prompts/scoping_v1.md`.

**Acceptance:** an ambiguous request escalates with concrete options; a clear request advances and persists a research question; the resolved scope is reflected on the project.

---

## Part B — Source adapters

`backend/app/adapters/sources/` — implement the `SourceAdapter` ABC for:
- `openalex.py`, `arxiv.py`, `semantic_scholar.py`, `crossref.py`

Each provides `search`, `fetch`, `references`, `citations`, returning the shared `SourceHit`/`SourceRecord` shapes. Requirements:
- Normalize fields (title, authors, venue, year, doi, url, abstract) into the common shape; keep the raw payload in `raw_metadata`.
- Respect rate limits; exponential backoff; map failures to `SourceUnavailable` (one source down must not kill search — log, audit, continue with others).
- A `SourceRouter` that fans a query across enabled adapters and **deduplicates** by DOI, then by normalized title + year + first author. Dedup keeps the richest record and records all origin adapters.
- Each external call charges `budget('search_calls', 1)`.

**Files:** `adapters/sources/router.py`, plus a fake adapter `adapters/sources/fake.py` returning canned results for tests.

---

## Part C — Literature Search handler

`backend/app/stages/search/handler.py` (`Stage.literature_search`)

**The loop (iterative, budget- and saturation-bounded):**

1. **Seed queries** — LLM generates an initial set of diverse queries from the research question (different framings/terminology), emit an `activity` line per query.
2. **Execute & dedup** — run queries through `SourceRouter`; merge into `sources` (status initially unset).
3. **Relevance triage** — for each new hit, score relevance 0–1 from title+abstract against the research question (LLM in a single batched call where possible; cache by source id). Assign `TriageStatus` and `triage_reason` using thresholds (configurable): high→`deep_read` candidate, mid→`skimmed`, low→`set_aside`, off-topic→`excluded`. Persist scores. Emit `counter_update` (papers_found/triaged).
4. **Embed** — compute and store `sources.embedding` for triaged-in papers (used for saturation + Phase 4 clustering).
5. **Snowball** — for the strongest papers, pull `references` and `citations` (channel `citation_snowball`), dedup against existing, feed back into triage. This is a distinct discovery channel from keyword search and must be tagged as such.
6. **Diversity / echo-chamber check** — assess whether the triaged-in set clusters around a single viewpoint; if dangerously homogeneous, generate counter-viewpoint queries and run another iteration. Record a diversity indicator in the stage summary.
7. **Saturation check (stopping criterion)** — after each iteration, measure how many *new ideas* the latest batch introduced. Operationalize: embed new papers' core-topic vectors and compute novelty as the share whose nearest-neighbor similarity to already-collected papers is below a threshold; combine with an LLM judgment ("did the last batch introduce new methods/claims or restate known ones?"). If novelty < threshold for two consecutive iterations → **saturation reached**. Emit `saturation_update` each iteration ("still finding new ideas" → "approaching saturation" → "saturated").
8. **Stop conditions:** saturation reached, or budget hit (`search_calls`/`llm_tokens`/time), or a hard iteration cap. Record `stopping_criterion` contribution and a saturation summary (thorough vs. thin) in the stage summary.
9. **Query reformulation:** if an iteration returns mostly duplicates or mostly low-relevance, the next queries must change strategy (LLM prompted with what failed), audited as `query_reformulated`. Do not just paginate deeper.

**Output:** the `sources` table populated with relevance/credibility(*placeholder until Phase 3*)/triage status; a stage summary with counts, diversity indicator, saturation judgment, and channels used.

**Loop-back:** none originates here (this is the earliest content stage). It *receives* loop-backs from later stages with new seed terms in context; on re-entry it adds to the existing set rather than restarting.

**Files:** `schemas/search.py` (`SearchIteration`, `RelevanceScore`, `SaturationReport`), `prompts/seed_queries_v1.md`, `prompts/relevance_triage_v1.md`, `prompts/reformulate_v1.md`, `prompts/saturation_judge_v1.md`, `stages/search/saturation.py`, `stages/search/triage.py`.

---

## Implementation notes

- Batch LLM relevance scoring (many abstracts per call) to control token cost; the BudgetGuard must see the usage.
- Make thresholds (relevance bands, saturation novelty cutoff, iteration cap, diversity trigger) configuration with sane defaults — they will need tuning.
- Saturation must be reported honestly: if the run stopped on budget before saturation, the summary says "coverage thin (stopped on budget)", surfaced later in the report's stopping-criterion note.
- Snowballing depth is bounded (default 1 hop from top-N papers) and budget-charged.

---

## Acceptance criteria (Definition of Done)

1. Scoping escalates on an ambiguous request and advances (persisting a research question) on a clear one.
2. With the fake adapter, the search handler runs multiple iterations, dedups across "sources", triages hits into the four statuses with reasons, and stores embeddings.
3. Reciprocal-duplicate inputs are merged into single `sources` rows with multiple origin adapters recorded.
4. Snowballed papers are tagged `citation_snowball` and distinct from keyword hits.
5. A canned "saturating" fixture (later batches restate earlier ideas) triggers saturation stop; a "diverse" fixture keeps iterating until the cap; a tiny budget triggers a budget stop with a "thin coverage" summary.
6. The echo-chamber fixture triggers at least one counter-viewpoint reformulation.
7. `counter_update` and `saturation_update` events are emitted each iteration; all reformulations and stops are audited.
8. A live source adapter (e.g., OpenAlex) returns and normalizes real results in an integration test (network-gated/skippable in CI).

## Manual demo
Run a real project through scoping (resolve the escalation) into search against OpenAlex; watch counters and saturation status update live; inspect the populated Source Library data.
