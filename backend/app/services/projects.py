"""Project CRUD. Creating a project writes an audit entry (overview §4)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import AuditActionType, ProjectStatus, Stage
from app.core.errors import NotFound
from app.db.models import Project
from app.schemas.projects import ProjectCreate, ProjectUpdate
from app.services.audit import AuditService


def _derive_title(create: ProjectCreate) -> str:
    if create.title:
        return create.title
    text = create.original_request.strip()
    return text if len(text) <= 80 else text[:77] + "..."


class ProjectService:
    def __init__(self, session: AsyncSession, audit: AuditService | None = None) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def create(self, data: ProjectCreate) -> Project:
        settings = get_settings()
        project = Project(
            title=_derive_title(data),
            original_request=data.original_request,
            audience=data.audience,
            outputs_requested=data.outputs_requested or ["report"],
            budget=data.budget or settings.default_budget,
            status=ProjectStatus.draft.value,
        )
        self._session.add(project)
        await self._session.flush()
        await self._audit.record(
            project_id=project.id,
            action_type=AuditActionType.stage_start,
            description=f"Project created: {project.title}",
            reasoning="User submitted a new research request.",
            stage=Stage.scoping.value,
        )
        return project

    async def get(self, project_id: str) -> Project:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFound(f"Project {project_id} not found")
        return project

    async def list(self, limit: int = 50, offset: int = 0) -> tuple[list[Project], int]:
        total = await self._session.scalar(select(func.count()).select_from(Project)) or 0
        result = await self._session.execute(
            select(Project).order_by(Project.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), int(total)

    async def update(self, project_id: str, data: ProjectUpdate) -> Project:
        project = await self.get(project_id)
        fields = data.model_dump(exclude_unset=True)
        for key, value in fields.items():
            if key in {"status", "current_stage"} and value is not None:
                value = value.value if hasattr(value, "value") else value
            setattr(project, key, value)
        await self._session.flush()
        # Reload server-side onupdate values (updated_at) so serialization
        # doesn't trigger a lazy load outside the async context.
        await self._session.refresh(project)
        return project

    async def archive(self, project_id: str) -> None:
        """Hard-delete a project. FK cascades remove dependent rows (including this
        project's audit_log), so we don't write an audit entry that would be
        immediately cascade-deleted. Phase 7 covers soft-archive + export bundles."""
        project = await self.get(project_id)
        await self._session.delete(project)
        await self._session.flush()
