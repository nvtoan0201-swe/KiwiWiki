"""Raising and resolving human escalations.

Raising persists an `open` escalation, pauses the run, and flips the project to
`awaiting_input`. Resolving validates the user's response against the offered
options, stores it, and the API layer re-queues the run; the runner hands the
response to the raising stage via `StageContext.escalation_response`.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    AuditActionType,
    EscalationStatus,
    EscalationTrigger,
    ProjectStatus,
)
from app.core.errors import NotFound, ValidationError
from app.db.models import Escalation, Project, Run
from app.events.publisher import EventPublisher
from app.services.audit import AuditService


async def raise_escalation(
    session: AsyncSession,
    audit: AuditService,
    events: EventPublisher,
    *,
    project: Project,
    run: Run,
    stage: str,
    trigger: EscalationTrigger,
    question: str,
    context: dict[str, Any] | None = None,
    options: list[dict[str, Any]] | None = None,
) -> Escalation:
    escalation = Escalation(
        project_id=project.id,
        run_id=run.id,
        trigger=trigger.value,
        question=question,
        context={**(context or {}), "_raised_at_stage": stage},
        options=options or [],
        status=EscalationStatus.open.value,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.add(escalation)
    project.status = ProjectStatus.awaiting_input.value
    run.status = "paused"
    await session.flush()

    await audit.record(
        project_id=project.id,
        action_type=AuditActionType.escalation_raised,
        description=f"Escalation ({trigger.value}): {question}",
        reasoning="The agent needs user input before it can safely continue.",
        payload={"escalation_id": escalation.id, "options": escalation.options},
        run_id=run.id,
        stage=stage,
    )
    await events.emit(
        "escalation_raised",
        stage=stage,
        payload={
            "escalation_id": escalation.id,
            "trigger": trigger.value,
            "question": question,
            "options": escalation.options,
        },
    )
    return escalation


def validate_response(escalation: Escalation, user_response: dict[str, Any]) -> None:
    """Best-effort validation of a response against the offered options.

    Two recognized shapes:
    - flat options `[{id, label, ...}]` answered by `{"selected_option": id}`;
    - nested ambiguities `[{id, question, options: [...]}]` answered by
      `{"resolutions": {ambiguity_id: option_id}}`.
    Free-text fields (`notes`, custom answers) are always allowed alongside.
    """
    if not isinstance(user_response, dict) or not user_response:
        raise ValidationError("Escalation response must be a non-empty object")

    options = escalation.options or []
    if not options:
        return

    nested = all(isinstance(o, dict) and isinstance(o.get("options"), list) for o in options)
    if nested:
        resolutions = user_response.get("resolutions")
        if not isinstance(resolutions, dict) or not resolutions:
            raise ValidationError(
                "Response must include 'resolutions' mapping ambiguity ids to chosen options"
            )
        by_id = {str(o.get("id")): o for o in options}
        for ambiguity_id, choice in resolutions.items():
            ambiguity = by_id.get(str(ambiguity_id))
            if ambiguity is None:
                raise ValidationError(f"Unknown ambiguity id: {ambiguity_id}")
            allowed = {
                str(opt.get("id", opt.get("label")))
                for opt in ambiguity["options"]
                if isinstance(opt, dict)
            }
            if allowed and str(choice) not in allowed and not isinstance(choice, dict):
                raise ValidationError(
                    f"Choice {choice!r} is not an offered option for ambiguity {ambiguity_id}"
                )
        return

    selected = user_response.get("selected_option")
    if selected is None:
        raise ValidationError("Response must include 'selected_option'")
    allowed = {str(o.get("id", o.get("label"))) for o in options if isinstance(o, dict)}
    if allowed and str(selected) not in allowed:
        raise ValidationError(f"'{selected}' is not one of the offered options")


async def resolve_escalation(
    session: AsyncSession,
    escalation_id: str,
    user_response: dict[str, Any],
) -> Escalation:
    """Validate and store the user's response. The caller re-queues the run."""
    escalation = await session.get(Escalation, escalation_id)
    if escalation is None:
        raise NotFound(f"Escalation {escalation_id} not found")
    if escalation.status != EscalationStatus.open.value:
        raise ValidationError(f"Escalation {escalation_id} is already {escalation.status}")

    validate_response(escalation, user_response)

    escalation.user_response = user_response
    escalation.status = EscalationStatus.resolved.value
    escalation.resolved_at = datetime.datetime.now(datetime.UTC)
    await session.flush()

    audit = AuditService(session)
    await audit.record(
        project_id=escalation.project_id,
        action_type=AuditActionType.escalation_resolved,
        description=f"Escalation resolved: {escalation.question}",
        reasoning="User provided the requested input; the run can resume.",
        payload={"escalation_id": escalation.id, "user_response": user_response},
        run_id=escalation.run_id,
        stage=(escalation.context or {}).get("_raised_at_stage"),
    )
    return escalation


async def latest_resolved_for_stage(
    session: AsyncSession, run: Run, stage: str, since: datetime.datetime | None
) -> Escalation | None:
    """The most recent escalation resolved for this run's current stage attempt,
    i.e. resolved after the stage execution started — that response belongs to
    the handler now re-entering."""
    query = (
        select(Escalation)
        .where(
            Escalation.run_id == run.id,
            Escalation.status == EscalationStatus.resolved.value,
        )
        .order_by(Escalation.resolved_at.desc())
        .limit(1)
    )
    escalation = (await session.execute(query)).scalars().first()
    if escalation is None:
        return None
    if (escalation.context or {}).get("_raised_at_stage") != stage:
        return None
    if since is not None and escalation.resolved_at is not None:
        resolved_at = escalation.resolved_at
        started = since
        # SQLite returns naive datetimes; compare in UTC consistently.
        if resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=datetime.UTC)
        if started.tzinfo is None:
            started = started.replace(tzinfo=datetime.UTC)
        if resolved_at < started:
            return None
    return escalation
