// Screen 2 — Projects dashboard. Project cards with a prominent
// awaiting-input treatment, per-card actions, global budget summary,
// filters/sort, and the New research button.

import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { useDeleteProject, useProjects } from "../../api/hooks";
import type { Project, ProjectStatus } from "../../api/types";
import { STAGE_LABELS } from "../../api/types";
import { Badge, Button, Card, Icon, IconButton, Select } from "../../components/ds";
import { EmptyState, StatusPill, formatWhen } from "../../components/shared";
import { useQueryClient } from "@tanstack/react-query";

type SortKey = "updated" | "title" | "status";

const FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "All projects" },
  { value: "awaiting_input", label: "Awaiting input" },
  { value: "running", label: "Running" },
  { value: "complete", label: "Complete" },
  { value: "paused", label: "Paused" },
  { value: "draft", label: "Drafts" },
];

function ProjectCard({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const navigate = useNavigate();
  const remove = useDeleteProject();
  const awaiting = project.status === "awaiting_input";
  const open = () =>
    navigate(
      awaiting
        ? `/projects/${project.id}/escalations`
        : project.status === "draft"
          ? `/projects/${project.id}/scope`
          : `/projects/${project.id}/monitor`,
    );

  const pauseOrResume = async () => {
    const runs = await api.listRuns(project.id);
    const active = runs.find((r) => r.status === "running" || r.status === "paused");
    if (!active) return;
    if (active.status === "running") await api.pauseRun(active.id);
    else await api.resumeRun(active.id);
    onChanged();
  };

  return (
    <Card
      className={`project-card${awaiting ? " project-card--awaiting" : ""}`}
      data-testid={`project-card-${project.id}`}
      pad
    >
      {awaiting && (
        <div className="project-card__awaiting" data-testid="awaiting-treatment">
          <Icon name="message-circle-question" size={15} />
          The agent has a question for you
          <Link to={`/projects/${project.id}/escalations`}>Answer now</Link>
        </div>
      )}
      <div className="project-card__head">
        <button className="project-card__title" onClick={open}>
          {project.title}
        </button>
        <StatusPill status={project.status} />
      </div>
      <p className="project-card__question">
        {project.research_question ?? project.original_request}
      </p>
      <div className="project-card__meta">
        {project.current_stage && (
          <Badge tone="neutral" icon="activity">
            {STAGE_LABELS[project.current_stage]}
          </Badge>
        )}
        <span className="project-card__when">updated {formatWhen(project.updated_at)}</span>
      </div>
      <div className="project-card__actions">
        <Button variant="secondary" size="sm" iconLeft="arrow-right" onClick={open}>
          Open
        </Button>
        {(project.status === "running" || project.status === "paused") && (
          <Button
            variant="ghost"
            size="sm"
            iconLeft={project.status === "running" ? "pause" : "play"}
            onClick={pauseOrResume}
          >
            {project.status === "running" ? "Pause" : "Resume"}
          </Button>
        )}
        <IconButton
          icon="archive"
          label="Archive project"
          size="sm"
          onClick={() => {
            if (window.confirm(`Archive “${project.title}”?`)) remove.mutate(project.id);
          }}
        />
      </div>
    </Card>
  );
}

export function ProjectsDashboard() {
  const projects = useProjects();
  const qc = useQueryClient();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState<SortKey>("updated");

  const items = useMemo(() => {
    let list = projects.data?.items ?? [];
    if (filter !== "all") list = list.filter((p) => p.status === (filter as ProjectStatus));
    list = [...list].sort((a, b) => {
      // Awaiting-input projects always surface first.
      const aw = Number(b.status === "awaiting_input") - Number(a.status === "awaiting_input");
      if (aw !== 0) return aw;
      if (sort === "title") return a.title.localeCompare(b.title);
      if (sort === "status") return a.status.localeCompare(b.status);
      return b.updated_at.localeCompare(a.updated_at);
    });
    return list;
  }, [projects.data, filter, sort]);

  const all = projects.data?.items ?? [];
  const stats = {
    total: all.length,
    running: all.filter((p) => p.status === "running").length,
    awaiting: all.filter((p) => p.status === "awaiting_input").length,
    complete: all.filter((p) => p.status === "complete").length,
  };
  const budgetTotal = all.reduce((acc, p) => acc + (p.budget?.papers_read ?? 0), 0);

  return (
    <div className="screen">
      <header className="dash-head">
        <div>
          <div className="eyebrow">Library</div>
          <h1 className="dash-title">Research</h1>
        </div>
        <div className="dash-head__actions">
          <Link to="/new">
            <Button iconLeft="plus">New research</Button>
          </Link>
        </div>
      </header>

      <section className="dash-stats">
        {[
          { label: "Projects", value: stats.total, icon: "book-open" },
          { label: "Running now", value: stats.running, icon: "activity" },
          { label: "Awaiting your input", value: stats.awaiting, icon: "message-circle-question" },
          { label: "Papers budgeted", value: budgetTotal, icon: "gauge" },
        ].map((s) => (
          <Card key={s.label} pad>
            <div className="stat">
              <span className="stat__icon">
                <Icon name={s.icon} size={18} />
              </span>
              <div className="stat__num">{s.value}</div>
              <div className="stat__label">{s.label}</div>
            </div>
          </Card>
        ))}
      </section>

      <div className="dash-filters">
        <Select
          aria-label="Filter projects"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          options={FILTERS}
        />
        <Select
          aria-label="Sort projects"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          options={[
            { value: "updated", label: "Recently updated" },
            { value: "title", label: "Title" },
            { value: "status", label: "Status" },
          ]}
        />
      </div>

      {projects.isLoading && <p className="muted-note">Loading projects…</p>}

      {!projects.isLoading && items.length === 0 && (
        <EmptyState
          title="What should we look into?"
          action={
            <Link to="/new">
              <Button iconLeft="plus">New research</Button>
            </Link>
          }
        >
          KiwiWiki reads across the literature, weighs the sources, and writes back a cited answer.
        </EmptyState>
      )}

      <div className="project-grid">
        {items.map((p) => (
          <ProjectCard
            key={p.id}
            project={p}
            onChanged={() => qc.invalidateQueries({ queryKey: ["projects"] })}
          />
        ))}
      </div>
    </div>
  );
}
