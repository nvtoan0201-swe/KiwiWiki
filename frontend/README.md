# Research Agent — Frontend (Phase 6)

The full KiwiWiki SPA: the 16 screens from the screen-design spec, built on the
React + Vite stack against the backend's frozen REST + WebSocket contracts. The
visual system is the "ink & paper" KiwiWiki design system (warm paper, warm ink,
one botanical-green accent; Newsreader / Public Sans / IBM Plex Mono).

## Stack

- React 19 + TypeScript + Vite
- TanStack Query (server state) — `src/api/hooks.ts`
- Zustand (client state) — `src/store/` (live run, notifications, settings)
- react-router-dom — routing in `src/App.tsx`
- WebSocket client with auto-reconnect + polling fallback — `src/ws/`
- lucide-react icons (brand stroke 1.75); react-markdown + remark-gfm for the report

## Layout

```
src/
  api/        types.ts (mirror of backend enums/schemas), client.ts (typed fetch), hooks.ts
  ws/         client.ts (ProjectSocket: reconnect + polling fallback), useProjectSocket.ts
  store/      liveRun.ts, notifications.ts, settings.ts (Zustand)
  components/ ds.tsx (design-system primitives), shared.tsx (ConfidenceBadge, StageTimeline,
              BudgetMeter, StatusPill, EmptyState, ErrorBoundary), helpers.ts,
              ProvenancePopover.tsx + provenanceContext.ts (the reusable trace overlay),
              CitedMarkdown.tsx (resolves [^src:id] markers + confidence tags), AppShell.tsx
  screens/    one folder per screen (Onboarding, ProjectsDashboard, NewResearch,
              ScopeConfirmation, ActivityMonitor, Escalation, SourceLibrary,
              PaperAnalysisDetail, ComparativeAnalysis, GapAnalysis, ReportViewer,
              PresentationViewer, AuditLog, BudgetSettings, Notifications)
  styles/     tokens.css + base.css + components.css (from the design system) + app.css
  tests/      vitest component tests for the critical screens + helpers
```

## Contracts

The frontend talks to the backend only over REST + the WebSocket event stream.
`src/api/types.ts` mirrors `backend/app/core/constants.py` (enums) and the
Pydantic schemas; keep it in sync (or generate from the OpenAPI schema). The WS
event contract is consumed in `src/store/liveRun.ts` and `src/ws/client.ts`.

In dev, Vite proxies `/api` → `http://localhost:8000` (and `/api/ws` upgrades),
stripping the `/api` prefix — see `vite.config.ts`. Override with `VITE_API_BASE`
/ `VITE_WS_BASE` if the backend is elsewhere.

## Commands

```
npm run dev      # Vite dev server (proxies /api to the Python API on :8000)
npm run build    # tsc -b && vite build
npm run lint     # eslint
npm run test     # vitest (use: npx vitest run)
npx prettier --check "src/**/*.{ts,tsx,css}"
```

## Tests

`vitest` + React Testing Library, jsdom environment (`src/tests/setup.ts`).
Component tests cover the critical screens called out in the phase spec — the
Activity Monitor (live feed, counters, saturation, loop-back markers, escalation
banner, polling fallback), the Escalation flow, the Provenance overlay (passage
chain + inference flag), and the Report Viewer (confidence badges, self-check,
stopping criterion, citation → provenance, exports). Network is mocked with a
small URL-pattern `fetch` stub (`src/tests/utils.tsx`) so the real client +
hooks run.
