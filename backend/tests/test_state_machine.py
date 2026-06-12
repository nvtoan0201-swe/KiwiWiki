from app.core.constants import Stage
from app.orchestrator import state_machine


def test_forward_order_traverses_all_stages() -> None:
    seen = [state_machine.FIRST_STAGE]
    while (nxt := state_machine.next_stage(seen[-1])) is not None:
        seen.append(nxt)
    assert seen == [
        Stage.scoping,
        Stage.literature_search,
        Stage.paper_analysis,
        Stage.comparative_analysis,
        Stage.gap_analysis,
        Stage.report_writing,
        Stage.presentation_generation,
    ]


def test_next_stage_of_last_is_none() -> None:
    assert state_machine.next_stage(Stage.presentation_generation) is None


def test_permitted_loop_backs() -> None:
    assert state_machine.can_loop_back(Stage.paper_analysis, Stage.literature_search)
    assert state_machine.can_loop_back(Stage.comparative_analysis, Stage.paper_analysis)
    assert state_machine.can_loop_back(Stage.comparative_analysis, Stage.literature_search)
    assert state_machine.can_loop_back(Stage.report_writing, Stage.comparative_analysis)


def test_forbidden_loop_backs() -> None:
    assert not state_machine.can_loop_back(Stage.scoping, Stage.literature_search)
    assert not state_machine.can_loop_back(Stage.literature_search, Stage.scoping)
    assert not state_machine.can_loop_back(Stage.paper_analysis, Stage.comparative_analysis)
    assert not state_machine.can_loop_back(Stage.report_writing, Stage.scoping)
    assert not state_machine.can_loop_back(Stage.presentation_generation, Stage.report_writing)
