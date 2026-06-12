import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ProvenanceProvider } from "../components/ProvenancePopover";
import { useProvenanceTrace } from "../components/provenanceContext";
import { Button } from "../components/ds";
import { PROJECT_ID, REPORT_ID, mockFetch, provenanceRow, source } from "./utils";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";

function Opener() {
  const { openTrace } = useProvenanceTrace();
  return (
    <Button
      onClick={() =>
        openTrace({
          projectId: PROJECT_ID,
          refId: REPORT_ID,
          claimText: "Sleep restriction raises IL-6.",
        })
      }
    >
      trace
    </Button>
  );
}

function renderOverlay() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProvenanceProvider>
          <Opener />
        </ProvenanceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockFetch([
    [/\/projects\/[^/]+\/provenance/, () => [provenanceRow]],
    [/\/projects\/[^/]+\/sources/, () => ({ items: [source], total: 1, limit: 500, offset: 0 })],
  ]);
});

describe("ProvenancePopover", () => {
  it("opens on demand and shows the claim → passage → source chain", async () => {
    const user = userEvent.setup();
    renderOverlay();
    await user.click(screen.getByText("trace"));

    const panel = await screen.findByTestId("provenance-popover");
    expect(panel).toHaveTextContent("Sleep restriction raises IL-6.");
    expect(await screen.findByTestId("provenance-passage")).toHaveTextContent("IL-6 rose 1.8-fold");
    expect(screen.getByText(source.title)).toBeInTheDocument();
  });

  it("flags an agent inference instead of showing a source passage", async () => {
    mockFetch([
      [
        /\/projects\/[^/]+\/provenance/,
        () => [
          {
            ...provenanceRow,
            id: "p2",
            is_inference: true,
            source_id: null,
            passage: null,
            confidence_label: "speculative",
          },
        ],
      ],
      [/\/projects\/[^/]+\/sources/, () => ({ items: [], total: 0, limit: 500, offset: 0 })],
    ]);
    const user = userEvent.setup();
    renderOverlay();
    await user.click(screen.getByText("trace"));
    expect(await screen.findByTestId("inference-flag")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("provenance-passage")).not.toBeInTheDocument());
  });
});
