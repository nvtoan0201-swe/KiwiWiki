// Pure helpers and shared constant maps (no components) so the component
// modules stay clean refresh boundaries.

import type { ConfidenceLabel } from "../api/types";
import type { BadgeTone } from "./ds";

export const CONFIDENCE_META: Record<
  ConfidenceLabel,
  { label: string; tone: BadgeTone; icon: string }
> = {
  well_established: { label: "Well established", tone: "positive", icon: "check-check" },
  emerging: { label: "Emerging", tone: "info", icon: "trending-up" },
  contested: { label: "Contested", tone: "warning", icon: "git-compare" },
  speculative: { label: "Speculative", tone: "neutral", icon: "lightbulb" },
};

const MARKER_RE = /\[\^src:([0-9a-fA-F-]{8,36})\]/g;

/** Source ids cited in report markdown, in first-appearance order, deduped. */
export function citedSourceIds(markdown: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const match of markdown.matchAll(MARKER_RE)) {
    if (!seen.has(match[1])) {
      seen.add(match[1]);
      out.push(match[1]);
    }
  }
  return out;
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return date.toLocaleDateString();
}

export function authorsLine(authors: string[] | null): string {
  if (!authors || authors.length === 0) return "Unknown authors";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors[0]} et al.`;
}
