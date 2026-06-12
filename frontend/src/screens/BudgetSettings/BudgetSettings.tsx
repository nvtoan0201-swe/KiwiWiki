// Screen 15 — Budget & settings. Default budgets, default audience/outputs,
// "what counts as recent", escalation sensitivity, source preferences, and
// notification prefs. Client-side defaults (no backend settings resource);
// applied when composing a new research request.

import { Button, Card, Checkbox, Input, Radio, Select, Switch } from "../../components/ds";
import { DEFAULT_SETTINGS, useSettings } from "../../store/settings";

const SOURCES = [
  { id: "openalex", label: "OpenAlex" },
  { id: "arxiv", label: "arXiv" },
  { id: "semantic_scholar", label: "Semantic Scholar" },
  { id: "crossref", label: "Crossref" },
];

export function BudgetSettings() {
  const s = useSettings();

  const setBudget = (key: keyof typeof s.defaultBudget, value: string) =>
    s.update({ defaultBudget: { ...s.defaultBudget, [key]: Number(value) || 0 } });

  const toggleSource = (id: string) =>
    s.update({
      preferredSources: s.preferredSources.includes(id)
        ? s.preferredSources.filter((x) => x !== id)
        : [...s.preferredSources, id],
    });

  const toggleOutput = (id: string) =>
    s.update({
      defaultOutputs: s.defaultOutputs.includes(id)
        ? s.defaultOutputs.filter((x) => x !== id)
        : [...s.defaultOutputs, id],
    });

  return (
    <div className="screen screen--form">
      <header className="screen-head">
        <div className="eyebrow">Settings</div>
        <h1 className="screen-title">Defaults for new research</h1>
        <p className="screen-sub measure">
          These apply when you start a project; each run can still override them.
        </p>
      </header>

      <Card pad className="form-card">
        <h4>Default budgets</h4>
        <div className="form-grid">
          <Input
            label="LLM tokens"
            type="number"
            value={String(s.defaultBudget.llm_tokens)}
            onChange={(e) => setBudget("llm_tokens", e.target.value)}
          />
          <Input
            label="Search calls"
            type="number"
            value={String(s.defaultBudget.search_calls)}
            onChange={(e) => setBudget("search_calls", e.target.value)}
          />
          <Input
            label="Papers read"
            type="number"
            value={String(s.defaultBudget.papers_read)}
            onChange={(e) => setBudget("papers_read", e.target.value)}
          />
          <Input
            label="Time (seconds)"
            type="number"
            value={String(s.defaultBudget.time)}
            onChange={(e) => setBudget("time", e.target.value)}
          />
        </div>
        <p className="muted-note">
          Hitting a ceiling stops the run gracefully — outputs are still produced and the report
          says the budget cut coverage short.
        </p>
      </Card>

      <Card pad className="form-card">
        <h4>Defaults</h4>
        <div className="form-grid">
          <Select
            label="Audience"
            value={s.defaultAudience}
            onChange={(e) => s.update({ defaultAudience: e.target.value })}
            options={[
              { value: "domain_expert", label: "Domain expert" },
              { value: "executive", label: "Executive" },
              { value: "general", label: "General reader" },
            ]}
          />
          <Input
            label="What counts as recent (years)"
            type="number"
            min={1}
            value={String(s.recentYears)}
            onChange={(e) => s.update({ recentYears: Number(e.target.value) || 5 })}
          />
        </div>
        <div className="form-row">
          <span className="kw-field__label">Outputs</span>
          <div className="form-row__options">
            <Checkbox
              label="Report"
              checked={s.defaultOutputs.includes("report")}
              onChange={() => toggleOutput("report")}
            />
            <Checkbox
              label="Presentation"
              checked={s.defaultOutputs.includes("presentation")}
              onChange={() => toggleOutput("presentation")}
            />
          </div>
        </div>
      </Card>

      <Card pad className="form-card">
        <h4>Escalation sensitivity</h4>
        <p className="muted-note">
          How readily the agent pauses to ask you, versus proceeding with a noted assumption.
        </p>
        <div className="form-row__options form-row__options--col">
          <Radio
            name="sensitivity"
            label="Ask more — pause on any material fork"
            checked={s.escalationSensitivity === "ask_more"}
            onChange={() => s.update({ escalationSensitivity: "ask_more" })}
          />
          <Radio
            name="sensitivity"
            label="Balanced — pause on scope, thin literature, contradictions, high stakes"
            checked={s.escalationSensitivity === "balanced"}
            onChange={() => s.update({ escalationSensitivity: "balanced" })}
          />
          <Radio
            name="sensitivity"
            label="Ask less — prefer best judgment, always noted in the audit log"
            checked={s.escalationSensitivity === "ask_less"}
            onChange={() => s.update({ escalationSensitivity: "ask_less" })}
          />
        </div>
      </Card>

      <Card pad className="form-card">
        <h4>Source preferences</h4>
        <div className="form-row__options">
          {SOURCES.map((src) => (
            <Checkbox
              key={src.id}
              label={src.label}
              checked={s.preferredSources.includes(src.id)}
              onChange={() => toggleSource(src.id)}
            />
          ))}
        </div>
        <p className="muted-note">
          Open-access full text or abstracts only — the agent never bypasses paywalls.
        </p>
      </Card>

      <Card pad className="form-card">
        <h4>Notifications</h4>
        <div className="form-row__options form-row__options--col">
          <Switch
            label="Run complete"
            checked={s.notifyRunComplete}
            onChange={(e) => s.update({ notifyRunComplete: e.target.checked })}
          />
          <Switch
            label="Budget approaching its ceiling"
            checked={s.notifyBudgetApproaching}
            onChange={(e) => s.update({ notifyBudgetApproaching: e.target.checked })}
          />
          <Switch
            label="Significant findings mid-run"
            checked={s.notifySignificantFindings}
            onChange={(e) => s.update({ notifySignificantFindings: e.target.checked })}
          />
        </div>
        <p className="muted-note">Awaiting-input alerts are always on — they cannot be missed.</p>
      </Card>

      <div className="form-actions">
        <Button variant="ghost" size="sm" onClick={() => s.update(DEFAULT_SETTINGS)}>
          Reset to defaults
        </Button>
      </div>
    </div>
  );
}
