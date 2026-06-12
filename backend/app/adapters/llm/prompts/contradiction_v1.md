# Contradiction check

A newly analyzed paper makes this claim:

> {new_claim}

(paper: {new_title})

Below are claims from already-analyzed papers on nearby topics. Flag every
candidate whose claim **genuinely conflicts** with the new claim — they cannot
both be right as stated, or they report opposing results for the same
question.

Do NOT flag:
- papers that merely study different aspects or use different framings;
- differences fully explained by scope stated in the claims themselves.

Do NOT pick a winner or judge which claim is right — that investigation
happens later. Just describe what the disagreement is.

## Candidate claims

{candidates}

Return a flag per real conflict, using the candidate's `index` exactly as
given, with a neutral one-or-two-sentence `description` of the disagreement.
Return no flags if nothing genuinely conflicts.
