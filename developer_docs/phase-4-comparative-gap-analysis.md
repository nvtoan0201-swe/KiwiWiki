# Phase 4 — Comparative & Gap Analysis

**Goal:** Move from per-paper records to a map of the field, then surface what isn't known. Cluster the literature, build a comparison matrix on the dimensions the field actually contests, separate consensus from contested points (investigating *why* sources disagree before declaring any winner), and synthesize grounded gaps and future directions.

**Prerequisites:** Phases 0–3 pass (analyses + credibility + contradiction flags exist).

---

## Part A — Comparative Analysis handler

`backend/app/stages/comparison/handler.py` (`Stage.comparative_analysis`)

### 1. Clustering
- `stages/comparison/clustering.py` — group analyzed sources by approach/school of thought.
  - Use `sources.embedding` for candidate grouping, then an LLM pass to name and characterize each cluster (`clusters.label`, `description`, `defining_characteristics`). Assign `sources.cluster_id`.
  - Number of clusters is data-driven (not fixed); allow a paper to be primary in one cluster but noted as bridging others.

### 2. Comparison dimensions (data-driven, not templated)
- `stages/comparison/dimensions.py` — derive the dimensions from what the papers actually contest (e.g., method, assumptions, datasets, metrics, populations, results, conditions where each wins). The LLM proposes dimensions grounded in the analyses + contradiction flags; reject generic dimensions no paper actually varies on. If the field's real fight is over, say, evaluation methodology, that becomes a central dimension.

### 3. Matrix
- Build `comparisons.matrix(jsonb)`: clusters × dimensions, each cell grounded in specific sources (every non-trivial cell carries `source_ids` and a `provenance` link). Store on the `comparisons` row.

### 4. Consensus vs. contested
- `stages/comparison/consensus.py` — explicitly partition findings into `consensus_points` (what the field agrees on, weighted by credibility) and `contested_points` (still open).
- For each contested point (seed from `contradictions` plus newly detected disagreements): **investigate why** — different datasets? metrics? populations? time periods? Record the investigation. Reach either a conditional resolution ("approach A wins when X; B when Y") or an honest "it depends on Z / unresolved." Update `contradictions.investigation` and `resolution`/`resolved`. A forced ranking where the evidence supports only "it depends" is a defect.
- Weight by `credibility_score`: a consensus resting on weak studies is labeled accordingly (`emerging`/`contested`, not `well_established`).

### 5. Confidence labeling
- Each consensus/contested point and matrix conclusion gets a `ConfidenceLabel`, carried forward to report/presentation.

### Loop-back
- If clustering/comparison reveals the evidence base is too thin or lopsided to map the field (e.g., a cluster with one weak paper that the question hinges on), return `LoopBack` to `paper_analysis` (promote set-aside papers) or `literature_search` (new terms), bounded by the cap. Otherwise `Advance`.

### Schemas & prompts
- `schemas/comparison.py` (`Cluster`, `Dimension`, `MatrixCell`, `ConsensusPoint`, `ContestedPoint`), `prompts/cluster_v1.md`, `prompts/dimensions_v1.md`, `prompts/consensus_v1.md`, `prompts/contradiction_investigate_v1.md`.

---

## Part B — Gap & Future-Directions handler

`backend/app/stages/gap/handler.py` (`Stage.gap_analysis`)

**Behavior:** From the comparison map (not from imagination), synthesize gaps:
- questions no analyzed paper answers,
- untested assumptions shared across a cluster,
- method combinations not yet tried,
- populations / conditions / datasets not yet studied.

Each `gaps` row carries `description`, `supporting_evidence` (the cluster/paper facts that reveal the gap — grounded, via provenance), `importance` (high/medium/low), and a `confidence_label`. Future-direction suggestions are stored and **labeled `speculative`** — they are the agent's synthesis, not established fact, and must be marked as such so the report stage renders them honestly.

**Stop:** when gaps are enumerated from the available map; budget-bounded as usual.

**Schemas & prompts:** `schemas/gap.py` (`Gap`), `prompts/gap_synthesis_v1.md`.

---

## Implementation notes

- Limit pairwise LLM comparisons using embedding similarity to keep token cost bounded on large source sets.
- Every cell/point/gap must be traceable: write `provenance` rows linking each to its supporting `source_id`s; inference-only conclusions are flagged `is_inference=true`.
- Resumability: clustering and matrix building checkpoint to the `comparisons` row; gap synthesis skips if already present.
- Do not let the comparison invent agreement — if sources don't actually converge, it stays contested.

---

## Acceptance criteria (Definition of Done)

1. Analyzed sources are assigned to named clusters with characterizations; cluster count reflects the data (a single-topic fixture yields one cluster, a mixed fixture yields several).
2. Comparison dimensions are derived from actual variation in the fixture (a generic dimension no paper varies on is not produced).
3. The matrix is populated with cells that each cite supporting sources via provenance.
4. A fixture with a genuine conflict yields a `contested_point` with a recorded why-investigation and either a conditional resolution or an explicit "unresolved"; the corresponding `contradictions` row is updated.
5. A consensus resting on low-credibility fixtures is labeled below `well_established`.
6. Gaps are produced with grounded `supporting_evidence` and importance; future directions are stored as `speculative`.
7. A thin-evidence fixture triggers a bounded loop-back; a sufficient fixture advances.
8. Every matrix cell, consensus/contested point, and gap has provenance or an inference flag.

## Manual demo
Continue the running demo project into comparison and gap analysis; inspect the field-map data: clusters, the matrix with source-backed cells, the consensus/contested split with investigations, and a grounded gap list with speculative future directions clearly marked.
