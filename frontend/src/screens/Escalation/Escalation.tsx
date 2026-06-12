// Screen 6 — Escalation (critical). Renders the open escalation: what is
// asked and why the agent paused, the context (with provenance links),
// options as controls + free text, the "proceed with your best judgment"
// option, and consequence text. Submitting resolves and resumes the run.

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useEscalations, useProject, useResolveEscalation } from "../../api/hooks";
import type { Escalation, EscalationTrigger } from "../../api/types";
import { Badge, Button, Callout, Card, Radio, Textarea } from "../../components/ds";
import { useProvenanceTrace } from "../../components/ProvenancePopover";
import { EmptyState, formatWhen } from "../../components/shared";

const TRIGGER_META: Record<EscalationTrigger, { label: string; why: string }> = {
  ambiguous_scope: {
    label: "Ambiguous scope",
    why: "The request can be read more than one way, and the readings lead to different research.",
  },
  thin_literature: {
    label: "Thin literature",
    why: "The agent found too little credible literature to answer well, and wants direction before spending more budget.",
  },
  unresolved_contradiction: {
    label: "Unresolved contradiction",
    why: "Credible sources disagree in a way that changes the conclusion, and the evidence alone cannot settle it.",
  },
  high_stakes: {
    label: "High-stakes call",
    why: "This decision materially shapes the output, so the agent will not make it silently.",
  },
};

const BEST_JUDGMENT = "__best_judgment__";

function ContextBlock({ escalation }: { escalation: Escalation }) {
  const { openTrace } = useProvenanceTrace();
  const ctx = escalation.context;
  if (!ctx) return null;
  const findings = (ctx.conflicting_findings ?? ctx.findings ?? []) as Array<{
    claim?: string;
    statement?: string;
    source_id?: string;
    passage?: string;
  }>;
  return (
    <div className="escalation-context">
      {Array.isArray(findings) && findings.length > 0 && (
        <div className="escalation-context__findings">
          {findings.map((f, i) => (
            <Callout key={i} tone="note" title={f.claim ?? f.statement ?? `Finding ${i + 1}`}>
              {f.passage && <p className="escalation-context__passage">“{f.passage}”</p>}
              {f.source_id && (
                <button
                  className="linklike"
                  onClick={() =>
                    openTrace({
                      projectId: escalation.project_id,
                      sourceId: f.source_id,
                      claimText: f.claim ?? f.statement,
                    })
                  }
                >
                  Trace this to its source
                </button>
              )}
            </Callout>
          ))}
        </div>
      )}
      {typeof ctx.summary === "string" && <p className="screen-body">{ctx.summary}</p>}
      {typeof ctx.note === "string" && <p className="screen-body">{ctx.note}</p>}
    </div>
  );
}

function OpenEscalation({ escalation }: { escalation: Escalation }) {
  const navigate = useNavigate();
  const resolve = useResolveEscalation(escalation.project_id);
  const [selected, setSelected] = useState<string | null>(null);
  const [freeText, setFreeText] = useState("");
  const meta = TRIGGER_META[escalation.trigger];

  // Scoping ambiguities arrive as option groups with their own ids; generic
  // escalations arrive as a flat option list.
  const options = (escalation.options ?? []).filter((o) => o && typeof o === "object");
  const isAmbiguityGroup = options.some((o) => "options" in (o as object));

  const [groupChoices, setGroupChoices] = useState<Record<string, string>>({});

  const submit = async () => {
    const response: Record<string, unknown> = {};
    if (isAmbiguityGroup) {
      response.resolutions = groupChoices;
    } else if (selected === BEST_JUDGMENT) {
      response.selected_option = "best_judgment";
      response.best_judgment = true;
    } else if (selected) {
      response.selected_option = selected;
    }
    if (freeText.trim()) response.note = freeText.trim();
    if (Object.keys(response).length === 0) return;
    await resolve.mutateAsync({ escalationId: escalation.id, response });
    navigate(`/projects/${escalation.project_id}/monitor`);
  };

  const canSubmit = isAmbiguityGroup
    ? Object.keys(groupChoices).length > 0 || freeText.trim().length > 0
    : selected !== null || freeText.trim().length > 0;

  return (
    <Card pad className="form-card" data-testid="open-escalation">
      <div className="escalation-head">
        <Badge tone="warning" icon="message-circle-question" dot>
          {meta.label}
        </Badge>
        <span className="escalation-head__when">raised {formatWhen(escalation.created_at)}</span>
      </div>

      <h3 className="escalation-question" data-testid="escalation-question">
        {escalation.question}
      </h3>
      <p className="escalation-why">
        <strong>Why the agent paused:</strong> {meta.why}
      </p>

      <ContextBlock escalation={escalation} />

      {isAmbiguityGroup ? (
        <div className="scope-ambiguities">
          {options.map((group) => {
            const g = group as {
              id: string;
              question: string;
              why_it_matters?: string;
              options: { id: string; label: string; description?: string }[];
            };
            return (
              <div key={g.id} className="scope-ambiguity">
                <p className="scope-ambiguity__q">{g.question}</p>
                {g.why_it_matters && <p className="scope-ambiguity__why">{g.why_it_matters}</p>}
                {(g.options ?? []).map((o) => (
                  <Radio
                    key={o.id}
                    name={`grp-${g.id}`}
                    label={
                      <>
                        {o.label}
                        {o.description && <span className="option-desc"> — {o.description}</span>}
                      </>
                    }
                    checked={groupChoices[g.id] === o.id}
                    onChange={() => setGroupChoices((prev) => ({ ...prev, [g.id]: o.id }))}
                  />
                ))}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="escalation-options">
          {options.map((opt, i) => {
            const o = opt as { id?: string; label: string; description?: string; consequence?: string };
            const id = o.id ?? String(i);
            return (
              <label key={id} className={`escalation-option${selected === id ? " escalation-option--on" : ""}`}>
                <Radio
                  name="escalation-option"
                  checked={selected === id}
                  onChange={() => setSelected(id)}
                  label={o.label}
                />
                {o.description && <p className="escalation-option__desc">{o.description}</p>}
                {o.consequence && (
                  <p className="escalation-option__consequence">If you choose this: {o.consequence}</p>
                )}
              </label>
            );
          })}
          <label
            className={`escalation-option${selected === BEST_JUDGMENT ? " escalation-option--on" : ""}`}
          >
            <Radio
              name="escalation-option"
              checked={selected === BEST_JUDGMENT}
              onChange={() => setSelected(BEST_JUDGMENT)}
              label="Proceed with your best judgment"
            />
            <p className="escalation-option__desc">
              The agent decides, records its reasoning in the audit log, and flags the assumption in
              the output.
            </p>
          </label>
        </div>
      )}

      <Textarea
        label="Or answer in your own words"
        rows={2}
        placeholder="Anything the agent should know…"
        value={freeText}
        onChange={(e) => setFreeText(e.target.value)}
      />

      <div className="form-actions">
        <Button onClick={submit} disabled={!canSubmit || resolve.isPending} data-testid="resolve-escalation">
          {resolve.isPending ? "Resuming…" : "Answer and resume the run"}
        </Button>
      </div>
    </Card>
  );
}

export function EscalationScreen() {
  const { projectId } = useParams<{ projectId: string }>();
  const project = useProject(projectId);
  const open = useEscalations(projectId, "open");
  const resolved = useEscalations(projectId, "resolved");

  if (open.isLoading) return <p className="muted-note screen">Loading…</p>;

  return (
    <div className="screen screen--form">
      <header className="screen-head">
        <div className="eyebrow">Questions from the agent</div>
        <h1 className="screen-title">{project.data?.title ?? "Escalations"}</h1>
      </header>

      {(open.data ?? []).length === 0 && (
        <EmptyState icon="check-check" title="Nothing is waiting on you">
          The run continues autonomously; it pauses here only for scope ambiguity, thin literature,
          unresolved contradictions, or high-stakes calls.
        </EmptyState>
      )}

      {(open.data ?? []).map((e) => (
        <OpenEscalation key={e.id} escalation={e} />
      ))}

      {(resolved.data ?? []).length > 0 && (
        <section className="escalation-history">
          <h4>Previously answered</h4>
          {(resolved.data ?? []).map((e) => (
            <Card key={e.id} pad className="escalation-historyitem">
              <div className="escalation-head">
                <Badge tone="neutral">{TRIGGER_META[e.trigger].label}</Badge>
                <span className="escalation-head__when">resolved {formatWhen(e.resolved_at)}</span>
              </div>
              <p className="screen-body">{e.question}</p>
              {e.user_response && (
                <p className="muted-note">Your answer: {JSON.stringify(e.user_response)}</p>
              )}
            </Card>
          ))}
        </section>
      )}
    </div>
  );
}
