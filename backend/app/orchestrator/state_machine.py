"""The legal stage transitions: forward order plus permitted loop-back targets.

Forward order is the declaration order of the `Stage` enum. Loop-backs are an
explicit allowlist (phase 1 spec); anything else is rejected by the runner.
"""

from __future__ import annotations

from app.core.constants import Stage

_ORDER: list[Stage] = list(Stage)
_INDEX: dict[Stage, int] = {stage: i for i, stage in enumerate(_ORDER)}

FIRST_STAGE: Stage = _ORDER[0]

LOOP_BACK_TARGETS: dict[Stage, frozenset[Stage]] = {
    Stage.paper_analysis: frozenset({Stage.literature_search}),
    Stage.comparative_analysis: frozenset({Stage.paper_analysis, Stage.literature_search}),
    Stage.report_writing: frozenset({Stage.comparative_analysis}),
}


def next_stage(current: Stage) -> Stage | None:
    """The stage after `current` in forward order, or None past the last stage."""
    index = _INDEX[current] + 1
    return _ORDER[index] if index < len(_ORDER) else None


def can_loop_back(from_stage: Stage, to_stage: Stage) -> bool:
    return to_stage in LOOP_BACK_TARGETS.get(from_stage, frozenset())
