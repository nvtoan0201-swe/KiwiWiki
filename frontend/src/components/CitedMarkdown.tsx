// Renders the canonical report markdown. Two report-specific notations are
// resolved while rendering (mirrors backend services/citations.py):
//   [^src:<source-id>]            → numbered SourceChip that opens provenance
//   *(confidence: <label>[; inference])* → ConfidenceBadge (+ inference badge)

import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ConfidenceLabel } from "../api/types";
import { Badge, SourceChip } from "./ds";
import { ConfidenceBadge } from "./shared";

const MARKER_RE = /\[\^src:([0-9a-fA-F-]{8,36})\]/g;
const CONFIDENCE_RE = /^\(confidence: ([a-z ]+?)((?:; inference)?)\)$/;

const TEXT_TO_LABEL: Record<string, ConfidenceLabel> = {
  "well established": "well_established",
  emerging: "emerging",
  contested: "contested",
  speculative: "speculative",
};

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

export interface CitedMarkdownProps {
  markdown: string;
  /** source id → citation number (first-appearance order). */
  numbering: Map<string, number>;
  onCite?: (sourceId: string) => void;
}

function replaceMarkers(
  node: ReactNode,
  numbering: Map<string, number>,
  onCite?: (sourceId: string) => void,
): ReactNode {
  return Children.map(node, (child) => {
    if (typeof child === "string") {
      const parts: ReactNode[] = [];
      let last = 0;
      for (const match of child.matchAll(MARKER_RE)) {
        const idx = match.index ?? 0;
        if (idx > last) parts.push(child.slice(last, idx));
        const sourceId = match[1];
        parts.push(
          <SourceChip
            key={`${sourceId}-${idx}`}
            n={numbering.get(sourceId) ?? "?"}
            role="button"
            tabIndex={0}
            data-testid={`citation-${sourceId}`}
            title="Trace this claim to its source"
            onClick={() => onCite?.(sourceId)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onCite?.(sourceId);
            }}
          />,
        );
        last = idx + match[0].length;
      }
      if (parts.length === 0) return child;
      if (last < child.length) parts.push(child.slice(last));
      return <>{parts}</>;
    }
    return child;
  });
}

export function CitedMarkdown({ markdown, numbering, onCite }: CitedMarkdownProps) {
  return (
    <div className="cited-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{replaceMarkers(children, numbering, onCite)}</p>,
          li: ({ children }) => <li>{replaceMarkers(children, numbering, onCite)}</li>,
          td: ({ children }) => <td>{replaceMarkers(children, numbering, onCite)}</td>,
          em: ({ children }) => {
            const text = Children.toArray(children)
              .map((c) => (typeof c === "string" ? c : isValidElement(c) ? "" : String(c ?? "")))
              .join("");
            const match = CONFIDENCE_RE.exec(text);
            if (match) {
              const label = TEXT_TO_LABEL[match[1]];
              const inference = match[2].length > 0;
              return (
                <span className="cited-markdown__conf">
                  {label && <ConfidenceBadge label={label} />}
                  {inference && (
                    <Badge tone="neutral" icon="sparkles" data-testid="inline-inference">
                      Inference
                    </Badge>
                  )}
                </span>
              );
            }
            return <em>{replaceMarkers(children, numbering, onCite)}</em>;
          },
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
