# Autonomous Research Agent — Behavioral & Workflow Plan

This plan describes *how the agent behaves, makes decisions, and knows when it is done* — not its technical implementation. It is organized around behavior and decision rules rather than capabilities in isolation, because the hardest part of a research agent is not performing each task but knowing **when a task is done well enough to move on** and **when to stop and ask a human instead of guessing**.

---

## The Behavioral Spine

Operating principles the agent holds constant across every stage:

- **Grounded, not generative.** Every claim in any output traces to a specific source. "I recall that…" is treated as a failure mode. If it can't be cited, it is flagged as the agent's own inference, not established fact.
- **Calibrated confidence.** The agent distinguishes *well-established* (multiple independent strong studies agree), *emerging* (promising but thin or recent), *contested* (credible sources disagree), and *speculative* (its own synthesis). These labels survive all the way into the final outputs rather than being smoothed into uniform prose.
- **Bounded autonomy.** The agent runs unsupervised within a stage but escalates at defined junctions. It never silently makes scope decisions that change what the user is actually getting.
- **Budget-aware.** Searches, papers read, and synthesis passes all cost time and money. The agent tracks a budget and makes explicit breadth-vs-depth and recency-vs-foundational tradeoffs rather than reading until it runs out.

---

## Feature Set

The requested features, plus four additions that keep the output reliable:

1. Scoping / question refinement *(added)*
2. Literature Search
3. Paper Analysis
4. Source credibility & bias assessment *(added — woven into Paper Analysis)*
5. Comparative Analysis
6. Gap & future-direction analysis *(added — output of Comparative Analysis)*
7. Report Writing
8. Presentation Generation
9. Provenance / citation management *(added — persistent state across all stages)*

**Why the additions matter:** Scoping is the highest-leverage stage; everything downstream inherits its quality. Credibility assessment prevents weighting a bold-but-weak paper like a rigorous one. Gap analysis is usually the actually-novel reason someone commissions research. Provenance makes every fact traceable to its source passage.

---

## The Workflow Is a Loop, Not a Pipeline

The biggest design mistake is treating the stages as sequential and run once. Real research is iterative: paper analysis surfaces a subfield the search missed; comparative analysis reveals the question was framed wrong. The agent can return to an earlier stage when a later one produces a **trigger condition**, and it logs *why* it looped back so the process stays auditable.

---

## Stage 0 — Scoping

**Behavior:** Restate the user's request as a concrete research question, surface ambiguities, and propose a scope (time window, subfields in/out, depth, intended audience and output format). Present this back before doing real work.

**Decisions it makes:**
- How broad to cast — survey of a whole field vs. deep dive on one method.
- What "recent" means for this topic (months in ML, years in pure math).
- Whether the question is answerable from literature at all, or requires primary data the agent cannot get.

**Escalates when:** the request admits multiple reasonable interpretations that would produce very different reports. A 30-second confirmation here saves hours of wrong-direction work.

---

## Stage 1 — Literature Search

**Behavior:** Iterative, not one-shot. Start broad, inspect results, then refine — expanding when too narrow, tightening when flooded. Use citation snowballing (references of good papers, and what cites them) as a second discovery channel, since keyword search alone misses differently-worded work.

**Decisions:**
- **Query reformulation** — when results are mostly irrelevant or mostly duplicates, change strategy rather than paging deeper.
- **Source diversity** — deliberately seek disagreeing viewpoints and different venues. A list of papers that all agree is a warning sign, not success.
- **Relevance triage** — score each hit on title/abstract before committing to read it, so the reading budget goes to high-value papers.

**Stopping criterion (the important one):** Stop at **saturation** — when new searches stop surfacing new *ideas* — not at a paper count. If the last several papers restate known points, the space is covered; if they keep introducing new methods, keep going. Report the saturation judgment so the user knows whether coverage is thorough or thin.

---

## Stage 2 — Paper Analysis

**Behavior:** Tiered reading. Triage abstract → skim structure → deep-read only what earns it. For each deep read, extract a structured record: core claim, method, key results with numbers, datasets/conditions, stated limitations, and the agent's *own* assessment of weaknesses the authors didn't admit.

**Decisions:**
- **Depth allocation** — foundational or directly-on-point papers get a full read; tangential ones get their claim noted and are set aside.
- **Credibility scoring** — weight findings by methodological strength, not by how confidently the abstract is written. A small-sample, unreplicated result is logged as weak evidence even if its framing is bold. Considers venue quality, sample size, methodology rigor, funding/conflicts, and replication status.
- **Contradiction flagging** — when a paper conflicts with one already analyzed, mark it for the comparative stage rather than quietly preferring one.

**Loops back when:** a paper reveals a whole relevant subfield or seminal work the search missed → return to Stage 1 with new terms.

---

## Stage 3 — Comparative Analysis

**Behavior:** Move from per-paper records to cross-cutting structure. Cluster the literature by approach or school of thought, then build comparison dimensions (method, assumptions, data, results, conditions where each wins). The output is a *map* of the field, not a pile of summaries.

**Decisions:**
- **What dimensions to compare on** — chosen from what the papers actually contest, not a generic template. If the field's real fight is over evaluation methodology, that's the spine of the comparison.
- **Resolving conflicts** — when results disagree, investigate *why* (different datasets? metrics? populations?) before declaring a winner. Willing to conclude "it depends on X" rather than forcing a ranking.
- **Consensus vs. contested** — explicitly separate what the field agrees on from what's still open.

**Produces the gap analysis:** questions no paper answers, untested assumptions, methods not yet combined, populations not yet studied.

---

## Stage 4 — Report Writing

**Behavior:** Audience-first. Structure, depth, and vocabulary are chosen from the audience identified in scoping (a domain expert wants methodology detail and hedging; an executive wants the bottom line and implications). Confidence labels from earlier stages carry through — hedge where evidence is thin, state plainly where it's strong, rather than flattening to a uniform confident tone.

**Decisions:** What to include vs. cut; how to order for the reader's needs vs. the logical structure; how heavily to cite. Every non-obvious claim carries its provenance.

**Self-check before finishing:** the agent reviews its own draft against the source records — is each claim supported, is anything overstated, are the disagreements represented fairly, did any unsourced assertion sneak in? This critique pass is where much of the quality comes from and is built in explicitly.

---

## Stage 5 — Presentation Generation

**Behavior:** Distill, don't compress. A presentation is a re-authoring around 3–5 key messages with a narrative arc, not the report with bullets. Decide the through-line first, then select only the evidence that serves it.

**Decisions:** Which findings are headline vs. backup; where a visual (comparison table, timeline, trend) communicates better than text; how much nuance to keep vs. move to an appendix or speaker notes so the main flow stays clean.

---

## Cross-Cutting Decision-Making

These govern behavior at every stage and are where most "is this agent trustworthy" judgments live.

**When to escalate to a human.** Pause and ask — don't guess — when: scope is genuinely ambiguous; the literature is too thin to answer confidently; a fundamental contradiction can't be resolved; or a finding is high-stakes enough that a wrong call has real cost. Everything else is handled autonomously. The skill is asking *rarely but at the right moments* — an agent that asks constantly is useless, one that never asks is dangerous.

**Stopping criteria in general.** Each stage needs a defined "good enough" signal (saturation for search, coverage of the question for analysis, a stable field-map for comparison) plus a hard budget ceiling as backstop. The agent reports *which* criterion stopped it — natural completion vs. hitting the budget — because those mean very different things about output quality.

**Handling its own uncertainty.** When the agent doesn't know, it says so and characterizes the gap rather than filling it with plausible-sounding synthesis presented as fact. "The literature doesn't address X" is a valid and valuable finding.

**Memory and auditability.** The agent keeps persistent project state — every paper, every extraction, every decision and why — so the whole run is reconstructable. This makes loops cheap, lets a human inspect reasoning, and lets the agent resume rather than restart.S