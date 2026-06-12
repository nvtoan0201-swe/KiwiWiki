# Draft a report section

Research question:

> {research_question}

Audience: {audience}. {tone_note}

Draft the section **{section_title}** — purpose: {section_purpose}
(depth: {section_depth}).

Write it as structured claims, not free prose:
- `lead_in` (optional): connective framing only — it must contain **no
  factual claims**.
- `claims`: each entry is one claim or finding, phrased for the audience.
  - Cite the roster papers it rests on via `source_indexes` and give a
    `passage` (≤15-word quote or paraphrase + locator) from one of them.
  - Give an honest `confidence_label` (`well_established` / `emerging` /
    `contested` / `speculative`) and let it shape the wording: hedge what is
    emerging or contested, state plainly only what is well established. Do
    not flatten everything into confident prose.
  - If a claim is your own synthesis rather than something a paper states,
    set `is_inference` to true (and cite the papers it builds on, if any).
- Ground every claim in the field map and roster below — never in
  imagination. Where sources disagree, present the disagreement; do not
  silently resolve it.

## Field map (clusters, matrix, consensus/contested)

{field_map}

## Analyzed papers (roster)

{roster}
