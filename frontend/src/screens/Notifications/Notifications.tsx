// Screen 16 — Notifications. List surface (toasts live in the shell);
// awaiting-input has the highest priority; each item deep-links to the
// relevant screen; delivery prefs live in Settings.

import { Link } from "react-router-dom";

import { useProjects } from "../../api/hooks";
import { Badge, Button, Card, Icon, type BadgeTone } from "../../components/ds";
import { formatWhen } from "../../components/helpers";
import { EmptyState } from "../../components/shared";
import { useNotifications, type NotificationKind } from "../../store/notifications";

const KIND_META: Record<NotificationKind, { tone: BadgeTone; icon: string; label: string }> = {
  awaiting_input: { tone: "warning", icon: "message-circle-question", label: "Awaiting input" },
  run_complete: { tone: "positive", icon: "check-check", label: "Run complete" },
  budget_approaching: { tone: "warning", icon: "gauge", label: "Budget" },
  stopped_early: { tone: "warning", icon: "square", label: "Stopped early" },
  significant_finding: { tone: "accent", icon: "sparkles", label: "Finding" },
  output_ready: { tone: "accent", icon: "book-open", label: "Output ready" },
  error: { tone: "danger", icon: "alert-triangle", label: "Error" },
};

export function Notifications() {
  const items = useNotifications((s) => s.items);
  const markRead = useNotifications((s) => s.markRead);
  const markAllRead = useNotifications((s) => s.markAllRead);
  const projects = useProjects();

  // Awaiting-input projects always surface here, even across reloads
  // (session notifications are in-memory; project state is the truth).
  const awaiting = (projects.data?.items ?? []).filter((p) => p.status === "awaiting_input");
  const sorted = [...items].sort((a, b) => {
    const pri = Number(b.kind === "awaiting_input") - Number(a.kind === "awaiting_input");
    return pri !== 0 ? pri : b.createdAt.localeCompare(a.createdAt);
  });

  return (
    <div className="screen screen--form">
      <header className="screen-head screen-head--row">
        <div>
          <div className="eyebrow">Notifications</div>
          <h1 className="screen-title">What needs you</h1>
        </div>
        <div className="screen-head__side">
          {items.some((n) => !n.read) && (
            <Button variant="ghost" size="sm" onClick={markAllRead}>
              Mark all read
            </Button>
          )}
          <Link to="/settings" className="muted-note">
            Delivery preferences
          </Link>
        </div>
      </header>

      {awaiting.map((p) => (
        <Card key={p.id} pad className="project-card--awaiting notif notif--awaiting">
          <Badge tone="warning" icon="message-circle-question" dot>
            Awaiting input
          </Badge>
          <div className="notif__body">
            <strong>{p.title}</strong>
            <span>The agent is paused on a question only you can answer.</span>
          </div>
          <Link to={`/projects/${p.id}/escalations`}>
            <Button size="sm">Answer now</Button>
          </Link>
        </Card>
      ))}

      {sorted.length === 0 && awaiting.length === 0 && (
        <EmptyState icon="bell" title="Nothing needs you right now">
          You'll hear about questions from the agent, finished runs, budget warnings, and ready
          outputs here.
        </EmptyState>
      )}

      {sorted.map((n) => {
        const meta = KIND_META[n.kind];
        return (
          <Card key={n.id} pad className={`notif${n.read ? " notif--read" : ""}`}>
            <Badge tone={meta.tone} icon={meta.icon}>
              {meta.label}
            </Badge>
            <div className="notif__body">
              <strong>{n.title}</strong>
              {n.body && <span>{n.body}</span>}
              <span className="muted-note">{formatWhen(n.createdAt)}</span>
            </div>
            {n.link && (
              <Link to={n.link} onClick={() => markRead(n.id)}>
                <Button variant="secondary" size="sm" iconRight="arrow-right">
                  Open
                </Button>
              </Link>
            )}
            {!n.read && (
              <button
                className="notif__dismiss"
                aria-label="Mark read"
                onClick={() => markRead(n.id)}
              >
                <Icon name="check" size={14} />
              </button>
            )}
          </Card>
        );
      })}
    </div>
  );
}
