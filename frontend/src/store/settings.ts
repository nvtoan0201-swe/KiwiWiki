// User defaults (Budget & Settings screen). The backend has no settings
// resource, so these are client-side defaults persisted to localStorage and
// applied when composing a new research request.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type EscalationSensitivity = "ask_more" | "balanced" | "ask_less";

export interface SettingsState {
  defaultBudget: { llm_tokens: number; search_calls: number; papers_read: number; time: number };
  defaultAudience: string;
  defaultOutputs: string[];
  recentYears: number;
  escalationSensitivity: EscalationSensitivity;
  preferredSources: string[];
  notifyRunComplete: boolean;
  notifyBudgetApproaching: boolean;
  notifySignificantFindings: boolean;
  update: (patch: Partial<Omit<SettingsState, "update">>) => void;
}

export const DEFAULT_SETTINGS = {
  defaultBudget: { llm_tokens: 2_000_000, search_calls: 100, papers_read: 60, time: 3600 },
  defaultAudience: "domain_expert",
  defaultOutputs: ["report", "presentation"],
  recentYears: 5,
  escalationSensitivity: "balanced" as EscalationSensitivity,
  preferredSources: ["openalex", "arxiv", "semantic_scholar", "crossref"],
  notifyRunComplete: true,
  notifyBudgetApproaching: true,
  notifySignificantFindings: false,
};

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_SETTINGS,
      update: (patch) => set(patch),
    }),
    { name: "kiwiwiki-settings" },
  ),
);
