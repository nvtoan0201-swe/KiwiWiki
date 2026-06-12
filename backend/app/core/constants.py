"""Canonical enums for the whole system (overview §4).

Defined once here; the frontend mirrors them in `api/types.ts`. Every
state-changing operation references these — keep the string values stable, they
are part of the persisted data and the API contract.
"""

from enum import Enum


class ProjectStatus(str, Enum):
    draft = "draft"
    scoping = "scoping"
    awaiting_input = "awaiting_input"
    running = "running"
    paused = "paused"
    complete = "complete"
    failed = "failed"


class Stage(str, Enum):
    scoping = "scoping"
    literature_search = "literature_search"
    paper_analysis = "paper_analysis"
    comparative_analysis = "comparative_analysis"
    gap_analysis = "gap_analysis"
    report_writing = "report_writing"
    presentation_generation = "presentation_generation"


class ConfidenceLabel(str, Enum):
    well_established = "well_established"
    emerging = "emerging"
    contested = "contested"
    speculative = "speculative"


class TriageStatus(str, Enum):
    deep_read = "deep_read"
    skimmed = "skimmed"
    set_aside = "set_aside"
    excluded = "excluded"


class DiscoveryChannel(str, Enum):
    keyword_search = "keyword_search"
    citation_snowball = "citation_snowball"
    user_supplied = "user_supplied"


class EscalationStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    auto_resolved = "auto_resolved"


class AuditActionType(str, Enum):
    stage_start = "stage_start"
    stage_complete = "stage_complete"
    search_run = "search_run"
    query_reformulated = "query_reformulated"
    paper_triaged = "paper_triaged"
    paper_analyzed = "paper_analyzed"
    contradiction_flagged = "contradiction_flagged"
    contradiction_investigated = "contradiction_investigated"
    cluster_assigned = "cluster_assigned"
    comparison_updated = "comparison_updated"
    gap_identified = "gap_identified"
    report_drafted = "report_drafted"
    self_check_completed = "self_check_completed"
    report_revised = "report_revised"
    presentation_generated = "presentation_generated"
    loop_back = "loop_back"
    escalation_raised = "escalation_raised"
    escalation_resolved = "escalation_resolved"
    budget_warning = "budget_warning"
    stopped = "stopped"
    error = "error"


class StoppingCriterion(str, Enum):
    saturation = "saturation"
    coverage = "coverage"
    stable_map = "stable_map"
    budget = "budget"
    user_stopped = "user_stopped"
    error = "error"


class BudgetCategory(str, Enum):
    llm_tokens = "llm_tokens"
    search_calls = "search_calls"
    papers_read = "papers_read"
    time = "time"


class EscalationTrigger(str, Enum):
    ambiguous_scope = "ambiguous_scope"
    thin_literature = "thin_literature"
    unresolved_contradiction = "unresolved_contradiction"
    high_stakes = "high_stakes"


class ProvenanceContext(str, Enum):
    analysis = "analysis"
    comparison = "comparison"
    gap = "gap"
    report = "report"
    presentation = "presentation"


class GapImportance(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
