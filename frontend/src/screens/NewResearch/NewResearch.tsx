// Screen 3 — New research. Request text, optional scope controls, audience,
// output toggles, budget ceiling, seed-source upload (parsed client-side and
// stored under project.scope.seed_sources — there is no upload endpoint).
// POST /projects, then start the run so scoping begins.

import { useState, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../api/client";
import { useCreateProject } from "../../api/hooks";
import { Button, Card, Checkbox, Icon, Input, Select, Tag, Textarea } from "../../components/ds";
import { useSettings } from "../../store/settings";

const AUDIENCES = [
  { value: "domain_expert", label: "Domain expert" },
  { value: "executive", label: "Executive" },
  { value: "general", label: "General reader" },
];

const DEPTHS = [
  { value: "", label: "Let the agent decide" },
  { value: "quick_survey", label: "Quick survey" },
  { value: "deep_dive", label: "Deep dive" },
];

export function NewResearch() {
  const navigate = useNavigate();
  const create = useCreateProject();
  const settings = useSettings();

  const [request, setRequest] = useState("");
  const [timeWindow, setTimeWindow] = useState("");
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");
  const [depth, setDepth] = useState("");
  const [audience, setAudience] = useState(settings.defaultAudience);
  const [outputs, setOutputs] = useState<string[]>(settings.defaultOutputs);
  const [papersBudget, setPapersBudget] = useState(String(settings.defaultBudget.papers_read));
  const [seedSources, setSeedSources] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const toggleOutput = (name: string) =>
    setOutputs((prev) => (prev.includes(name) ? prev.filter((o) => o !== name) : [...prev, name]));

  const onSeedFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    void file.text().then((text) => {
      const lines = text
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .slice(0, 50);
      setSeedSources((prev) => [...new Set([...prev, ...lines])]);
    });
  };

  const submit = async () => {
    setError(null);
    if (request.trim().length < 3) {
      setError("Describe what you want researched.");
      return;
    }
    try {
      const project = await create.mutateAsync({
        original_request: request.trim(),
        audience,
        outputs_requested: outputs,
        budget: { ...settings.defaultBudget, papers_read: Number(papersBudget) || undefined },
      });
      const scope: Record<string, unknown> = {};
      if (timeWindow) scope.time_window = timeWindow;
      if (include) scope.included_subfields = include.split(",").map((s) => s.trim()).filter(Boolean);
      if (exclude) scope.excluded_subfields = exclude.split(",").map((s) => s.trim()).filter(Boolean);
      if (depth) scope.depth = depth;
      if (seedSources.length) scope.seed_sources = seedSources;
      if (Object.keys(scope).length > 0) {
        await api.updateProject(project.id, { scope });
      }
      await api.startRun(project.id);
      navigate(`/projects/${project.id}/monitor`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the project.");
    }
  };

  return (
    <div className="screen screen--form">
      <header className="screen-head">
        <div className="eyebrow">New research</div>
        <h1 className="screen-title">What should we look into?</h1>
        <p className="screen-sub measure">
          Describe the question in your own words. The agent restates it, proposes a scope, and
          checks with you before searching.
        </p>
      </header>

      <Card pad className="form-card">
        <Textarea
          label="Research request"
          rows={4}
          placeholder="e.g. What do we know about how sleep deprivation affects immune function?"
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          error={error ?? undefined}
        />

        <div className="form-grid">
          <Input
            label="Time window"
            placeholder="e.g. last 10 years"
            value={timeWindow}
            onChange={(e) => setTimeWindow(e.target.value)}
            hint="Optional — what counts as recent."
          />
          <Select label="Depth" value={depth} onChange={(e) => setDepth(e.target.value)} options={DEPTHS} />
          <Input
            label="Include subfields"
            placeholder="comma-separated"
            value={include}
            onChange={(e) => setInclude(e.target.value)}
          />
          <Input
            label="Exclude subfields"
            placeholder="comma-separated"
            value={exclude}
            onChange={(e) => setExclude(e.target.value)}
          />
          <Select
            label="Audience"
            value={audience}
            onChange={(e) => setAudience(e.target.value)}
            options={AUDIENCES}
          />
          <Input
            label="Budget — papers to read"
            type="number"
            min={1}
            value={papersBudget}
            onChange={(e) => setPapersBudget(e.target.value)}
            hint="The agent stops gracefully at the ceiling and reports what it covered."
          />
        </div>

        <div className="form-row">
          <span className="kw-field__label">Outputs</span>
          <div className="form-row__options">
            <Checkbox
              label="Report"
              checked={outputs.includes("report")}
              onChange={() => toggleOutput("report")}
            />
            <Checkbox
              label="Presentation"
              checked={outputs.includes("presentation")}
              onChange={() => toggleOutput("presentation")}
            />
          </div>
        </div>

        <div className="form-row">
          <span className="kw-field__label">Seed sources</span>
          <label className="seed-upload">
            <Icon name="upload" size={15} />
            Upload a list (one DOI, URL, or title per line)
            <input type="file" accept=".txt,.csv,.md" onChange={onSeedFile} hidden />
          </label>
          {seedSources.length > 0 && (
            <div className="seed-upload__tags">
              {seedSources.map((s) => (
                <Tag key={s} onRemove={() => setSeedSources((prev) => prev.filter((x) => x !== s))}>
                  {s.length > 48 ? `${s.slice(0, 45)}…` : s}
                </Tag>
              ))}
            </div>
          )}
        </div>

        <div className="form-actions">
          <Button size="lg" iconLeft="search" onClick={submit} disabled={create.isPending}>
            {create.isPending ? "Starting…" : "Run research"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
