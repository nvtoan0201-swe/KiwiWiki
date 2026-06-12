import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ReportViewer } from "../screens/ReportViewer/ReportViewer";
import {
  PROJECT_ID,
  REPORT_ID,
  SOURCE_ID,
  mockFetch,
  provenanceRow,
  renderAt,
  source,
} from "./utils";

const report = {
  id: REPORT_ID,
  project_id: PROJECT_ID,
  audience: "domain_expert",
  content_markdown: `## Findings\n\nSleep restriction raises IL-6 [^src:${SOURCE_ID}]. *(confidence: emerging)*\n\nThe mechanism is the agent's best reading. *(confidence: speculative; inference)*\n`,
  self_check_result: {
    summary: "One overstated claim was softened.",
    findings: [{ issue: "overstated", action: "soften", note: "Hedged the causal language." }],
  },
  stopping_criterion: "saturation",
  version: 2,
};

beforeEach(() => {
  mockFetch([
    [/\/projects\/[^/]+\/reports$/, () => [report]],
    [/\/projects\/[^/]+\/provenance/, () => [provenanceRow]],
    [/\/projects\/[^/]+\/sources/, () => ({ items: [source], total: 1, limit: 500, offset: 0 })],
  ]);
});

describe("ReportViewer", () => {
  it("renders the report with confidence badges, self-check, and the stopping criterion", async () => {
    renderAt(<ReportViewer />, {
      path: "/projects/:projectId/report",
      route: `/projects/${PROJECT_ID}/report`,
    });

    const body = await screen.findByTestId("report-body");
    expect(body).toHaveTextContent("Sleep restriction raises IL-6");
    expect(screen.getByTestId("confidence-emerging")).toBeInTheDocument();
    expect(screen.getByTestId("inline-inference")).toBeInTheDocument();
    expect(screen.getByTestId("self-check")).toHaveTextContent(/softened/);
    expect(screen.getByTestId("stopping-criterion")).toHaveTextContent(/saturation/);
  });

  it("resolves a citation marker via the provenance overlay", async () => {
    renderAt(<ReportViewer />, {
      path: "/projects/:projectId/report",
      route: `/projects/${PROJECT_ID}/report`,
    });

    const chip = await screen.findByTestId(`citation-${SOURCE_ID}`);
    expect(chip).toHaveTextContent("1");
    fireEvent.click(chip);

    expect(await screen.findByTestId("provenance-popover")).toBeInTheDocument();
    expect(await screen.findByTestId("provenance-passage")).toHaveTextContent("IL-6 rose 1.8-fold");
  });

  it("offers docx and md export links", async () => {
    renderAt(<ReportViewer />, {
      path: "/projects/:projectId/report",
      route: `/projects/${PROJECT_ID}/report`,
    });
    await screen.findByTestId("report-body");
    const docx = screen.getByText(".docx").closest("a");
    expect(docx).toHaveAttribute(
      "href",
      expect.stringContaining(`/reports/${REPORT_ID}/export?format=docx`),
    );
    const md = screen.getByText(".md").closest("a");
    expect(md).toHaveAttribute("href", expect.stringContaining("format=md"));
  });
});
