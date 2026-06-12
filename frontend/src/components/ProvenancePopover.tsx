// ProvenancePopover — the reusable overlay (screen 13, critical) that any
// claim or citation anywhere can open. Shows the claim → source(s) → passage
// chain, confidence + credibility, an inference flag when applicable, and a
// link to the full analysis / the original. Built as an overlay, not a route.

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useProvenance, useSources } from "../api/hooks";
import { Badge, Callout, Citation, ConfidenceMeter, Icon, IconButton, SourceChip } from "./ds";
import { authorsLine } from "./helpers";
import { ProvenanceCtx, type TraceRequest } from "./provenanceContext";
import { ConfidenceBadge } from "./shared";

function TracePanel({ req, onClose }: { req: TraceRequest; onClose: () => void }) {
  const needFetch = !req.rows;
  const filters = req.refId ? { ref_id: req.refId } : { source_id: req.sourceId };
  const fetched = useProvenance(req.projectId, filters, needFetch);
  const sources = useSources(req.projectId);

  const rows = req.rows ?? fetched.data ?? [];
  const sourceItems = sources.data?.items;
  const sourceById = useMemo(() => {
    const map = new Map<string, NonNullable<typeof sourceItems>[number]>();
    for (const s of sourceItems ?? []) map.set(s.id, s);
    return map;
  }, [sourceItems]);

  return (
    <div
      className="prov-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Provenance trace"
      onClick={onClose}
    >
      <div
        className="prov-panel"
        data-testid="provenance-popover"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="prov-panel__head">
          <div>
            <div className="eyebrow">Provenance</div>
            <h3 className="prov-panel__title">Where this claim comes from</h3>
          </div>
          <IconButton icon="x" label="Close" onClick={onClose} />
        </header>

        {req.claimText && (
          <blockquote className="prov-panel__claim">
            “{req.claimText}”
            {req.confidenceLabel && (
              <span className="prov-panel__claimbadge">
                <ConfidenceBadge label={req.confidenceLabel} />
              </span>
            )}
          </blockquote>
        )}

        {needFetch && fetched.isLoading && <p className="muted-note">Tracing…</p>}

        {!fetched.isLoading && rows.length === 0 && (
          <p className="muted-note" data-testid="provenance-empty">
            No provenance records found for this claim.
          </p>
        )}

        <div className="prov-panel__chain">
          {rows.map((p) => {
            const source = p.source_id ? sourceById.get(p.source_id) : undefined;
            return (
              <div key={p.id} className="prov-entry" data-testid="provenance-entry">
                <div className="prov-entry__meta">
                  <ConfidenceBadge label={p.confidence_label} />
                  {p.is_inference && (
                    <Badge tone="neutral" icon="sparkles" data-testid="inference-flag">
                      Agent inference
                    </Badge>
                  )}
                  <span className="prov-entry__ctx">{p.context}</span>
                </div>

                {p.claim_text !== req.claimText && (
                  <p className="prov-entry__claim">{p.claim_text}</p>
                )}

                {p.is_inference ? (
                  <Callout tone="insight" title="This is the agent's own synthesis">
                    It is not sourced from a paper; it is flagged as inference rather than blended
                    into sourced findings.
                  </Callout>
                ) : (
                  <>
                    {p.passage && (
                      <div className="prov-entry__passage">
                        <Icon name="quote" size={14} />
                        <span data-testid="provenance-passage">{p.passage}</span>
                      </div>
                    )}
                    {source && (
                      <div className="prov-entry__source">
                        <Citation
                          title={source.title}
                          source={source.venue ?? undefined}
                          meta={`${authorsLine(source.authors)}${source.year ? ` · ${source.year}` : ""}`}
                          href={source.url ?? undefined}
                        />
                        <div className="prov-entry__links">
                          {source.credibility_score != null && (
                            <span className="prov-entry__cred">
                              credibility{" "}
                              <ConfidenceMeter value={source.credibility_score} showLabel={false} />{" "}
                              {Math.round(source.credibility_score * 100)}%
                            </span>
                          )}
                          <Link
                            to={`/projects/${p.project_id}/sources/${source.id}`}
                            onClick={onClose}
                          >
                            Full analysis
                          </Link>
                          {source.url && (
                            <a href={source.url} target="_blank" rel="noreferrer">
                              Original
                            </a>
                          )}
                        </div>
                      </div>
                    )}
                    {!source && p.source_id && (
                      <p className="muted-note">
                        Source <SourceChip n={p.source_id.slice(0, 8)} />
                      </p>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function ProvenanceProvider({ children }: { children: ReactNode }) {
  const [req, setReq] = useState<TraceRequest | null>(null);
  const openTrace = useCallback((r: TraceRequest) => setReq(r), []);
  const value = useMemo(() => ({ openTrace }), [openTrace]);
  return (
    <ProvenanceCtx.Provider value={value}>
      {children}
      {req && <TracePanel req={req} onClose={() => setReq(null)} />}
    </ProvenanceCtx.Provider>
  );
}
