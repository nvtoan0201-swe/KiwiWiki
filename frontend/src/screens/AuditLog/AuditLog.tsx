// Screen 14 — Audit log. Paginated chronological entries with action type,
// description, and reasoning; loop-backs and escalations called out;
// resume/re-run controls; export to JSON.

import { useState } from "react";
import { useParams } from "react-router-dom";

import { useAudit, useRuns, useStartRun } from "../../api/hooks";
import { api } from "../../api/client";
import type { AuditActionType } from "../../api/types";
import { STAGE_LABELS } from "../../api/types";
import { Badge, Button, Card, Icon, type BadgeTone } from "../../components/ds";
import { EmptyState } from "../../components/shared";

const PAGE_SIZE = 50;

const ACTION_META: Partial<Record<AuditActionType, { tone: BadgeTone; icon: string }>> = {
  loop_back: { tone: "warning", icon: "undo-2" },
  escalation_raised: { tone: "warning", icon: "message-circle-question" },
  escalation_resolved: { tone: "positive", icon: "check" },
  budget_warning: { tone: "warning", icon: "gauge" },
  error: { tone: "danger", icon: "alert-triangle" },
  stopped: { tone: "danger", icon: "square" },
  stage_start: { tone: "accent", icon: "play" },
  stage_complete: { tone: "positive", icon: "check-check" },
};

export function AuditLog() {
  const { projectId } = useParams<{ projectId: string }>();
  const [offset, setOffset] = useState(0);
  const audit = useAudit(projectId, offset, PAGE_SIZE);
  const runs = useRuns(projectId);
  const startRun = useStartRun(projectId ?? "");

  const page = audit.data;
  const pausedRun = (runs.data ?? []).find((r) => r.status === "paused");

  const exportLog = async () => {
    const all = await api.listAudit(projectId!, 500, 0);
    const blob = new Blob([JSON.stringify(all.items, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit-${projectId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="screen">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Audit log</div>
          <h1 className="screen-title">Every decision, with its reasoning</h1>
          <p className="screen-sub">
            The durable record — the live feed is the view, this is the truth.
          </p>
        </div>
        <div className="screen-head__side report-toolbar">
          {pausedRun && (
            <Button
              variant="secondary"
              size="sm"
              iconLeft="play"
              onClick={() => api.resumeRun(pausedRun.id).then(() => runs.refetch())}
            >
              Resume paused run
            </Button>
          )}
          <Button
            variant="secondary"
            size="sm"
            iconLeft="rotate-ccw"
            onClick={() => startRun.mutate()}
          >
            Re-run from here
          </Button>
          <Button variant="ghost" size="sm" iconLeft="download" onClick={exportLog}>
            Export
          </Button>
        </div>
      </header>

      {audit.isLoading && <p className="muted-note">Loading audit entries…</p>}

      {page && page.items.length === 0 && (
        <EmptyState icon="history" title="No audit entries yet" />
      )}

      {page && page.items.length > 0 && (
        <Card className="audit-list">
          {page.items.map((entry) => {
            const meta = ACTION_META[entry.action_type];
            return (
              <div
                key={entry.id}
                className={`audit-entry${meta ? " audit-entry--flagged" : ""}`}
                data-testid={`audit-${entry.action_type}`}
              >
                <div className="audit-entry__time">
                  <span>{new Date(entry.timestamp).toLocaleTimeString()}</span>
                  <span className="audit-entry__date">
                    {new Date(entry.timestamp).toLocaleDateString()}
                  </span>
                </div>
                <div className="audit-entry__body">
                  <div className="audit-entry__head">
                    <Badge tone={meta?.tone ?? "neutral"} icon={meta?.icon}>
                      {entry.action_type.replace(/_/g, " ")}
                    </Badge>
                    {entry.stage && (
                      <span className="audit-entry__stage">{STAGE_LABELS[entry.stage]}</span>
                    )}
                  </div>
                  <p className="audit-entry__desc">{entry.description}</p>
                  {entry.reasoning && (
                    <p className="audit-entry__reasoning">
                      <Icon name="corner-down-right" size={12} /> {entry.reasoning}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </Card>
      )}

      {page && page.total > PAGE_SIZE && (
        <div className="pager">
          <Button
            variant="ghost"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Newer
          </Button>
          <span className="muted-note">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} of {page.total}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Older
          </Button>
        </div>
      )}
    </div>
  );
}
