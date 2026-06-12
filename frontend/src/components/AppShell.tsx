// App shell: the fixed paper rail (brand, global nav, per-project sections),
// the global awaiting-input surfaces (rail badge + banner), and the toast
// stack. The awaiting-input state must be impossible to miss (phase 6).

import { Link, NavLink, Outlet, useLocation, useParams } from "react-router-dom";

import { useEscalations, useProject, useProjects } from "../api/hooks";
import mark from "../assets/mark.svg";
import { useLiveRun } from "../store/liveRun";
import { useNotifications } from "../store/notifications";
import { useProjectSocket } from "../ws/useProjectSocket";
import { Badge, Icon } from "./ds";
import { ErrorBoundary } from "./shared";

function RailLink({
  to,
  icon,
  label,
  count,
  end,
}: {
  to: string;
  icon: string;
  label: string;
  count?: number;
  end?: boolean;
}) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `kw-nav${isActive ? " kw-nav--active" : ""}`}>
      <Icon name={icon} size={17} />
      <span className="kw-nav__label">{label}</span>
      {count != null && count > 0 && <span className="kw-nav__count">{count}</span>}
    </NavLink>
  );
}

function ProjectNav({ projectId }: { projectId: string }) {
  const open = useEscalations(projectId, "open");
  const openCount = open.data?.length ?? 0;
  const base = `/projects/${projectId}`;
  return (
    <nav className="chat-section" aria-label="Project">
      <div className="chat-section__label">This project</div>
      <RailLink to={`${base}/monitor`} icon="activity" label="Activity monitor" />
      <RailLink to={`${base}/escalations`} icon="message-circle-question" label="Questions" count={openCount} />
      <RailLink to={`${base}/sources`} icon="file-text" label="Source library" />
      <RailLink to={`${base}/fieldmap`} icon="layers" label="Field map" />
      <RailLink to={`${base}/gaps`} icon="puzzle" label="Gap analysis" />
      <RailLink to={`${base}/report`} icon="book-open" label="Report" />
      <RailLink to={`${base}/presentation`} icon="presentation" label="Presentation" />
      <RailLink to={`${base}/audit`} icon="history" label="Audit log" />
    </nav>
  );
}

function AwaitingBanner() {
  const projects = useProjects();
  const location = useLocation();
  const awaiting = (projects.data?.items ?? []).filter((p) => p.status === "awaiting_input");
  if (awaiting.length === 0) return null;
  const first = awaiting[0];
  const target = `/projects/${first.id}/escalations`;
  if (location.pathname === target) return null;
  return (
    <div className="awaiting-banner" role="status" data-testid="awaiting-banner">
      <Icon name="message-circle-question" size={16} />
      <span>
        {awaiting.length === 1
          ? `“${first.title}” is paused — the agent needs your input.`
          : `${awaiting.length} projects are paused awaiting your input.`}
      </span>
      <Link to={target} className="awaiting-banner__link">
        Answer now
      </Link>
    </div>
  );
}

function Toasts() {
  const toasts = useNotifications((s) => s.toasts);
  const dismiss = useNotifications((s) => s.dismissToast);
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`} data-testid={`toast-${t.kind}`}>
          <Icon name={t.kind === "awaiting_input" ? "message-circle-question" : "bell"} size={15} />
          <div className="toast__body">
            <div className="toast__title">{t.title}</div>
            {t.body && <div className="toast__text">{t.body}</div>}
            {t.link && (
              <Link to={t.link} className="toast__link" onClick={() => dismiss(t.id)}>
                Open
              </Link>
            )}
          </div>
          <button className="toast__x" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
            <Icon name="x" size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}

export function AppShell() {
  const { projectId } = useParams<{ projectId: string }>();
  const projects = useProjects();
  const unread = useNotifications((s) => s.items.filter((n) => !n.read).length);
  const awaitingCount = (projects.data?.items ?? []).filter((p) => p.status === "awaiting_input").length;

  // Keep one socket alive for the project being viewed.
  useProjectSocket(projectId);
  const project = useProject(projectId);
  const connection = useLiveRun((s) => s.connection);

  return (
    <div className="shell">
      <aside className="shell-rail">
        <Link to="/" className="shell-brand">
          <img src={mark} alt="" width={26} height={26} />
          <span>
            Kiwi<span className="shell-brand__w">Wiki</span>
          </span>
        </Link>

        <nav className="chat-section" aria-label="Global">
          <RailLink to="/" icon="layout-dashboard" label="Projects" end count={awaitingCount} />
          <RailLink to="/new" icon="plus" label="New research" />
          <RailLink to="/notifications" icon="bell" label="Notifications" count={unread} />
          <RailLink to="/settings" icon="settings-2" label="Settings" />
          <RailLink to="/onboarding" icon="compass" label="How it works" />
        </nav>

        {projectId && project.data && (
          <>
            <div className="shell-rail__project" title={project.data.title}>
              <div className="chat-section__label">Open project</div>
              <div className="shell-rail__title">{project.data.title}</div>
            </div>
            <ProjectNav projectId={projectId} />
          </>
        )}

        <div className="shell-rail__foot">
          {projectId && connection !== "closed" && (
            <Badge tone={connection === "open" ? "accent" : "warning"} dot data-testid="connection-state">
              {connection === "open" ? "Live" : connection === "polling" ? "Reconnecting — polling" : "Connecting"}
            </Badge>
          )}
        </div>
      </aside>

      <main className="shell-main">
        <AwaitingBanner />
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>

      <Toasts />
    </div>
  );
}
