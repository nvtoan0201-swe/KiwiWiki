# Report self-check

You are reviewing your own report draft against the source records before it
ships. Be adversarial with yourself: an unsupported claim that reaches the
reader is a defect.

For every claim in the draft below, check:
1. **Support** — is the claim backed by its cited passage(s)? A claim with no
   sources must carry the inference flag.
2. **Calibration** — is the wording stronger than its confidence label and the
   sources' credibility justify?
3. **Fairness** — where sources disagree, is the disagreement represented
   fairly, or has one side been silently picked?
4. **Leakage** — did any unsourced, un-flagged assertion sneak in?

Report only the claims that fail, as `findings`. For each give the
`section_index` and `claim_index` exactly as numbered in the draft, the
`issue` (`unsupported` / `overstated` / `unfair_disagreement` /
`unflagged_assertion`), and the `action`:
- `soften` — supply `revised_text` (and `revised_confidence` if the label
  must drop);
- `remove` — the claim cannot be salvaged;
- `re_ground` — the claim is right but mis-cited: supply the correct
  `source_indexes` and `passage` (and `revised_text` if the wording must
  change).

Finish with a one-paragraph `summary` of the draft's overall support,
calibration, and fairness. If nothing fails, return an empty `findings` list.

## Draft claims (by section)

{draft}

## Source records (roster)

{roster}
