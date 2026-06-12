# Autonomous Research Agent — Screen Design Specification

A **soft design** document: it lists every screen the application needs and details what each one contains, why it exists, and how the user moves through it. It does not specify visual styling, layout grids, or code — only the content and purpose of each screen.

The screens map directly to the agent's workflow (Scoping → Search → Analysis → Comparison → Report → Presentation) plus the supporting screens that make an *autonomous* agent trustworthy: a live activity monitor, human-escalation prompts, provenance tracing, and an audit log.

---

## Screen Map (overview)

**Entry & management**
1. Onboarding / Welcome
2. Projects Dashboard (home)
3. New Research — Scoping
4. Scope Confirmation

**Active run**
5. Agent Activity Monitor (live progress)
6. Human Escalation / Intervention
7. Source Library (literature search results)
8. Paper Analysis Detail
9. Comparative Analysis — Field Map
10. Gap & Future-Directions

**Outputs**
11. Report Viewer / Editor
12. Presentation Viewer
13. Provenance / Source Trace (overlay)

**Support**
14. Audit Log / Run History
15. Budget & Settings
16. Notifications

---

## 1. Onboarding / Welcome

**Purpose:** Orient a first-time user to what the agent does and, crucially, how it behaves — that it works autonomously but will pause to ask at key moments.

**Includes:**
- A short statement of what the agent produces (literature reviews, comparative analyses, reports, presentations).
- A plain-language explanation of the four confidence labels (*well-established, emerging, contested, speculative*) since these appear everywhere downstream.
- A note that the agent escalates for decisions rather than guessing, so the user knows to expect occasional prompts.
- Optional account/workspace setup and a default-budget preference.
- A single clear call-to-action to start the first research project.

---

## 2. Projects Dashboard (home)

**Purpose:** The user's home base — see all research projects and their states at a glance.

**Includes:**
- A list/grid of projects, each card showing: title, the research question, current stage, status (running / awaiting input / complete / paused), and last-updated time.
- A prominent status indicator for any project **awaiting human input** (this is the most time-sensitive state and should be visually unmissable).
- A progress indicator per project tied to the workflow stages.
- Quick actions per project: open, pause/resume, duplicate, archive, delete.
- A "New Research" button.
- A running budget/usage summary across projects.
- Filter and sort controls (by status, date, stage).

---

## 3. New Research — Scoping

**Purpose:** Capture the user's request and the inputs the agent needs to scope it. This is the highest-leverage screen; its quality propagates everywhere.

**Includes:**
- A free-text field for the research question or topic, with examples/placeholder prompts.
- Scope controls the user can set up front (all optional — the agent will propose defaults): time window / "what counts as recent," subfields to include or exclude, depth (quick survey vs. deep dive), and any sources or papers to seed from.
- Intended audience selector (e.g., domain expert, executive, general) — drives report tone and depth later.
- Desired outputs as toggles (report, presentation, raw source library, gap analysis).
- A budget ceiling control (time, number of papers, or cost).
- Optional file upload for seed papers or prior work.
- A "Submit to agent" action that hands off to scoping.

---

## 4. Scope Confirmation

**Purpose:** The agent restates the request as a concrete research question and proposed scope, and asks the user to confirm before real work begins. This is the first escalation point.

**Includes:**
- The agent's restated research question, clearly distinguished from the user's original wording.
- The proposed scope: time window, included/excluded subfields, depth, audience, outputs, budget.
- Any **ambiguities the agent flagged**, each presented as a choice for the user to resolve (e.g., "Did you mean X or Y?").
- A flag if the agent judges the question may not be answerable from literature alone, with its reasoning.
- Editable fields so the user can adjust scope inline.
- Confirm / Revise actions. Confirming launches the run.

---

## 5. Agent Activity Monitor (live progress)

**Purpose:** Make autonomous work transparent. The user can watch what the agent is doing, why, and how much budget remains, and can intervene.

**Includes:**
- The current stage and a stage timeline showing what's done, active, and upcoming.
- A live activity feed in plain language ("Searching for…," "Reading paper X," "Found a contradiction between A and B, flagging for comparison," "Looping back to search — a new subfield surfaced").
- **Loop-back events** shown explicitly, with the trigger that caused them, so the non-linear workflow is legible.
- Live counters: papers found, papers triaged, papers deep-read, searches run, budget consumed vs. ceiling.
- The current saturation judgment during search ("still finding new ideas" vs. "approaching saturation").
- Controls: pause, resume, adjust budget mid-run, or stop early and produce outputs from what's gathered so far.
- A banner that appears when the agent has paused for human input, linking to the escalation screen.

---

## 6. Human Escalation / Intervention

**Purpose:** Where the agent asks the user a question it has decided it should not answer on its own. Asking rarely but at the right moments is the core trust behavior.

**Includes:**
- A clear statement of *what* the agent is asking and *why it paused* (ambiguous scope, thin literature, unresolved contradiction, or a high-stakes call).
- The relevant context: the conflicting findings, the sparse-evidence area, or the interpretations in tension — with links to the underlying sources.
- The decision presented as concrete options where possible, plus a free-text option for nuanced direction.
- The consequence of each choice, so the user understands the tradeoff.
- An option to let the agent proceed with its own best judgment (and have it note the assumption in the output).
- Submit action that resumes the run.

---

## 7. Source Library (literature search results)

**Purpose:** Show everything the search found and how the agent triaged it — the evidence base the user can inspect and correct.

**Includes:**
- A list of all discovered sources with: title, authors, venue, year, and the agent's **relevance score** and **credibility score**.
- Triage status per source: deep-read, skimmed, noted-and-set-aside, excluded — with the reason.
- Discovery channel tag (keyword search vs. citation snowballing) so coverage is legible.
- A **diversity / consensus indicator** — a warning if the set skews toward agreement (an echo-chamber signal) and a view of the range of viewpoints.
- The saturation summary: whether coverage is judged thorough or thin, and why.
- Filters and sort (by relevance, credibility, year, status, cluster).
- User overrides: promote a set-aside paper to deep-read, exclude one, or add a paper manually — each of which can trigger re-analysis.
- Drill-in to each paper's analysis detail.

---

## 8. Paper Analysis Detail

**Purpose:** The structured record for a single paper, so the user can verify what the agent extracted and concluded.

**Includes:**
- Bibliographic header: title, authors, venue, year, link to original.
- The extracted structured record: core claim, method, key results with numbers, datasets/conditions, and author-stated limitations.
- The agent's **own critical assessment** — weaknesses the authors didn't admit — clearly marked as the agent's inference, not the paper's text.
- The credibility breakdown: venue quality, sample size, methodology rigor, funding/conflicts, replication status, and the resulting weight.
- A confidence label for the paper's central finding.
- **Contradiction flags** linking to papers it conflicts with.
- Provenance links from each extracted point back to the source passage.
- User actions: correct an extraction, adjust the weight, add a note.

---

## 9. Comparative Analysis — Field Map

**Purpose:** The cross-cutting view — the agent's map of the field rather than a pile of summaries.

**Includes:**
- Clusters of the literature by approach or school of thought, with what defines each.
- A comparison matrix across the dimensions the field actually contests (method, assumptions, data, results, conditions where each approach wins) — dimensions chosen from the evidence, not a generic template.
- A clear separation of **consensus** (what the field agrees on) from **contested** points (what's still open).
- For each contested point, the agent's investigation of *why* sources disagree (different datasets, metrics, populations) and whether it reached "X wins" or "it depends on Y."
- Links from every cell/claim back to the supporting papers.
- A path into the gap analysis.

---

## 10. Gap & Future-Directions

**Purpose:** Surface what *isn't* known — often the actual reason the research was commissioned.

**Includes:**
- Identified gaps: questions no paper answers, untested assumptions, method combinations not yet tried, populations or conditions not yet studied.
- Each gap tied to the evidence that reveals it (i.e., grounded in the comparative map, not invented).
- A confidence/importance indication per gap.
- Suggested future directions, clearly labeled as the agent's *speculative* synthesis rather than established fact.
- Links back to the relevant clusters and papers.

---

## 11. Report Viewer / Editor

**Purpose:** Read, verify, and refine the final written deliverable.

**Includes:**
- The rendered report, structured and pitched to the audience set in scoping.
- **Inline confidence labels** carried through from analysis, so hedged and firm claims look different on the page.
- Inline citations; clicking any claim opens its provenance trace.
- A visible result of the agent's **self-check pass** (what it reviewed, anything it flagged as potentially overstated).
- A note of which stopping criterion ended the run — natural completion vs. budget ceiling — since that signals output quality.
- Editing tools: edit text, accept/reject the agent's hedging, request a re-write for a different audience or length, or ask the agent to expand a section (which may reopen earlier stages).
- Export options (the document file, with citations).

---

## 12. Presentation Viewer

**Purpose:** Review the distilled presentation — a re-authoring around a few key messages, not the report with bullets.

**Includes:**
- The slides/sequence, organized around the 3–5 key messages and a narrative through-line.
- The identified through-line stated explicitly so the user can judge the framing.
- Per-slide: headline message, supporting evidence, and any visual the agent chose (comparison table, timeline, trend) with its rationale.
- Speaker notes / appendix where nuance was moved to keep the main flow clean.
- Edit controls: reorder, change the through-line, promote/demote a finding, adjust visuals.
- Export options.

---

## 13. Provenance / Source Trace (overlay)

**Purpose:** Let the user trace any single claim, anywhere in the app, back to its origin. This is an overlay/panel rather than a standalone destination.

**Includes:**
- The claim as stated in the output.
- The chain: claim → paper(s) → the specific passage(s) it derives from.
- The confidence label and credibility weight attached to it.
- A flag if the claim is the agent's own inference rather than sourced.
- A link to open the full paper analysis or the original source.

---

## 14. Audit Log / Run History

**Purpose:** Reconstruct and inspect the entire run — every decision and why — supporting auditability and resume-not-restart.

**Includes:**
- A chronological log of every meaningful action: searches run, queries reformulated (and why), papers triaged, loop-backs (with triggers), escalations and the user's answers, and stopping decisions.
- The reasoning attached to each decision.
- The ability to view the project state at any prior point.
- Resume / re-run from a chosen point.
- Export of the log for sharing or compliance.

---

## 15. Budget & Settings

**Purpose:** Control the agent's resource use and standing preferences.

**Includes:**
- Default budget ceilings (time, papers, cost) for new projects and for the active run.
- Default audience, output types, and "what counts as recent" by topic area.
- Escalation sensitivity — how readily the agent pauses to ask vs. proceeds on its own judgment.
- Source preferences (preferred/excluded venues, languages, date ranges).
- Account, workspace, and notification preferences.

---

## 16. Notifications

**Purpose:** Reach the user when the agent needs them — chiefly because, running autonomously, it will sometimes pause and wait.

**Includes:**
- Alerts for: agent awaiting human input (highest priority), run complete, budget ceiling approaching/reached, run stopped early, and significant findings if the user opted in.
- Each notification deep-links to the relevant screen (escalation, report, monitor).
- Delivery preferences (in-app, email, push) configured in settings.

---

## Notes on flow

- The **happy path** is: Dashboard → New Research → Scope Confirmation → Activity Monitor → (outputs) Report / Presentation.
- The **interruption path** can break in at any active stage: Activity Monitor → Escalation → back to Activity Monitor. This is normal, not exceptional, and the design treats it as a first-class flow.
- **Provenance** and the **Audit Log** are reachable from nearly everywhere, because traceability is the feature that makes an autonomous agent trustworthy rather than just fast.