"""Import every model so the shared metadata (and Alembic autogenerate) sees them."""

from app.db.models.audit_log import AuditLogEntry
from app.db.models.budget_ledger import BudgetLedgerEntry
from app.db.models.clusters import Cluster
from app.db.models.comparisons import Comparison
from app.db.models.contradictions import Contradiction
from app.db.models.escalations import Escalation
from app.db.models.gaps import Gap
from app.db.models.paper_analyses import PaperAnalysis
from app.db.models.presentations import Presentation
from app.db.models.projects import Project
from app.db.models.provenance import Provenance
from app.db.models.reports import Report
from app.db.models.runs import Run
from app.db.models.sources import Source
from app.db.models.stage_executions import StageExecution

__all__ = [
    "AuditLogEntry",
    "BudgetLedgerEntry",
    "Cluster",
    "Comparison",
    "Contradiction",
    "Escalation",
    "Gap",
    "PaperAnalysis",
    "Presentation",
    "Project",
    "Provenance",
    "Report",
    "Run",
    "Source",
    "StageExecution",
]
