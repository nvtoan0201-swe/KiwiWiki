// Phase-6 shared components: ConfidenceBadge, StageTimeline, BudgetMeter,
// StatusPill, EmptyState, ErrorBoundary. (ProvenancePopover lives in its own
// file — it carries state and data fetching.)

import { Component, type ReactNode } from "react";

import type { ConfidenceLabel, ProjectStatus, Stage } from "../api/types";
import { STAGE_LABELS, STAGES } from "../api/types";
import { Badge, Icon, type BadgeTone } from "./ds";
import { CONFIDENCE_META } from "./helpers";

// ---------- ConfidenceBadge ----------

export function ConfidenceBadge({ label }: { label: ConfidenceLabel | null | undefined }) {
  if (!label || !(label in CONFIDENCE_META)) return null;
  const meta = CONFIDENCE_META[label];
  return (
    <Badge tone={meta.tone} icon={meta.icon} data-testid={`confidence-${label}`}>
      {meta.label}
    </Badge>
  );
}

// ---------- StatusPill ----------

const STATUS_META: Record<ProjectStatus, { label: string; tone: BadgeTone; dot?: boolean }> = {
  draft: { label: "Draft", tone: "neutral" },
  scoping: { label: "Scoping", tone: "info" },
  awaiting_input: { label: "Awaiting your input", tone: "warning", dot: true },
  running: { label: "Running", tone: "accent", dot: true },
  paused: { label: "Paused", tone: "neutral" },
  complete: { label: "Complete", tone: "positive" },
  failed: { label: "Failed", tone: "danger" },
};

export function StatusPill({ status }: { status: ProjectStatus }) {
  const meta = STATUS_META[status] ?? STATUS_META.draft;
  return (
    <Badge tone={meta.tone} dot={meta.dot} data-testid={`status-${status}`}>
      {meta.label}
    </Badge>
  );
}

// ---------- StageTimeline ----------

export interface StageTimelineProps {
  currentStage: Stage | null;
  completedThrough?: Stage | null;
  loopBackStage?: Stage | null;
}

export function StageTimeline({ currentStage }: StageTimelineProps) {
  const currentIdx = currentStage ? STAGES.indexOf(currentStage) : -1;
  return (
    <ol className="stage-timeline" aria-label="Workflow stages">
      {STAGES.map((stage, i) => {
        const state = i < currentIdx ? "done" : i === currentIdx ? "active" : "todo";
        return (
          <li key={stage} className="stage-timeline__step" data-state={state}>
            <span className="stage-timeline__marker">
              {state === "done" ? (
                <Icon name="check" size={12} />
              ) : state === "active" ? (
                <Icon name="loader" size={12} className="spin" />
              ) : (
                <span className="stage-timeline__dot" />
              )}
            </span>
            <span className="stage-timeline__label">{STAGE_LABELS[stage]}</span>
          </li>
        );
      })}
    </ol>
  );
}

// ---------- BudgetMeter ----------

const BUDGET_LABELS: Record<string, string> = {
  llm_tokens: "LLM tokens",
  search_calls: "Search calls",
  papers_read: "Papers read",
  time: "Time (s)",
};

export interface BudgetMeterProps {
  budget: Record<string, number> | null | undefined;
  consumed: Record<string, number> | null | undefined;
}

export function BudgetMeter({ budget, consumed }: BudgetMeterProps) {
  const categories = Object.keys(BUDGET_LABELS).filter(
    (c) => budget?.[c] != null || consumed?.[c] != null,
  );
  if (categories.length === 0) {
    return <p className="muted-note">No budget recorded yet.</p>;
  }
  return (
    <div className="budget-meter" data-testid="budget-meter">
      {categories.map((cat) => {
        const ceiling = budget?.[cat];
        const used = consumed?.[cat] ?? 0;
        const frac = ceiling ? Math.min(1, used / ceiling) : 0;
        const level = frac >= 0.9 ? "high" : frac >= 0.7 ? "med" : "ok";
        return (
          <div key={cat} className="budget-meter__row">
            <span className="budget-meter__label">{BUDGET_LABELS[cat]}</span>
            <span className="budget-meter__track">
              <span
                className="budget-meter__fill"
                data-level={level}
                style={{ width: `${frac * 100}%` }}
              />
            </span>
            <span className="budget-meter__nums">
              {Intl.NumberFormat().format(used)}
              {ceiling != null ? ` / ${Intl.NumberFormat().format(ceiling)}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------- EmptyState ----------

export interface EmptyStateProps {
  icon?: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon = "book-open", title, children, action }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon">
        <Icon name={icon} size={26} />
      </span>
      <h3 className="empty-state__title">{title}</h3>
      {children && <div className="empty-state__body">{children}</div>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}

// ---------- ErrorBoundary ----------

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="empty-state" role="alert">
          <span className="empty-state__icon">
            <Icon name="alert-triangle" size={26} />
          </span>
          <h3 className="empty-state__title">Something went wrong</h3>
          <div className="empty-state__body">
            <p>{this.state.error.message}</p>
            <button
              className="kw-btn kw-btn--secondary kw-btn--sm"
              onClick={() => this.setState({ error: null })}
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
