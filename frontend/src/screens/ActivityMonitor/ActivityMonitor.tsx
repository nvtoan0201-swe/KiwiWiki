// Screen 5 — Activity monitor (critical). Stage timeline, live activity feed,
// live counters + budget, saturation indicator, loop-back markers, run
// controls, and the escalation banner. WS-driven; falls back to polling the
// run/status endpoints while the socket is down.

import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useEscalations, useProject, useRunControl, useRuns, useStartRun } from "../../api/hooks";
import { Badge, Button, Callout, Card, Icon, Input } from "../../components/ds";
import { BudgetMeter, EmptyState, StageTimeline, StatusPill, formatWhen } from "../../components/shared";
import { useLiveRun } from "../../store/liveRun";

function SaturationIndicator() {
  const saturation = useLiveRun((s) => s.saturation);
  if (!saturation) return null;
  const tone =
    saturation.state === "saturated"
      ? "positive"
      : saturation.state === "approaching saturation"
        ? "accent"
        : "neutral";
  return (
    <div className="monitor-saturation" data-testid="saturation-indicator">
      <Badge tone={tone} icon="waves">
        {saturation.state}
      </Badge>
      {saturation.novelty_share != null && (
        <span className="monitor-saturation__share">
          novelty {Math.round(saturation.novelty_share * 100)}%
          {saturation.iteration != null ? ` · iteration ${saturation.iteration}` : ""}
        </span>
      )}
    </div>
  );
}

function Feed() {
  const feed = useLiveRun((s) => s.feed);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [feed.length]);

  if (feed.length === 0) {
    return <p className="muted-note">Waiting for activity… events appear here as the agent works.</p>;
  }
  return (
    <div className="monitor-feed" data-testid="activity-feed">
      {feed.map((line) => (
        <div key={line.id} className={`feed-line feed-line--${line.kind}`}>
          <span className="feed-line__time">{new Date(line.timestamp).toLocaleTimeString()}</span>
          {line.kind === "loop_back" && (
            <Badge tone="warning" icon="undo-2" data-testid="loop-back-marker">
              Loop back
            </Badge>
          )}
          {line.kind === "error" && <Badge tone="danger">Error</Badge>}
          <span className="feed-line__text">{line.text}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

export function ActivityMonitor() {
  const { projectId } = useParams<{ projectId: string }>();
  const connection = useLiveRun((s) => s.connection);
  const polling = connection !== "open";

  // Poll faster while the WS is down (graceful degradation).
  const project = useProject(projectId, { pollMs: polling ? 4000 : 20_000 });
  const runs = useRuns(projectId);
  const escalations = useEscalations(projectId, "open");
  const control = useRunControl(projectId ?? "");
  const startRun = useStartRun(projectId ?? "");

  const counters = useLiveRun((s) => s.counters);
  const liveStage = useLiveRun((s) => s.currentStage);

  const [budgetEdit, setBudgetEdit] = useState(false);
  const [papersCeiling, setPapersCeiling] = useState("");

  // Refresh REST state when WS signals escalations/run changes.
  const openEscalationId = useLiveRun((s) => s.openEscalationId);
  useEffect(() => {
    void escalations.refetch();
    void project.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openEscalationId]);

  if (!projectId) return null;
  if (project.isLoading) return <p className="muted-note screen">Loading project…</p>;
  if (!project.data) {
    return (
      <div className="screen">
        <EmptyState icon="alert-triangle" title="Project not found" />
      </div>
    );
  }

  const p = project.data;
  const activeRun =
    (runs.data ?? []).find((r) => r.status === "running" || r.status === "paused") ??
    (runs.data ?? [])[0];
  const stage = liveStage ?? p.current_stage;
  const openEscalation = (escalations.data ?? [])[0];

  const liveBudgetConsumed: Record<string, number> = {};
  for (const [cat, c] of Object.entries(counters.budget)) liveBudgetConsumed[cat] = c.running_total;
  const consumed =
    Object.keys(liveBudgetConsumed).length > 0
      ? liveBudgetConsumed
      : ((activeRun?.budget_consumed as Record<string, number>) ?? {});

  const adjustBudget = async () => {
    if (!activeRun || !papersCeiling) return;
    await control.adjustBudget.mutateAsync({
      runId: activeRun.id,
      body: { papers_read: Number(papersCeiling) },
    });
    setBudgetEdit(false);
  };

  return (
    <div className="screen">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Activity monitor</div>
          <h1 className="screen-title">{p.title}</h1>
          <p className="screen-sub">{p.research_question ?? p.original_request}</p>
        </div>
        <div className="screen-head__side">
          <StatusPill status={p.status} />
          {polling && (
            <Badge tone="warning" icon="wifi-off" data-testid="polling-fallback">
              Live feed reconnecting — polling
            </Badge>
          )}
        </div>
      </header>

      {openEscalation && (
        <div className="escalation-banner" role="alert" data-testid="escalation-banner">
          <Icon name="message-circle-question" size={17} />
          <div className="escalation-banner__body">
            <strong>The agent paused to ask you something.</strong>
            <span>{openEscalation.question}</span>
          </div>
          <Link to={`/projects/${projectId}/escalations`}>
            <Button size="sm">Answer</Button>
          </Link>
        </div>
      )}

      <Card pad className="monitor-timeline">
        <StageTimeline currentStage={stage} />
        <SaturationIndicator />
      </Card>

      <div className="monitor-grid">
        <Card pad className="monitor-feedcard">
          <h4>Live activity</h4>
          <Feed />
        </Card>

        <div className="monitor-side">
          <Card pad>
            <h4>Counters</h4>
            <dl className="monitor-counters" data-testid="counters">
              <div>
                <dt>Papers found</dt>
                <dd>{counters.papers_found ?? "—"}</dd>
              </div>
              <div>
                <dt>Triaged</dt>
                <dd>{counters.papers_triaged ?? "—"}</dd>
              </div>
              <div>
                <dt>Read deeply</dt>
                <dd>{counters.papers_analyzed ?? "—"}</dd>
              </div>
              <div>
                <dt>Searches</dt>
                <dd>{counters.searches ?? "—"}</dd>
              </div>
            </dl>
          </Card>

          <Card pad>
            <h4>Budget</h4>
            <BudgetMeter budget={p.budget ?? undefined} consumed={consumed} />
            {activeRun &&
              (budgetEdit ? (
                <div className="monitor-budgetedit">
                  <Input
                    label="Papers-read ceiling"
                    type="number"
                    value={papersCeiling}
                    onChange={(e) => setPapersCeiling(e.target.value)}
                  />
                  <div className="form-actions">
                    <Button size="sm" onClick={adjustBudget}>
                      Apply
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setBudgetEdit(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="ghost" size="sm" iconLeft="sliders-horizontal" onClick={() => setBudgetEdit(true)}>
                  Adjust budget
                </Button>
              ))}
          </Card>

          <Card pad>
            <h4>Controls</h4>
            <div className="monitor-controls">
              {!activeRun || activeRun.status === "complete" || activeRun.status === "failed" ? (
                <Button size="sm" iconLeft="play" onClick={() => startRun.mutate()}>
                  Start a run
                </Button>
              ) : (
                <>
                  {activeRun.status === "running" ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      iconLeft="pause"
                      onClick={() => control.pause.mutate(activeRun.id)}
                    >
                      Pause
                    </Button>
                  ) : (
                    <Button size="sm" iconLeft="play" onClick={() => control.resume.mutate(activeRun.id)}>
                      Resume
                    </Button>
                  )}
                  <Button
                    variant="danger"
                    size="sm"
                    iconLeft="square"
                    onClick={() =>
                      control.stop.mutate({ runId: activeRun.id, reason: "Stopped from the monitor" })
                    }
                  >
                    Stop
                  </Button>
                </>
              )}
            </div>
            {activeRun && (
              <p className="muted-note">
                Run started {formatWhen(activeRun.started_at)}
                {activeRun.stopping_criterion ? ` · stopped: ${activeRun.stopping_criterion}` : ""}
              </p>
            )}
          </Card>

          {p.status === "complete" && (
            <Callout tone="insight" title="Outputs are ready">
              <Link to={`/projects/${projectId}/report`}>Read the report</Link> ·{" "}
              <Link to={`/projects/${projectId}/presentation`}>Open the presentation</Link>
            </Callout>
          )}
        </div>
      </div>
    </div>
  );
}
