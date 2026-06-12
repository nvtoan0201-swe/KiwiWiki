// Screen 1 — Onboarding. Static informational steps: what the agent does,
// the four confidence labels, and the "it will pause to ask you" expectation.

import { Link } from "react-router-dom";

import mark from "../../assets/mark.svg";
import { Button, Card, Icon } from "../../components/ds";
import { ConfidenceBadge } from "../../components/shared";

const STEPS = [
  {
    icon: "search",
    title: "It reads broadly",
    body: "Given your question, KiwiWiki searches OpenAlex, arXiv, Semantic Scholar, and Crossref, snowballs through citations, and keeps going until new papers stop adding new ideas — not until an arbitrary count.",
  },
  {
    icon: "scale",
    title: "It weighs the sources",
    body: "Every paper gets a structured read: claim, method, results, limitations. Credibility reflects the method — a bold, small-sample, unreplicated paper scores low no matter how confident it sounds.",
  },
  {
    icon: "git-compare",
    title: "It maps agreement and conflict",
    body: "Where papers disagree, the agent investigates why instead of picking a winner. “It depends on the dataset” is a finding, not a failure.",
  },
  {
    icon: "book-open",
    title: "It writes back, fully cited",
    body: "The report and presentation carry a citation for every claim. Anything that is the agent's own synthesis is flagged as inference — never blended into sourced findings.",
  },
];

export function Onboarding() {
  return (
    <div className="screen screen--reading">
      <header className="screen-head">
        <img src={mark} alt="" width={44} height={44} />
        <div className="eyebrow">How it works</div>
        <h1 className="screen-title">Research that shows its work</h1>
        <p className="screen-sub measure">
          KiwiWiki reads across the literature, weighs the sources against one another, and writes
          back a measured, fully-cited answer. It runs on its own — but it will pause and ask you
          when a decision is genuinely yours to make.
        </p>
      </header>

      <div className="onboarding-grid">
        {STEPS.map((s) => (
          <Card key={s.title} pad>
            <span className="stat__icon">
              <Icon name={s.icon} size={18} />
            </span>
            <h4>{s.title}</h4>
            <p className="screen-body">{s.body}</p>
          </Card>
        ))}
      </div>

      <Card pad className="onboarding-section">
        <h4>Every claim carries a confidence label</h4>
        <p className="screen-body">
          Findings are labelled by how well the literature supports them, and the labels survive
          into the report and slides — no uniform confident prose.
        </p>
        <div className="onboarding-labels">
          <div>
            <ConfidenceBadge label="well_established" />
            <span>Replicated, agreed on across credible sources.</span>
          </div>
          <div>
            <ConfidenceBadge label="emerging" />
            <span>Early but consistent evidence; few studies so far.</span>
          </div>
          <div>
            <ConfidenceBadge label="contested" />
            <span>Credible sources disagree — the disagreement is investigated, not hidden.</span>
          </div>
          <div>
            <ConfidenceBadge label="speculative" />
            <span>The agent's own inference or a future direction; clearly flagged.</span>
          </div>
        </div>
      </Card>

      <Card pad className="onboarding-section">
        <h4>It will pause to ask you</h4>
        <p className="screen-body">
          When the scope is ambiguous, the literature is too thin, sources contradict each other in
          ways that change the answer, or a call is high-stakes — the run pauses and asks. It asks
          rarely, and it never silently makes a scope-changing decision. You can always answer
          "proceed with your best judgment."
        </p>
      </Card>

      <div className="screen-cta">
        <Link to="/new">
          <Button size="lg" iconLeft="plus">
            Start a research project
          </Button>
        </Link>
      </div>
    </div>
  );
}
