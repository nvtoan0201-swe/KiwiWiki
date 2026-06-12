import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ActivityMonitor } from "../screens/ActivityMonitor/ActivityMonitor";
import { useLiveRun } from "../store/liveRun";
import type { WsEvent } from "../api/types";
import { PROJECT_ID, mockFetch, renderAt } from "./utils";

function evt(partial: Partial<WsEvent> & Pick<WsEvent, "type">): WsEvent {
  return {
    id: Math.random().toString(36).slice(2),
    project_id: PROJECT_ID,
    run_id: "run-1",
    stage: null,
    timestamp: "2026-06-12T12:00:00Z",
    payload: {},
    ...partial,
  };
}

const project = {
  id: PROJECT_ID,
  title: "Sleep & immunity",
  original_request: "How does sleep loss affect immune function?",
  research_question: "How does sleep restriction alter immune markers?",
  scope: null,
  audience: "domain_expert",
  outputs_requested: ["report"],
  budget: { papers_read: 60 },
  status: "running",
  current_stage: "literature_search",
  created_at: "2026-06-10T10:00:00Z",
  updated_at: "2026-06-12T10:00:00Z",
};

beforeEach(() => {
  useLiveRun.getState().reset(PROJECT_ID);
  useLiveRun.getState().setConnection("open");
  mockFetch([
    [
      /\/projects\/[^/]+\/runs$/,
      () => [
        {
          id: "run-1",
          project_id: PROJECT_ID,
          status: "running",
          started_at: "2026-06-12T11:00:00Z",
          ended_at: null,
          stopping_criterion: null,
          budget_consumed: { papers_read: 12 },
        },
      ],
    ],
    [/\/projects\/[^/]+\/escalations/, () => []],
    [/\/projects\/[^/]+$/, () => project],
  ]);
});

describe("ActivityMonitor", () => {
  it("renders the stage timeline and the live activity feed from WS events", async () => {
    useLiveRun.getState().applyEvent(
      evt({
        type: "activity",
        stage: "literature_search",
        payload: { description: "Ran query: sleep AND IL-6" },
      }),
    );
    useLiveRun.getState().applyEvent(
      evt({
        type: "counter_update",
        stage: "literature_search",
        payload: { papers_found: 23, papers_triaged: 14, searches: 3 },
      }),
    );
    useLiveRun.getState().applyEvent(
      evt({
        type: "saturation_update",
        stage: "literature_search",
        payload: { state: "approaching saturation", novelty_share: 0.18, iteration: 3 },
      }),
    );

    renderAt(<ActivityMonitor />, {
      path: "/projects/:projectId/monitor",
      route: `/projects/${PROJECT_ID}/monitor`,
    });

    expect(await screen.findByText("Sleep & immunity")).toBeInTheDocument();
    const feed = screen.getByTestId("activity-feed");
    expect(within(feed).getByText(/Ran query: sleep AND IL-6/)).toBeInTheDocument();

    const counters = screen.getByTestId("counters");
    expect(within(counters).getByText("23")).toBeInTheDocument();
    expect(within(counters).getByText("14")).toBeInTheDocument();

    expect(screen.getByTestId("saturation-indicator")).toHaveTextContent("approaching saturation");
  });

  it("shows a loop-back marker inline in the feed", async () => {
    useLiveRun.getState().applyEvent(
      evt({
        type: "loop_back",
        stage: "literature_search",
        payload: { iteration: 4, reason: "coverage too thin" },
      }),
    );
    renderAt(<ActivityMonitor />, {
      path: "/projects/:projectId/monitor",
      route: `/projects/${PROJECT_ID}/monitor`,
    });
    expect(await screen.findByTestId("loop-back-marker")).toBeInTheDocument();
    expect(screen.getByText(/coverage too thin/)).toBeInTheDocument();
  });

  it("surfaces the escalation banner when an escalation is open", async () => {
    mockFetch([
      [/\/projects\/[^/]+\/runs$/, () => []],
      [
        /\/projects\/[^/]+\/escalations/,
        () => [
          {
            id: "e1",
            project_id: PROJECT_ID,
            run_id: "run-1",
            trigger: "ambiguous_scope",
            question: "Which population should we focus on?",
            context: null,
            options: [],
            status: "open",
            user_response: null,
            created_at: "2026-06-12T11:30:00Z",
            resolved_at: null,
          },
        ],
      ],
      [/\/projects\/[^/]+$/, () => ({ ...project, status: "awaiting_input" })],
    ]);

    renderAt(<ActivityMonitor />, {
      path: "/projects/:projectId/monitor",
      route: `/projects/${PROJECT_ID}/monitor`,
    });

    const banner = await screen.findByTestId("escalation-banner");
    expect(banner).toHaveTextContent("Which population should we focus on?");
  });

  it("falls back to a polling indicator when the socket is not open", async () => {
    useLiveRun.getState().setConnection("polling");
    renderAt(<ActivityMonitor />, {
      path: "/projects/:projectId/monitor",
      route: `/projects/${PROJECT_ID}/monitor`,
    });
    expect(await screen.findByTestId("polling-fallback")).toBeInTheDocument();
  });
});
