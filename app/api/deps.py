from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

SessionDep = AsyncSession

__all__ = ["get_session", "SessionDep"]

