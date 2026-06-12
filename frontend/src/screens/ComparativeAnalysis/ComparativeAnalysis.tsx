// Screen 9 — Comparative analysis (field map). Cluster view with
// characterizations; the comparison matrix (clusters × dimensions) with
// source-linked cells; the consensus vs. contested split; per-contested-point
// the why-investigation and resolution / "it depends"; link into Gaps.

import { Link, useParams } from "react-router-dom";

import { useComparison, useSources } from "../../api/hooks";
import { Badge, Button, Callout, Card, SourceChip } from "../../components/ds";
import { useProvenanceTrace } from "../../components/ProvenancePopover";
import { ConfidenceBadge, EmptyState } from "../../components/shared";

export function ComparativeAnalysis() {
  const { projectId } = useParams<{ projectId: string }>();
  const fieldMap = useComparison(projectId);
  const sources = useSources(projectId);
  const { openTrace } = useProvenanceTrace();

  if (fieldMap.isLoading) return <p className="muted-note screen">Loading field map…</p>;

  const data = fieldMap.data;
  if (!data || (data.clusters.length === 0 && !data.comparison)) {
    return (
      <div className="screen">
        <EmptyState icon="layers" title="No field map yet">
          The comparative-analysis stage builds the cluster map and matrix after enough papers are
          analyzed.
        </EmptyState>
      </div>
    );
  }

  const sourceTitle = (id: string) =>
    sources.data?.items.find((s) => s.id === id)?.title ?? id.slice(0, 8);

  const matrix = data.comparison?.matrix ?? null;
  const consensus = data.comparison?.consensus_points ?? [];
  const contested = data.comparison?.contested_points ?? [];

  const cellFor = (clusterId: string, dimension: string) =>
    matrix?.cells.find((c) => c.cluster_id === clusterId && c.dimension === dimension);

  const citeChips = (statement: string, ids?: string[]) =>
    (ids ?? []).map((id, i) => (
      <SourceChip
        key={id}
        n={i + 1}
        title={sourceTitle(id)}
        role="button"
        onClick={() =>
          openTrace({ projectId: projectId!, sourceId: id, claimText: statement })
        }
      />
    ));

  return (
    <div className="screen">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Field map</div>
          <h1 className="screen-title">How the field divides</h1>
        </div>
        <Link to={`/projects/${projectId}/gaps`}>
          <Button variant="secondary" iconRight="arrow-right">
            What's missing — gaps
          </Button>
        </Link>
      </header>

      <section className="cluster-grid">
        {data.clusters.map((cluster) => (
          <Card key={cluster.id} pad className="cluster-card" data-testid={`cluster-${cluster.id}`}>
            <h4>{cluster.label}</h4>
            {cluster.description && <p className="screen-body">{cluster.description}</p>}
            {Array.isArray(cluster.defining_characteristics) && (
              <ul className="cluster-card__traits">
                {(cluster.defining_characteristics as string[]).map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
            )}
            <Link to={`/projects/${projectId}/sources?cluster=${cluster.id}`} className="muted-note">
              Sources in this cluster
            </Link>
          </Card>
        ))}
      </section>

      {matrix && matrix.dimensions.length > 0 && (
        <Card pad className="matrix-card">
          <h4>Comparison matrix</h4>
          <p className="muted-note">
            Dimensions come from what the papers actually contest. Cells cite their sources; empty
            cells mean the cluster has nothing on that dimension.
          </p>
          <div className="matrix-scroll">
            <table className="matrix" data-testid="comparison-matrix">
              <thead>
                <tr>
                  <th>Cluster</th>
                  {matrix.dimensions.map((d) => (
                    <th key={d}>{d}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.clusters.map((cl) => (
                  <tr key={cl.id}>
                    <th>{cl.label}</th>
                    {matrix.dimensions.map((dim) => {
                      const cell = cellFor(cl.id, dim);
                      return (
                        <td key={dim} className={cell?.empty !== false ? "matrix__empty" : ""}>
                          {cell && !cell.empty ? (
                            <>
                              <span className="matrix__summary">{cell.summary}</span>
                              <span className="matrix__cites">
                                {citeChips(cell.summary ?? "", cell.source_ids)}
                                {cell.confidence_label && (
                                  <ConfidenceBadge label={cell.confidence_label} />
                                )}
                              </span>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="split-grid">
        <Card pad data-testid="consensus-panel">
          <h4>
            Where the field agrees <Badge tone="positive">{consensus.length}</Badge>
          </h4>
          {consensus.length === 0 && <p className="muted-note">No consensus points recorded.</p>}
          <ul className="pointlist">
            {consensus.map((p, i) => (
              <li key={i}>
                <span className="screen-body">{p.statement}</span>
                <span className="pointlist__meta">
                  {citeChips(p.statement, p.source_ids)}
                  <ConfidenceBadge label={p.confidence_label ?? null} />
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <Card pad data-testid="contested-panel">
          <h4>
            Still contested <Badge tone="warning">{contested.length}</Badge>
          </h4>
          {contested.length === 0 && <p className="muted-note">No contested points recorded.</p>}
          {contested.map((p, i) => (
            <div key={i} className="contested-point">
              <p className="screen-body">
                {p.statement}{" "}
                <span className="pointlist__meta">{citeChips(p.statement, p.source_ids)}</span>
              </p>
              {p.investigation && (
                <Callout tone="note" title="Why they disagree">
                  {p.investigation}
                </Callout>
              )}
              {p.resolution_type === "conditional" && p.resolution && (
                <Callout tone="insight" title="It depends">
                  {p.resolution}
                </Callout>
              )}
              {p.resolution_type === "unresolved" && (
                <p className="muted-note">
                  Unresolved — the evidence cannot settle this yet; the report keeps both readings.
                </p>
              )}
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
