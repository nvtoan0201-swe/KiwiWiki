"""Evaluation harness (phase 7 part B).

Quality gates for the trust properties the system asserts: groundedness,
calibrated confidence, right-moment escalation, saturation behavior,
self-check efficacy, and budget adherence. Every check here is deterministic
(fake sources, scripted LLM) so it can gate CI; LLM-judged variants of these
checks require a real key and are explicitly out of scope for the gates.

Run `python -m eval.run` from `backend/` to produce a scorecard artifact, or
let `tests/test_eval_scorecard.py` enforce the gates under pytest.
"""
