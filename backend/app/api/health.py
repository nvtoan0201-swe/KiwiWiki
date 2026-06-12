"""Health check — confirms DB and Redis connectivity."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session

logger = logging.getLogger("app.health")
router = APIRouter(tags=["health"])


async def _check_db(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: db check failed", extra={"extra": {"error": str(exc)}})
        return False


async def _check_redis() -> bool:
    try:
        import redis.asyncio as redis

        client = redis.from_url(get_settings().redis_url)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("health: redis check failed", extra={"extra": {"error": str(exc)}})
        return False


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    db_ok = await _check_db(session)
    redis_ok = await _check_redis()
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "model": get_settings().agent_model,
    }
