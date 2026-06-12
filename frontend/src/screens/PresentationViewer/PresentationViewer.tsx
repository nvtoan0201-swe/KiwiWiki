// Screen 12 — Presentation viewer. Slide sequence with the through-line shown
// explicitly, per-slide headline + evidence + rendered visual spec, speaker
// notes, reorder controls (client-side), and pptx/md export.

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import { usePresentation } from "../../api/hooks";
import type { Slide, VisualSpec } from "../../api/types";
import { Badge, Button, Card, Icon, IconButton, SourceChip } from "../../components/ds";
import { useProvenanceTrace } from "../../components/ProvenancePopover";
import { EmptyState } from "../../components/shared";

function Visual({ spec }: { spec: VisualSpec | null | undefined }) {
  if (!spec) return null;
  if (spec.type === "comparison_table" && (spec.rows ?? []).length > 0) {
    return (
      <div className="slide-visual">
        {spec.title && <div className="slide-visual__title">{spec.title}</div>}
        <table className="matrix">
          <thead>
            <tr>
              {(spec.columns ?? []).map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(spec.rows ?? []).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  const points = spec.points ?? [];
  if (points.length === 0) return null;
  const icon = spec.type === "timeline" ? "calendar-range" : spec.type === "trend" ? "trending-up" : "list";
  return (
    <div className="slide-visual">
      {spec.title && (
        <div className="slide-visual__title">
          <Icon name={icon} size={14} /> {spec.title}
        </div>
      )}
      <ul className="slide-visual__points">
        {points.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
    </div>
  );
}

export function PresentationViewer() {
  const { projectId } = useParams<{ projectId: string }>();
  const presentations = usePresentation(projectId);
  const { openTrace } = useProvenanceTrace();

  const deck = (presentations.data ?? [])[0];
  const [order, setOrder] = useState<number[]>([]);
  const [active, setActive] = useState(0);
  const [showNotes, setShowNotes] = useState(true);

  const slides = (deck?.slides ?? []) as Slide[];
  useEffect(() => {
    setOrder(slides.map((_, i) => i));
    setActive(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck?.id, slides.length]);

  if (presentations.isLoading) return <p className="muted-note screen">Loading presentation…</p>;
  if (!deck) {
    return (
      <div className="screen">
        <EmptyState icon="presentation" title="No presentation yet">
          The presentation is a re-authoring of the findings — through-line first — generated after
          the report.
        </EmptyState>
      </div>
    );
  }

  const move = (pos: number, dir: -1 | 1) => {
    setOrder((prev) => {
      const next = [...prev];
      const target = pos + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[pos], next[target]] = [next[target], next[pos]];
      return next;
    });
    setActive((a) => (a === pos ? pos + dir : a));
  };

  const keyMessages = (deck.key_messages ?? []).map((m) =>
    typeof m === "string" ? m : m.message,
  );
  const activeSlide = slides[order[active] ?? 0];

  return (
    <div className="screen">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Presentation · v{deck.version}</div>
          <h1 className="screen-title">Slides</h1>
        </div>
        <div className="screen-head__side report-toolbar">
          <Button variant="ghost" size="sm" onClick={() => setShowNotes((s) => !s)}>
            {showNotes ? "Hide" : "Show"} speaker notes
          </Button>
          <a href={api.presentationExportUrl(deck.id, "pptx")} download>
            <Button variant="secondary" size="sm" iconLeft="download">
              .pptx
            </Button>
          </a>
          <a href={api.presentationExportUrl(deck.id, "md")} download>
            <Button variant="ghost" size="sm" iconLeft="download">
              .md
            </Button>
          </a>
        </div>
      </header>

      {deck.through_line && (
        <Card pad className="throughline" data-testid="through-line">
          <div className="eyebrow">Through-line</div>
          <p className="throughline__text">{deck.through_line}</p>
          {keyMessages.length > 0 && (
            <ol className="throughline__messages">
              {keyMessages.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ol>
          )}
        </Card>
      )}

      <div className="deck-grid">
        <ol className="deck-rail" aria-label="Slides">
          {order.map((slideIdx, pos) => {
            const s = slides[slideIdx];
            if (!s) return null;
            return (
              <li
                key={slideIdx}
                className={`deck-rail__item${pos === active ? " deck-rail__item--on" : ""}`}
              >
                <button className="deck-rail__btn" onClick={() => setActive(pos)}>
                  <span className="deck-rail__num">{pos + 1}</span>
                  <span className="deck-rail__headline">{s.headline}</span>
                </button>
                <span className="deck-rail__controls">
                  <IconButton icon="chevron-up" label="Move up" size="sm" onClick={() => move(pos, -1)} />
                  <IconButton
                    icon="chevron-down"
                    label="Move down"
                    size="sm"
                    onClick={() => move(pos, 1)}
                  />
                </span>
              </li>
            );
          })}
        </ol>

        {activeSlide && (
          <div className="deck-stage">
            <Card pad className="slide" data-testid="active-slide">
              {activeSlide.key_message_index != null && keyMessages[activeSlide.key_message_index] && (
                <Badge tone="accent" icon="target">
                  Key message {activeSlide.key_message_index + 1}
                </Badge>
              )}
              <h2 className="slide__headline">{activeSlide.headline}</h2>
              <ul className="slide__evidence">
                {(activeSlide.evidence ?? []).map((e, i) => (
                  <li key={i}>
                    {e.text}{" "}
                    {e.is_inference ? (
                      <Badge tone="neutral" icon="sparkles">
                        Inference
                      </Badge>
                    ) : (
                      (e.source_ids ?? []).map((id, j) => (
                        <SourceChip
                          key={id}
                          n={j + 1}
                          role="button"
                          onClick={() =>
                            openTrace({ projectId: projectId!, sourceId: id, claimText: e.text })
                          }
                        />
                      ))
                    )}
                  </li>
                ))}
              </ul>
              <Visual spec={activeSlide.visual} />
            </Card>

            {showNotes && activeSlide.speaker_notes && (
              <Card pad className="slide-notes">
                <div className="eyebrow">Speaker notes</div>
                <p className="screen-body">{activeSlide.speaker_notes}</p>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
