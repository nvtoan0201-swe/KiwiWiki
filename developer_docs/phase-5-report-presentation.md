# Phase 5 — Report Writing & Presentation Generation

**Goal:** Produce the two deliverables. The report is audience-pitched, carries confidence labels and inline citations, and passes a self-critique before it's done. The presentation is a re-authoring around a few key messages, not the report with bullets. Both export to files.

**Prerequisites:** Phases 0–4 pass (comparison map + gaps exist).

---

## Part A — Report Writing handler

`backend/app/stages/report/handler.py` (`Stage.report_writing`)

### Inputs
The research question, scope/audience, the comparison map (clusters, matrix, consensus/contested), gaps/future directions, paper analyses, contradictions, and the run's stopping criterion.

### Behavior
1. **Plan structure by audience.** Pick structure/depth/vocabulary from `project.audience`:
   - expert → methodology detail, hedging, full citations;
   - executive → bottom line first, implications, light citations;
   - general → plain-language, more context.
   Produce an outline (LLM) before drafting.
2. **Draft section by section** (`stages/report/writer.py`), pulling claims from the grounded data. Every non-obvious claim:
   - carries an **inline citation** referencing the `source_id`(s) (rendered as a marker the UI resolves to a provenance trace), and
   - carries its **confidence label** so hedged vs. firm claims read differently. Do not flatten everything to confident prose.
   - Contested points are presented as disagreements (not silently resolved); gaps and future directions are included and future directions marked speculative.
3. **Stopping-criterion note.** Include how the run ended (saturation/coverage vs. budget) since it signals output completeness.
4. **Self-check pass (required)** — `stages/report/self_check.py`: the agent reviews its own draft against the source records and answers, per claim/section:
   - is each claim supported by provenance?
   - is anything overstated relative to its credibility/confidence label?
   - are disagreements represented fairly?
   - did any unsourced, un-flagged assertion sneak in?
   Findings are written to `reports.self_check_result(jsonb)`. Any unsupported claim is either fixed (re-grounded), softened, or removed before completion — not shipped. Audit the self-check.
5. Persist the `reports` row (markdown canonical), version it, emit `output_ready(report)`.

### Schemas & prompts
- `schemas/report.py` (`ReportOutline`, `ReportSection`, `SelfCheckResult`), `prompts/report_outline_v1.md`, `prompts/report_section_v1.md`, `prompts/self_check_v1.md`.

### Editing support (API, consumed by the viewer in Phase 6)
- `PATCH /reports/{id}` — store user edits.
- `POST /reports/{id}/rewrite` — re-generate for a different audience/length, or expand a section (the latter may request a loop-back via a new run if more evidence is needed).

---

## Part B — Presentation Generation handler

`backend/app/stages/presentation/handler.py` (`Stage.presentation_generation`)

### Behavior
1. **Choose the through-line first** — one synthesizing narrative, stored in `presentations.through_line`.
2. **Select 3–5 key messages** (`key_messages`) that serve the through-line; pull only the evidence that supports them — distill, don't dump.
3. **Build slides** (`slides(jsonb)`): each slide = headline message + supporting evidence (with source refs) + an optional **visual spec** (type: comparison_table | timeline | trend | bullet_set, plus the data for it) where a visual communicates better than text. The agent decides which findings are headline vs. backup.
4. **Speaker notes / appendix** (`speaker_notes`) hold the nuance moved out of the main flow so slides stay clean.
5. Persist, version, emit `output_ready(presentation)`.

### Schemas & prompts
- `schemas/presentation.py` (`Slide`, `VisualSpec`, `KeyMessage`), `prompts/through_line_v1.md`, `prompts/slide_build_v1.md`.

---

## Part C — Export adapters

`backend/app/adapters/export/`
- `docx.py` — render report markdown → `.docx` (`python-docx`): headings, inline citation markers, a references section built from the cited `sources`, confidence labels preserved.
- `pptx.py` — render the presentation model → `.pptx` (`python-pptx`): one slide per `slides` entry, render `VisualSpec` (tables/simple charts), speaker notes into the notes pane.
- `markdown.py` — report → portable `.md` (canonical), and a slides `.md` fallback.
- API: `GET /reports/{id}/export?format=docx|md`, `GET /presentations/{id}/export?format=pptx|md` — stream the file.

**Note for the coding agent:** in this Anthropic environment, prefer the provided document skills' patterns for docx/pptx generation if available; otherwise use `python-docx`/`python-pptx` directly as specified.

---

## Implementation notes

- The canonical content is markdown; exporters are pure transforms over the stored model so re-export after edits is deterministic.
- Citation markers in markdown must map deterministically to `provenance`/`sources` so the viewer can resolve them and the docx references list is consistent.
- The self-check is not optional and not cosmetic: it must be able to *block completion* by forcing edits. Make its decisions auditable.
- Keep report and presentation as separate versioned rows; editing one never mutates the other.

---

## Acceptance criteria (Definition of Done)

1. For the same project, an `expert` vs. `executive` audience setting produces measurably different structure/depth (verified by outline shape + citation density).
2. The report contains inline citation markers resolvable to sources, confidence labels on claims, a contested-points section presented as disagreement, gaps, future directions marked speculative, and a stopping-criterion note.
3. A planted unsupported claim in a draft is caught by the self-check and is removed/softened before the `reports` row is finalized; the `self_check_result` records the catch.
4. The presentation has a stored through-line, 3–5 key messages, slides with headline+evidence+optional visual specs, and speaker notes; it is not a 1:1 copy of the report sections.
5. `.docx`, `.pptx`, and `.md` exports generate, open without corruption, and the docx references list matches the cited sources.
6. `rewrite` regenerates for a new audience without losing provenance.
7. `output_ready` events fire for both deliverables.

## Manual demo
Take the running demo project to completion; export the report as docx and the deck as pptx; open both; verify citations resolve, confidence labels survive, the deck reads as a distilled narrative, and the self-check log shows at least one review action.
