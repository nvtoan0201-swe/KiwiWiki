"""Insert one sample draft project for manual testing.

    python -m scripts.seed

Idempotent enough for dev: it just adds a draft project and prints its id, which
you can then open over the WS or drive through the API.
"""

from __future__ import annotations

import asyncio

from app.db.session import dispose_engine, get_sessionmaker
from app.schemas.projects import ProjectCreate
from app.services.projects import ProjectService


async def main() -> None:
    async with get_sessionmaker()() as session:
        service = ProjectService(session)
        project = await service.create(
            ProjectCreate(
                original_request=(
                    "What are the most effective approaches to retrieval-augmented "
                    "generation for long-context question answering, and how do they compare?"
                ),
                audience="domain_expert",
                outputs_requested=["report", "presentation"],
            )
        )
        await session.commit()
        print(f"Seeded draft project: {project.id} — {project.title}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
