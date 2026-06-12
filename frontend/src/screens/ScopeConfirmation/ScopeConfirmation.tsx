// Screen 4 — Scope confirmation. Renders the ScopeProposal carried in the
// open scoping escalation: the restated question (distinct from the original),
// the proposed scope, ambiguities as choice controls, and the
// answerable-from-literature flag. Confirm/Revise resolve the escalation.

import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useEscalations, useProject, useResolveEscalation } from "../../api/hooks";
import type { ScopeProposal } from "../../api/types";
import { Badge, Button, Callout, Card, Radio, Tag, Textarea } from "../../components/ds";
import { EmptyState } from "../../components/shared";

export function ScopeConfirmation() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const project = useProject(projectId);
  const escalations = useEscalations(projectId, "open");
  const resolve = useResolveEscalation(projectId ?? "");
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");

  const scoping = (escalations.data ?? []).find(
    (e) => e.trigger === "ambiguous_scope" || e.trigger === "thin_literature",
  );
  const proposal = scoping?.context?.proposal as ScopeProposal | undefined;

  if (escalations.isLoading || project.isLoading) {
    return <p className="muted-note screen">Loading scope proposal…</p>;
  }

  if (!scoping || !proposal) {
    return (
      <div className="screen">
        <EmptyState icon="check-check" title="No scope waiting on you">
          {project.data?.research_question ? (
            <>
              The confirmed question: <em>{project.data.research_question}</em>
            </>
          ) : (
            "The agent has not proposed a scope yet — it will pause here when it does."
          )}
        </EmptyState>
        <div className="screen-cta">
          <Button variant="secondary" onClick={() => navigate(`/projects/${projectId}/monitor`)}>
            Go to the activity monitor
          </Button>
        </div>
      </div>
    );
  }

  const thinLiterature = scoping.trigger === "thin_literature";
  const ambiguities = proposal.ambiguities ?? [];

  const confirm = async (selectedOption?: string) => {
    const response: Record<string, unknown> = {};
    if (selectedOption) response.selected_option = selectedOption;
    if (Object.keys(choices).length) response.resolutions = choices;
    if (note.trim()) response.note = note.trim();
    if (!selectedOption && Object.keys(response).length === 0) response.confirmed = true;
    await resolve.mutateAsync({ escalationId: scoping.id, response });
    navigate(`/projects/${projectId}/monitor`);
  };

  return (
    <div className="screen screen--form">
      <header className="screen-head">
        <div className="eyebrow">Scope confirmation</div>
        <h1 className="screen-title">Did I understand the question?</h1>
      </header>

      <Card pad className="form-card">
        <div className="scope-restate">
          <div className="kw-field__label">Your request</div>
          <p className="scope-restate__original">“{project.data?.original_request}”</p>
          <div className="kw-field__label">Restated as</div>
          <p className="scope-restate__question" data-testid="restated-question">
            {proposal.research_question}
          </p>
        </div>

        <div className="scope-summary">
          {proposal.scope.time_window && <Tag>window: {proposal.scope.time_window}</Tag>}
          {proposal.scope.depth && <Tag>depth: {proposal.scope.depth}</Tag>}
          {(proposal.scope.included_subfields ?? []).map((s) => (
            <Tag key={`in-${s}`}>includes: {s}</Tag>
          ))}
          {(proposal.scope.excluded_subfields ?? []).map((s) => (
            <Tag key={`ex-${s}`}>excludes: {s}</Tag>
          ))}
          {proposal.audience && <Tag>audience: {proposal.audience}</Tag>}
        </div>

        {proposal.answerable_from_literature ? (
          <Badge tone="positive" icon="check-check">
            Answerable from published literature
          </Badge>
        ) : (
          <Callout tone="warning" title="This may not be answerable from the literature">
            {proposal.answerability_reasoning}
          </Callout>
        )}

        {ambiguities.length > 0 && (
          <div className="scope-ambiguities">
            <h4>Before searching, resolve {ambiguities.length === 1 ? "this" : "these"}</h4>
            {ambiguities.map((a) => (
              <div key={a.id} className="scope-ambiguity" data-testid={`ambiguity-${a.id}`}>
                <p className="scope-ambiguity__q">{a.question}</p>
                {a.why_it_matters && <p className="scope-ambiguity__why">{a.why_it_matters}</p>}
                <div className="scope-ambiguity__options">
                  {a.options.map((o) => (
                    <Radio
                      key={o.id}
                      name={`amb-${a.id}`}
                      label={
                        <>
                          {o.label}
                          {o.description && <span className="option-desc"> — {o.description}</span>}
                        </>
                      }
                      checked={choices[a.id] === o.id}
                      onChange={() => setChoices((prev) => ({ ...prev, [a.id]: o.id }))}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <Textarea
          label="Anything to adjust? (optional)"
          rows={2}
          placeholder="e.g. focus on human studies only"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />

        <div className="form-actions">
          {thinLiterature ? (
            <>
              <Button onClick={() => confirm("proceed_anyway")} disabled={resolve.isPending}>
                Search anyway and report what exists
              </Button>
              <Button variant="secondary" onClick={() => navigate("/new")}>
                Revise the question
              </Button>
              <Button variant="danger" onClick={() => confirm("stop")} disabled={resolve.isPending}>
                Stop the project
              </Button>
            </>
          ) : (
            <>
              <Button
                onClick={() => confirm()}
                disabled={resolve.isPending || Object.keys(choices).length < ambiguities.length}
                data-testid="confirm-scope"
              >
                {resolve.isPending ? "Confirming…" : "Confirm and start searching"}
              </Button>
              <Button variant="secondary" onClick={() => navigate("/new")}>
                Revise
              </Button>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
