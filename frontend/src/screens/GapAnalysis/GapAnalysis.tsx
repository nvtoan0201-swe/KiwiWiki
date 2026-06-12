// Screen 10 — Gap analysis. Gap list with supporting-evidence links,
// importance, confidence; future directions clearly marked speculative;
// links back to clusters/papers.

import { Link, useParams } from "react-router-dom";

import { useGaps } from "../../api/hooks";
import type { Gap } from "../../api/types";
import { Badge, Callout, Card, SourceChip, type BadgeTone } from "../../components/ds";
import { useProvenanceTrace } from "../../components/provenanceContext";
import { ConfidenceBadge, EmptyState } from "../../components/shared";

const IMPORTANCE_TONE: Record<string, BadgeTone> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

function GapCard({ gap, projectId }: { gap: Gap; projectId: string }) {
  const { openTrace } = useProvenanceTrace();
  const ev = gap.supporting_evidence;
  return (
    <Card pad className="gap-card" data-testid={`gap-${gap.id}`}>
      <div className="gap-card__head">
        {gap.importance && (
          <Badge tone={IMPORTANCE_TONE[gap.importance]}>{gap.importance} importance</Badge>
        )}
        <ConfidenceBadge label={gap.confidence_label} />
        {ev?.gap_type && <Badge tone="neutral">{ev.gap_type.replace(/_/g, " ")}</Badge>}
      </div>
      <p className="screen-body gap-card__desc">{gap.description}</p>
      {ev?.evidence && <p className="gap-card__evidence">Why this is a gap: {ev.evidence}</p>}
      <div className="gap-card__links">
        {(ev?.source_ids ?? []).map((id, i) => (
          <SourceChip
            key={id}
            n={i + 1}
            role="button"
            onClick={() => openTrace({ projectId, refId: gap.id, claimText: gap.description })}
          />
        ))}
        <button
          className="linklike"
          onClick={() => openTrace({ projectId, refId: gap.id, claimText: gap.description })}
        >
          Trace evidence
        </button>
        <Link to={`/projects/${projectId}/fieldmap`} className="muted-note">
          See it on the field map
        </Link>
      </div>
    </Card>
  );
}

export function GapAnalysis() {
  const { projectId } = useParams<{ projectId: string }>();
  const gaps = useGaps(projectId);

  if (gaps.isLoading) return <p className="muted-note screen">Loading gaps…</p>;

  const all = gaps.data ?? [];
  const futureDirections = all.filter((g) => g.supporting_evidence?.type === "future_direction");
  const realGaps = all.filter((g) => g.supporting_evidence?.type !== "future_direction");

  return (
    <div className="screen">
      <header className="screen-head">
        <div className="eyebrow">Gap analysis</div>
        <h1 className="screen-title">What the field hasn't answered</h1>
      </header>

      {all.length === 0 && (
        <EmptyState icon="puzzle" title="No gaps recorded yet">
          The gap-analysis stage synthesizes these after the field map is built.
        </EmptyState>
      )}

      <div className="gap-grid">
        {realGaps.map((g) => (
          <GapCard key={g.id} gap={g} projectId={projectId!} />
        ))}
      </div>

      {futureDirections.length > 0 && (
        <section className="future-directions" data-testid="future-directions">
          <h3>Future directions</h3>
          <Callout tone="insight" title="Speculative — the agent's own synthesis">
            These are inferences about where the field could go, not findings from any paper. They
            are flagged as speculative everywhere they appear.
          </Callout>
          <div className="gap-grid">
            {futureDirections.map((g) => (
              <Card key={g.id} pad className="gap-card gap-card--speculative">
                <div className="gap-card__head">
                  <ConfidenceBadge label="speculative" />
                  <Badge tone="neutral" icon="sparkles">
                    Inference
                  </Badge>
                </div>
                <p className="screen-body">{g.description}</p>
                {g.supporting_evidence?.rationale && (
                  <p className="gap-card__evidence">{g.supporting_evidence.rationale}</p>
                )}
              </Card>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
