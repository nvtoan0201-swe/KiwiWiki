// Test helpers: render a screen with the app's providers (Query, Router,
// Provenance overlay) and a small URL-pattern fetch mock so screens exercise
// the real client + hooks rather than mocked modules.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { ProvenanceProvider } from "../components/ProvenancePopover";

export const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
export const SOURCE_ID = "22222222-2222-2222-2222-222222222222";
export const REPORT_ID = "33333333-3333-3333-3333-333333333333";
export const ESCALATION_ID = "44444444-4444-4444-4444-444444444444";

export function renderAt(ui: ReactElement, { path, route }: { path: string; route: string }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ProvenanceProvider>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="*" element={<div>elsewhere</div>} />
          </Routes>
        </ProvenanceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** A fetch mock that matches request URLs against [pattern, responder] pairs. */
export function mockFetch(routes: Array<[RegExp, (url: string, init?: RequestInit) => unknown]>) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [pattern, responder] of routes) {
      if (pattern.test(url)) {
        const body = responder(url, init);
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ error: { code: "not_found", message: url } }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const source = {
  id: SOURCE_ID,
  project_id: PROJECT_ID,
  title: "Sleep loss and cytokine response",
  authors: ["Okeke, R.", "Mensah, A."],
  venue: "Journal of Sleep Research",
  year: 2021,
  doi: "10.1/sleep",
  url: "https://example.org/paper",
  abstract: "A controlled study of sleep restriction and inflammatory markers.",
  discovery_channel: "keyword_search",
  relevance_score: 0.88,
  credibility_score: 0.72,
  triage_status: "deep_read",
  triage_reason: "Directly on topic.",
  cluster_id: null,
  created_at: "2026-06-10T10:00:00Z",
  updated_at: "2026-06-12T10:00:00Z",
};

export const provenanceRow = {
  id: "prov-1",
  project_id: PROJECT_ID,
  claim_text: "Sleep restriction raises IL-6.",
  source_id: SOURCE_ID,
  passage: "IL-6 rose 1.8-fold after two nights of 4h sleep.",
  is_inference: false,
  confidence_label: "emerging",
  context: "report",
  ref_id: REPORT_ID,
};
