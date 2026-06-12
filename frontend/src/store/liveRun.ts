// Live run state, fed by WebSocket events (and refreshed by polling when the
// socket is down). One store keyed by project — the app monitors one project
// at a time, but events for other projects update notifications regardless.

import { create } from "zustand";

import type { Stage, WsEvent } from "../api/types";

export interface ActivityLine {
  id: string;
  timestamp: string;
  stage: Stage | null;
  text: string;
  kind: "activity" | "loop_back" | "stage_changed" | "error";
}

export interface BudgetCounter {
  running_total: number;
  ceiling: number | null;
}

export interface Counters {
  papers_found?: number;
  papers_triaged?: number;
  papers_analyzed?: number;
  searches?: number;
  in_scope?: number;
  budget: Record<string, BudgetCounter>;
  [key: string]: unknown;
}

export interface SaturationState {
  state: string;
  novelty_share: number | null;
  iteration?: number;
}

export type ConnectionState = "connecting" | "open" | "polling" | "closed";

interface LiveRunState {
  projectId: string | null;
  runId: string | null;
  currentStage: Stage | null;
  feed: ActivityLine[];
  counters: Counters;
  saturation: SaturationState | null;
  openEscalationId: string | null;
  connection: ConnectionState;
  lastEventAt: string | null;
  reset: (projectId: string) => void;
  setConnection: (state: ConnectionState) => void;
  applyEvent: (event: WsEvent) => void;
}

const MAX_FEED = 200;

function describe(event: WsEvent): string {
  const p = event.payload as Record<string, unknown>;
  switch (event.type) {
    case "stage_changed":
      return `Stage: ${String(p.from_stage ?? "start")} → ${String(p.to_stage)}`;
    case "loop_back":
      return `Loop back (iteration ${String(p.iteration ?? "?")}) — ${String(p.reason ?? "")}`;
    case "error":
      return `Error: ${String(p.message ?? "unknown")}`;
    default:
      return String(p.description ?? p.summary ?? event.type);
  }
}

export const useLiveRun = create<LiveRunState>((set, get) => ({
  projectId: null,
  runId: null,
  currentStage: null,
  feed: [],
  counters: { budget: {} },
  saturation: null,
  openEscalationId: null,
  connection: "closed",
  lastEventAt: null,

  reset: (projectId) =>
    set({
      projectId,
      runId: null,
      currentStage: null,
      feed: [],
      counters: { budget: {} },
      saturation: null,
      openEscalationId: null,
      lastEventAt: null,
    }),

  setConnection: (connection) => set({ connection }),

  applyEvent: (event) => {
    const state = get();
    if (state.projectId && event.project_id !== state.projectId) return;

    const next: Partial<LiveRunState> = {
      lastEventAt: event.timestamp,
      runId: event.run_id ?? state.runId,
    };

    if (event.stage) next.currentStage = event.stage;

    switch (event.type) {
      case "stage_changed": {
        const to = event.payload.to_stage as Stage | undefined;
        if (to) next.currentStage = to;
        break;
      }
      case "counter_update": {
        const p = event.payload as Record<string, unknown>;
        if (typeof p.category === "string") {
          // BudgetGuard counter: {category, running_total, ceiling, remaining}
          next.counters = {
            ...state.counters,
            budget: {
              ...state.counters.budget,
              [p.category]: {
                running_total: Number(p.running_total ?? 0),
                ceiling: typeof p.ceiling === "number" ? p.ceiling : null,
              },
            },
          };
        } else {
          // Stage counters: {papers_found, papers_triaged, searches, papers_analyzed, …}
          next.counters = { ...state.counters, ...p, budget: state.counters.budget };
        }
        break;
      }
      case "saturation_update": {
        next.saturation = {
          state: String(event.payload.state ?? "still finding new ideas"),
          novelty_share:
            typeof event.payload.novelty_share === "number" ? event.payload.novelty_share : null,
          iteration: event.payload.iteration as number | undefined,
        };
        break;
      }
      case "escalation_raised": {
        next.openEscalationId = String(event.payload.escalation_id ?? "");
        break;
      }
      case "escalation_resolved": {
        next.openEscalationId = null;
        break;
      }
      default:
        break;
    }

    if (
      event.type === "activity" ||
      event.type === "loop_back" ||
      event.type === "stage_changed" ||
      event.type === "error"
    ) {
      const line: ActivityLine = {
        id: event.id,
        timestamp: event.timestamp,
        stage: event.stage,
        text: describe(event),
        kind: event.type as ActivityLine["kind"],
      };
      next.feed = [...state.feed, line].slice(-MAX_FEED);
    }

    set(next);
  },
}));
