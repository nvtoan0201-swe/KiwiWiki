// Screen 8 — Paper analysis detail. Bibliographic header, the structured
// record (claim / method / results-with-numbers / datasets / author
// limitations), the agent critique clearly labelled as inference, the
// credibility breakdown, contradiction flags linking to conflicting papers,
// and provenance links per point.

import { Link, useParams } from "react-router-dom";

import { useAnalysis, useSourceOverride } from "../../api/hooks";
import type { CredibilityComponent } from "../../api/types";
import { Badge, Button, Callout, Card, ConfidenceMeter, Icon } from "../../components/ds";
import { useProvenanceTrace } from "../../components/ProvenancePopover";
import { ConfidenceBadge, EmptyState, authorsLine } from "../../components/shared";

const CRED_LABELS: Record<string, string> = {
  venue_quality: "Venue quality",
  sample_size_power: "Sample size & power",
  methodology_rigor: "Methodology rigor",
  conflicts_of_interest: "Conflicts of interest",
  replication_status: "Replication status",
};

function PassageLink({
  projectId,
  sourceId,
  claim,
}: {
  projectId: string;
  sourceId: string;
  claim: string;
}) {
  const { openTrace } = useProvenanceTrace();
  return (
    <button
      className="linklike"
      title="Show the supporting passage"
      onClick={() => openTrace({ projectId, sourceId, claimText: claim })}
    >
      <Icon name="quote" size={12} /> provenance
    </button>
  );
}

export function PaperAnalysisDetail() {
  const { projectId, sourceId } = useParams<{ projectId: string; sourceId: string }>();
  const detail = useAnalysis(sourceId);
  const override = useSourceOverride(projectId ?? "");

  if (detail.isLoading) return <p className="muted-note screen">Loading analysis…</p>;
  if (!detail.data) {
    return (
      <div className="screen">
        <EmptyState icon="alert-triangle" title="Source not found" />
      </div>
    );
  }

  const { source, analysis, contradictions } = detail.data;

  return (
    <div className="screen screen--reading">
      <Link to={`/projects/${projectId}/sources`} className="backlink">
        <Icon name="arrow-left" size={14} /> Source library
      </Link>

      <header className="paper-head">
        <div className="eyebrow">Paper analysis</div>
        <h1 className="paper-head__title">{source.title}</h1>
        <p className="paper-head__byline">
          {authorsLine(source.authors)}
          {source.year ? ` · ${source.year}` : ""}
          {source.venue ? ` · ${source.venue}` : ""}
          {source.doi ? ` · DOI ${source.doi}` : ""}
        </p>
        <div className="paper-head__badges">
          {analysis?.confidence_label && <ConfidenceBadge label={analysis.confidence_label} />}
          {source.credibility_score != null && (
            <span className="paper-head__cred">
              credibility <ConfidenceMeter value={source.credibility_score} showLabel={false} />{" "}
              {Math.round(source.credibility_score * 100)}%
            </span>
          )}
          {source.url && (
            <a href={source.url} target="_blank" rel="noreferrer">
              Original <Icon name="external-link" size={12} />
            </a>
          )}
        </div>
        <div className="paper-head__actions">
          {source.triage_status !== "deep_read" && (
            <Button
              variant="secondary"
              size="sm"
              iconLeft="arrow-up"
              onClick={() => override.mutate({ sourceId: source.id, body: { action: "promote" } })}
            >
              Promote to deep read
            </Button>
          )}
          {source.triage_status !== "excluded" && (
            <Button
              variant="ghost"
              size="sm"
              iconLeft="x"
              onClick={() => override.mutate({ sourceId: source.id, body: { action: "exclude" } })}
            >
              Exclude
            </Button>
          )}
        </div>
      </header>

      {!analysis && (
        <EmptyState icon="hourglass" title="Not analyzed yet">
          This source has not been through paper analysis. Promote it to deep read to queue it.
          {source.abstract && <p className="screen-body">{source.abstract}</p>}
        </EmptyState>
      )}

      {analysis && (
        <>
          <Card pad className="paper-section">
            <h4>Core claim</h4>
            <p className="screen-body" data-testid="core-claim">
              {analysis.core_claim ?? "—"}{" "}
              {analysis.core_claim && (
                <PassageLink projectId={projectId!} sourceId={source.id} claim={analysis.core_claim} />
              )}
            </p>
            <h4>Method</h4>
            <p className="screen-body">
              {analysis.method ?? "—"}{" "}
              {analysis.method && (
                <PassageLink projectId={projectId!} sourceId={source.id} claim={analysis.method} />
              )}
            </p>
          </Card>

          {(analysis.results ?? []).length > 0 && (
            <Card pad className="paper-section">
              <h4>Results</h4>
              <ul className="paper-results">
                {(analysis.results ?? []).map((r, i) => (
                  <li key={i}>
                    {r.finding}
                    {r.numbers && <code className="paper-results__nums">{r.numbers}</code>}{" "}
                    <PassageLink projectId={projectId!} sourceId={source.id} claim={r.finding} />
                  </li>
                ))}
              </ul>
              {(analysis.datasets ?? []).length > 0 && (
                <p className="muted-note">Datasets: {(analysis.datasets ?? []).join(", ")}</p>
              )}
            </Card>
          )}

          {(analysis.author_limitations ?? []).length > 0 && (
            <Card pad className="paper-section">
              <h4>Limitations the authors acknowledge</h4>
              <ul>
                {(analysis.author_limitations ?? []).map((l, i) => (
                  <li key={i} className="screen-body">
                    {l.limitation}{" "}
                    <PassageLink projectId={projectId!} sourceId={source.id} claim={l.limitation} />
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {analysis.agent_critique && (
            <Callout tone="insight" title="Agent critique — inference, not sourced" data-testid="agent-critique">
              <Badge tone="neutral" icon="sparkles" data-testid="critique-inference-flag">
                Agent inference
              </Badge>
              <p className="screen-body" style={{ marginTop: 8 }}>
                {analysis.agent_critique}
              </p>
            </Callout>
          )}

          {analysis.credibility_breakdown && (
            <Card pad className="paper-section">
              <h4>Credibility breakdown</h4>
              <p className="muted-note">
                Scores reflect the method, not the confidence of the framing.
              </p>
              <div className="cred-breakdown">
                {Object.entries(analysis.credibility_breakdown)
                  .filter(([k]) => k in CRED_LABELS)
                  .map(([key, value]) => {
                    const comp = value as CredibilityComponent;
                    return (
                      <div key={key} className="cred-breakdown__row">
                        <span className="cred-breakdown__label">{CRED_LABELS[key]}</span>
                        <ConfidenceMeter value={comp.score ?? 0} showLabel={false} />
                        <span className="cred-breakdown__note">
                          {comp.known === false ? "unknown — scored conservatively" : comp.note}
                        </span>
                      </div>
                    );
                  })}
              </div>
              {typeof analysis.credibility_breakdown.summary === "string" && (
                <p className="screen-body">{analysis.credibility_breakdown.summary}</p>
              )}
            </Card>
          )}
        </>
      )}

      {contradictions.length > 0 && (
        <Card pad className="paper-section">
          <h4>Contradiction flags</h4>
          {contradictions.map((c) => {
            const otherId = c.source_a_id === source.id ? c.source_b_id : c.source_a_id;
            return (
              <Callout key={c.id} tone="warning" title="Disagrees with another paper">
                <p className="screen-body">{c.description}</p>
                <Link to={`/projects/${projectId}/sources/${otherId}`}>Open the conflicting paper</Link>
                {c.resolved && c.resolution && (
                  <p className="muted-note">Resolved in comparison: {c.resolution}</p>
                )}
                {!c.resolved && (
                  <p className="muted-note">
                    Not resolved here — the comparison stage investigates why they disagree.
                  </p>
                )}
              </Callout>
            );
          })}
        </Card>
      )}
    </div>
  );
}
