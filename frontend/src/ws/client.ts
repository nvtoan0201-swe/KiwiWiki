// WebSocket client for /ws/projects/{id}. Dispatches events into the live-run
// store and the notification store; reconnects with backoff and signals the
// UI to fall back to polling while disconnected (phase 6: live state degrades
// gracefully).

import type { WsEvent } from "../api/types";
import { useLiveRun } from "../store/liveRun";
import { useNotifications } from "../store/notifications";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 15_000;

export function wsUrl(projectId: string): string {
  const base = (import.meta.env?.VITE_WS_BASE as string | undefined) ?? "";
  if (base) return `${base}/ws/projects/${projectId}`;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws/projects/${projectId}`;
}

export function notifyFromEvent(event: WsEvent): void {
  const push = useNotifications.getState().push;
  switch (event.type) {
    case "escalation_raised":
      push({
        kind: "awaiting_input",
        title: "The agent needs your input",
        body: String(event.payload.question ?? "An escalation is waiting for a decision."),
        projectId: event.project_id,
        link: `/projects/${event.project_id}/escalations`,
      });
      break;
    case "run_finished": {
      const status = String(event.payload.status ?? "");
      const criterion = event.payload.stopping_criterion;
      const early = criterion === "budget" || criterion === "user_stopped" || criterion === "error";
      push({
        kind: status === "failed" ? "error" : early ? "stopped_early" : "run_complete",
        title:
          status === "failed"
            ? "Run failed"
            : early
              ? `Run stopped early (${String(criterion)})`
              : "Run complete",
        projectId: event.project_id,
        link: `/projects/${event.project_id}/monitor`,
      });
      break;
    }
    case "output_ready": {
      const output = String(event.payload.output ?? "output");
      push({
        kind: "output_ready",
        title: output === "report" ? "Report ready" : "Presentation ready",
        projectId: event.project_id,
        link:
          output === "report"
            ? `/projects/${event.project_id}/report`
            : `/projects/${event.project_id}/presentation`,
      });
      break;
    }
    case "activity": {
      if (event.payload.action_type === "budget_warning") {
        push({
          kind: "budget_approaching",
          title: "Budget approaching its ceiling",
          body: String(event.payload.description ?? ""),
          projectId: event.project_id,
          link: `/projects/${event.project_id}/monitor`,
        });
      }
      break;
    }
    default:
      break;
  }
}

export class ProjectSocket {
  private projectId: string;
  private ws: WebSocket | null = null;
  private attempts = 0;
  private closedByUser = false;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(projectId: string) {
    this.projectId = projectId;
  }

  connect(): void {
    this.closedByUser = false;
    useLiveRun.getState().setConnection("connecting");
    try {
      this.ws = new WebSocket(wsUrl(this.projectId));
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.attempts = 0;
      useLiveRun.getState().setConnection("open");
    };

    this.ws.onmessage = (msg: MessageEvent<string>) => {
      let event: WsEvent;
      try {
        event = JSON.parse(msg.data) as WsEvent;
      } catch {
        return;
      }
      useLiveRun.getState().applyEvent(event);
      notifyFromEvent(event);
    };

    this.ws.onclose = () => {
      if (!this.closedByUser) this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect(): void {
    // While disconnected the UI polls the run/status endpoints instead.
    useLiveRun.getState().setConnection("polling");
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** this.attempts, RECONNECT_MAX_MS);
    this.attempts += 1;
    this.timer = setTimeout(() => this.connect(), delay);
  }

  close(): void {
    this.closedByUser = true;
    if (this.timer) clearTimeout(this.timer);
    this.ws?.close();
    useLiveRun.getState().setConnection("closed");
  }
}
