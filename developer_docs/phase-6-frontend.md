# Phase 6 — Frontend (All Screens)

**Goal:** Build the 16 screens from the screen-design spec against the backend's REST + WebSocket contracts. Emphasis on the screens that make autonomy trustworthy: the live Activity Monitor, the Escalation flow, Provenance tracing, and the Audit Log. The frontend reads from contracts frozen in Phases 0–5; it may start as soon as a given screen's backend phase is done.

**Prerequisites:** Phase 0–1 contracts for shell/monitor/escalation; later screens follow their backend phase. Full completion needs Phases 0–5.

---

## Foundation

- `frontend/src/api/types.ts` — TypeScript mirror of backend enums and schemas (generate from OpenAPI if available; otherwise hand-mirror and keep in sync).
- `frontend/src/api/client.ts` + TanStack Query hooks per resource (`useProjects`, `useProject`, `useRun`, `useSources`, `useAnalysis`, `useComparison`, `useGaps`, `useReport`, `usePresentation`, `useEscalations`, `useAudit`).
- `frontend/src/ws/client.ts` — WebSocket connection to `/ws/projects/{id}`, dispatching events into a store; auto-reconnect; buffers while disconnected.
- `frontend/src/store/` — Zustand stores for live run state (current stage, counters, saturation, activity feed) and notifications.
- Shared components: `ConfidenceBadge` (the four labels, visually distinct), `ProvenancePopover` (overlay; see screen 13), `StageTimeline`, `BudgetMeter`, `StatusPill`, `EmptyState`, `ErrorBoundary`.

---

## Screens (one folder each under `frontend/src/screens/`)

Each entry lists the key components and the data/contracts it binds to. Full content of each screen is in the screen-design spec; this lists the build targets.

1. **Onboarding** — static informational steps; renders the four confidence labels and the "agent will pause to ask" expectation; CTA → New Research. No live data.
2. **ProjectsDashboard** — `useProjects`; project cards (title, question, stage, status, updated); a prominent **awaiting-input** treatment; per-card actions (open/pause/resume/archive/delete); global budget summary; filters/sort; New Research button.
3. **NewResearch** — form: request text, optional scope controls (time window, include/exclude subfields, depth), audience selector, output toggles, budget ceiling, seed-file upload; `POST /projects` then start scoping.
4. **ScopeConfirmation** — renders the `ScopeProposal` (restated question distinct from original), proposed scope (editable), ambiguities as choice controls, the answerable-from-literature flag; Confirm/Revise → `POST /escalations/{id}/resolve`.
5. **ActivityMonitor** *(critical)* — `StageTimeline`; live **activity feed** from `activity` events; live counters (`BudgetMeter` + papers found/triaged/read, searches) from `counter_update`; **saturation indicator** from `saturation_update`; **loop-back markers** inline from `loop_back`; controls (pause/resume/stop/adjust-budget); a banner on `escalation_raised` linking to the Escalation screen.
6. **Escalation** *(critical)* — renders the open escalation: what's asked + why it paused (trigger), the context (conflicting findings / thin area / interpretations) with provenance links, options as controls + free-text, the "proceed with your best judgment" option, consequence text per option; submit → resolve, which resumes the run.
7. **SourceLibrary** — `useSources`; table with relevance + credibility scores, triage status + reason, discovery-channel tag; diversity/echo-chamber indicator; saturation summary; filters/sort; user overrides (promote/exclude/add-manually, which call back to the API and may re-trigger work); drill-in → Paper Analysis Detail.
8. **PaperAnalysisDetail** — `useAnalysis(sourceId)`; bibliographic header; structured record (claim/method/results-with-numbers/datasets/author-limitations); **agent critique clearly labeled as inference**; credibility breakdown; confidence badge; contradiction flags linking to conflicting papers; provenance links per point; edit/correct actions.
9. **ComparativeAnalysis (Field Map)** — `useComparison`; cluster view with characterizations; the comparison **matrix** (clusters × dimensions) with cells linking to sources; consensus vs. contested split; per-contested-point the why-investigation and resolution/"it depends"; link into Gaps.
10. **GapAnalysis** — `useGaps`; gap list with supporting evidence links, importance, confidence; future directions clearly marked **speculative**; links back to clusters/papers.
11. **ReportViewer** — `useReport`; rendered markdown with inline confidence badges and citation markers that open the `ProvenancePopover`; self-check result surfaced; stopping-criterion note; edit tools (`PATCH`), rewrite-for-audience/expand (`POST .../rewrite`), export buttons (docx/md).
12. **PresentationViewer** — `usePresentation`; slide sequence; through-line shown explicitly; per-slide headline+evidence+rendered visual spec; speaker notes/appendix; reorder/edit/promote-demote controls; export (pptx/md).
13. **ProvenancePopover (overlay)** *(critical)* — invoked from any claim/citation anywhere; shows claim → source(s) → passage chain, confidence + credibility, an inference flag when applicable, and a link to the full analysis/original. Built as a reusable overlay, not a route.
14. **AuditLog** — `useAudit` (paginated); chronological entries with action type, description, **reasoning**; loop-backs and escalations called out; view state at a point; resume/re-run-from-point controls; export.
15. **BudgetSettings** — default budgets, default audience/outputs/"what counts as recent", **escalation sensitivity** control, source preferences, account/notification prefs.
16. **Notifications** — list + toast surface; highest priority for **awaiting-input**; also run-complete, budget-approaching, stopped-early, significant-findings (opt-in); each deep-links to the relevant screen; delivery prefs in settings.

---

## Behavior/flow requirements

- **Happy path:** Dashboard → NewResearch → ScopeConfirmation → ActivityMonitor → ReportViewer/PresentationViewer.
- **Interruption path** is first-class: ActivityMonitor → Escalation → back to ActivityMonitor; the awaiting-input state must be impossible to miss (dashboard card, monitor banner, notification, app badge).
- **Provenance and Audit reachable everywhere** — every claim surface offers a trace; a global nav entry reaches the audit log.
- Live state degrades gracefully: if the WS drops, fall back to polling the run/status endpoints and reconnect.
- Confidence labels render consistently via the shared `ConfidenceBadge` everywhere they appear.
- Speculative content (future directions, agent critique) is always visually distinguished from sourced claims.

---

## Acceptance criteria (Definition of Done)

1. A user can create a project, complete scope confirmation, and watch a real run progress live (stage timeline, activity feed, counters, saturation) driven by WS events.
2. When the backend raises an escalation, the awaiting-input state shows on the dashboard, the monitor banner, and a notification; resolving it from the Escalation screen resumes the run and the monitor reflects it.
3. Source Library shows triage/credibility/channel and supports a promote/exclude override that round-trips to the backend.
4. Paper Analysis Detail renders the structured record with the agent critique labeled as inference and working provenance links.
5. Field Map renders clusters + matrix with source-linked cells and the consensus/contested split; Gap screen marks future directions speculative.
6. Report Viewer resolves citation markers via the Provenance overlay, shows confidence badges and the self-check/stopping-criterion info, and exports docx/md; Presentation Viewer shows the through-line and exports pptx.
7. Audit Log lists entries with reasoning and offers resume-from-point.
8. WS disconnect falls back to polling and recovers without a reload; `vitest` component tests cover the critical screens (Monitor, Escalation, Provenance, Report Viewer).

## Manual demo
Drive one real project end to end purely through the UI, including resolving an escalation, inspecting provenance on a report claim, and exporting both deliverables.
