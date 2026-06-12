# Phase 3 — Paper Analysis

**Goal:** Turn triaged sources into structured, credibility-weighted, provenance-linked analysis records. Tiered reading allocates depth by value; extraction is structured; credibility is scored from method not confidence; contradictions are flagged for the comparison stage; loop-backs fire when a paper reveals a missed subfield.

**Prerequisites:** Phases 0–2 pass (sources triaged).

---

## Deliverables

`backend/app/stages/analysis/handler.py` (`Stage.paper_analysis`)

### Inputs
All `sources` with `triage_status in (deep_read, skimmed)` (and any user-promoted papers). `set_aside`/`excluded` are not analyzed unless promoted.

### Content acquisition
- `stages/analysis/fetch.py` — obtain the best available text per source: open-access full text where retrievable (via the source adapters / open links), else abstract + metadata. Never bypass paywalls or access controls; if only the abstract is available, analyze at reduced depth and record `text_available: abstract_only`. Charges `budget('papers_read', 1)`.

### Tiered reading
- `stages/analysis/reader.py` implements three depths:
  - **Skim** (for `skimmed` status): extract core claim, method, headline result, confidence — lightweight, cheap.
  - **Deep read** (for `deep_read`): full structured extraction (below).
  - Depth can be upgraded if a skim reveals the paper is more central than triage thought (record the upgrade + reason).

### Structured extraction (deep read)
Via `complete_json` against a `PaperAnalysis` schema. Extract:
- `core_claim`
- `method`
- `results` — key findings **with numbers** where present (effect sizes, accuracies, sample stats)
- `datasets` / conditions
- `author_limitations` — limitations the authors themselves state
- `agent_critique` — weaknesses the authors did **not** admit, explicitly marked as the agent's inference (never presented as the paper's text)
- `confidence_label` for the paper's central finding

Each extracted point that may surface in outputs is written to `provenance` with the supporting `passage` (quote ≤15 words or a paraphrase + locator) or flagged `is_inference=true` for the critique. **An extraction with no provenance for a sourced claim is a bug.**

### Credibility scoring
- `stages/analysis/credibility.py` — produce `credibility_breakdown(jsonb)` and a scalar `sources.credibility_score`:
  - venue quality (use available venue metadata / heuristics; do not fabricate impact factors),
  - sample size / statistical power signals,
  - methodology rigor (design type, controls, preregistration if known),
  - funding / conflicts of interest if disclosed,
  - replication status if discoverable.
  - Weight = function of the above. A bold abstract does not raise the score; method does. A small-sample, unreplicated result is logged as weak evidence regardless of framing.
- The score feeds downstream weighting in comparison/report.

### Contradiction flagging
- `stages/analysis/contradictions.py` — when a new analysis conflicts with an already-analyzed paper's claim (LLM comparison over claims within the same topic cluster; use embeddings to limit candidate pairs), write a `contradictions` row (`source_a_id`, `source_b_id`, `description`, `resolved=false`). Do **not** pick a winner here — that is the comparison stage's job. Audit each flag.

### Loop-back trigger
- If deep reading repeatedly surfaces references to a **seminal work or whole subfield absent from `sources`**, return `LoopBack(to=literature_search, reason="missed subfield: <terms>")` with new seed terms in context. Bounded by the engine's loop-back cap.

### Stopping
- Analyze until all in-scope papers are processed or the `papers_read`/`llm_tokens`/time budget is hit. Record coverage (e.g., "42/50 in-scope papers analyzed; stopped on budget") in the stage summary.

### Schemas & prompts
- `schemas/analysis.py` (`PaperAnalysis`, `CredibilityBreakdown`, `ContradictionFlag`), `prompts/deep_read_v1.md`, `prompts/skim_v1.md`, `prompts/credibility_v1.md`, `prompts/contradiction_v1.md`.

---

## Implementation notes

- Process papers concurrently with a bounded worker pool; respect the budget guard centrally.
- Make extraction resumable: on re-entry, skip sources that already have a `paper_analyses` row.
- Keep the `agent_critique` visually/semantically separate from author content in the data model (`agent_critique` field) so the UI can label it as inference — never blend it into `core_claim`.
- Quote discipline: passages stored for provenance follow the copyright limits (short quote or paraphrase). The report stage relies on these being safe to surface.

---

## Acceptance criteria (Definition of Done)

1. Every `deep_read` source gets a `paper_analyses` row with all fields populated (numbers captured where the fixture contains them); every `skimmed` source gets a lightweight record.
2. Each sourced extracted claim has a `provenance` row with a passage; the `agent_critique` is stored separately and, when surfaced, is flagged as inference.
3. `credibility_score` reflects method, not abstract tone: a fixture pair (bold-but-weak vs. rigorous-but-modest) scores the rigorous one higher.
4. A fixture with two conflicting papers produces a `contradictions` row with both ids and a description, `resolved=false`, and no winner chosen.
5. A fixture whose papers cite an absent subfield triggers a `LoopBack` to search with new terms; after the engine returns, analysis resumes without re-analyzing prior papers.
6. A tight `papers_read` budget stops analysis gracefully and records partial coverage in the summary.
7. Concurrency does not double-charge budget or duplicate analyses; resumption skips completed papers.

## Manual demo
Continue the Phase 2 demo project into analysis; open a Paper Analysis Detail's underlying data and verify the structured record, the separated agent critique, the credibility breakdown, and provenance links; confirm at least one contradiction flag exists across the set.
