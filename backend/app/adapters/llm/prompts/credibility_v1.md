# Credibility assessment

Assess the evidential weight of this paper from its **method**, not its tone.
A bold, assertive abstract does not raise credibility; a small-sample,
unreplicated result is weak evidence regardless of framing.

## Paper

Title: {title}
Venue: {venue} ({year})
Core claim: {core_claim}
Method: {method}
Key results: {results}
Author-stated limitations: {limitations}

Score each signal from 0.0 (weak) to 1.0 (strong), with a one-line note:

- `venue_quality`: peer-reviewed venue standing, judged from the venue name
  and available metadata only. Do NOT fabricate impact factors or rankings —
  if you cannot tell, mark `known=false` and score 0.5.
- `sample_size_power`: sample size / statistical power signals in the method
  and results.
- `methodology_rigor`: design type, controls, baselines, ablations,
  preregistration if known.
- `conflicts_of_interest`: funding or conflicts **if disclosed**; if nothing
  is disclosed either way, mark `known=false` and score 0.5.
- `replication_status`: replicated or independently confirmed if discoverable
  from the material given; otherwise `known=false`, score 0.5.

For any signal the material genuinely does not show, use `known=false` and a
neutral 0.5 — never guess in either direction.
