import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { EscalationScreen } from "../screens/Escalation/Escalation";
import { ESCALATION_ID, PROJECT_ID, mockFetch, renderAt } from "./utils";

const openEscalation = {
  id: ESCALATION_ID,
  project_id: PROJECT_ID,
  run_id: "run-1",
  trigger: "unresolved_contradiction",
  question:
    "Two strong studies disagree on the size of the effect. How should the report treat this?",
  context: { summary: "Okeke 2021 reports a large effect; Mensah 2022 finds none." },
  options: [
    {
      id: "report_both",
      label: "Report both and explain the disagreement",
      consequence: "The report stays balanced.",
    },
    { id: "weight_credible", label: "Weight the more credible study" },
  ],
  status: "open",
  user_response: null,
  created_at: "2026-06-12T11:30:00Z",
  resolved_at: null,
};

function routes(resolveSpy: (body: string) => void) {
  return mockFetch([
    [
      /\/escalations\/[^/]+\/resolve$/,
      (_url, init) => {
        resolveSpy(String(init?.body ?? ""));
        return { ...openEscalation, status: "resolved" };
      },
    ],
    [/\/projects\/[^/]+\/escalations\?status=open/, () => [openEscalation]],
    [/\/projects\/[^/]+\/escalations\?status=resolved/, () => []],
    [
      /\/projects\/[^/]+$/,
      () => ({
        id: PROJECT_ID,
        title: "Sleep & immunity",
        status: "awaiting_input",
        original_request: "x",
        research_question: null,
        scope: null,
        audience: null,
        outputs_requested: null,
        budget: null,
        current_stage: null,
        created_at: "2026-06-10T10:00:00Z",
        updated_at: "2026-06-12T10:00:00Z",
      }),
    ],
  ]);
}

beforeEach(() => {
  routes(() => {});
});

describe("Escalation", () => {
  it("renders the open escalation with its question, trigger reason, and the best-judgment option", async () => {
    renderAt(<EscalationScreen />, {
      path: "/projects/:projectId/escalations",
      route: `/projects/${PROJECT_ID}/escalations`,
    });
    expect(await screen.findByTestId("escalation-question")).toHaveTextContent(
      /Two strong studies disagree/,
    );
    expect(screen.getByText(/Why the agent paused/)).toBeInTheDocument();
    expect(screen.getByText(/Report both and explain the disagreement/)).toBeInTheDocument();
    expect(screen.getByText(/proceed with your best judgment/i)).toBeInTheDocument();
  });

  it("resolves the escalation with the chosen option when submitted", async () => {
    let captured = "";
    routes((body) => (captured = body));
    const user = userEvent.setup();

    renderAt(<EscalationScreen />, {
      path: "/projects/:projectId/escalations",
      route: `/projects/${PROJECT_ID}/escalations`,
    });
    await screen.findByTestId("open-escalation");

    await user.click(screen.getByText(/Report both and explain the disagreement/));
    await user.click(screen.getByTestId("resolve-escalation"));

    await waitFor(() => expect(captured).not.toBe(""));
    expect(JSON.parse(captured)).toMatchObject({
      user_response: { selected_option: "report_both" },
    });
  });
});
