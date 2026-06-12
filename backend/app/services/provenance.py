"""Provenance: every agent-produced claim is traceable or explicitly inferred.

The invariant (enforced in `attach`): a provenance row must either point at a
source passage (`source_id` + `passage`) or be flagged `is_inference=True`.
Emitting an unsourced, un-flagged claim is a bug, so this service refuses it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ConfidenceLabel, ProvenanceContext
from app.core.errors import ValidationError
from app.db.models import Provenance


class ProvenanceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def attach(
        self,
        *,
        project_id: str,
        claim_text: str,
        context: ProvenanceContext,
        ref_id: str | None = None,
        source_id: str | None = None,
        passage: str | None = None,
        is_inference: bool = False,
        confidence_label: ConfidenceLabel | None = None,
    ) -> Provenance:
        has_source = source_id is not None and passage is not None and passage.strip() != ""
        if not has_source and not is_inference:
            raise ValidationError(
                "Provenance requires either a source passage (source_id + passage) "
                "or is_inference=True.",
                {"claim_text": claim_text},
            )

        row = Provenance(
            project_id=project_id,
            claim_text=claim_text,
            source_id=source_id,
            passage=passage,
            is_inference=is_inference,
            confidence_label=confidence_label.value if confidence_label else None,
            context=context.value,
            ref_id=ref_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def trace(self, ref_id: str) -> list[Provenance]:
        result = await self._session.execute(select(Provenance).where(Provenance.ref_id == ref_id))
        return list(result.scalars().all())
