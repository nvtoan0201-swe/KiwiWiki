"""Stage handlers, one module per workflow stage.

`build_default_registry()` wires the real handler for every stage of the
workflow (all phases through 5 have landed). The orchestrator stays decoupled
from individual stage logic — tests still swap stubs in via the registry.
"""

from __future__ import annotations

from app.orchestrator.registry import StageRegistry


def build_default_registry() -> StageRegistry:
    from app.stages.analysis.handler import PaperAnalysisHandler
    from app.stages.comparison.handler import ComparativeAnalysisHandler
    from app.stages.gap.handler import GapAnalysisHandler
    from app.stages.presentation.handler import PresentationGenerationHandler
    from app.stages.report.handler import ReportWritingHandler
    from app.stages.scoping.handler import ScopingHandler
    from app.stages.search.handler import LiteratureSearchHandler

    registry = StageRegistry()
    registry.register(ScopingHandler())
    registry.register(LiteratureSearchHandler())
    registry.register(PaperAnalysisHandler())
    registry.register(ComparativeAnalysisHandler())
    registry.register(GapAnalysisHandler())
    registry.register(ReportWritingHandler())
    registry.register(PresentationGenerationHandler())
    return registry
