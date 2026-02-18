from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from app.api.router import router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.init import init_db


def create_app(*, init_db_on_startup: bool = True) -> FastAPI:
    app = FastAPI(title="cryptoarbitrajbot API", version="0.1.0")
    app.include_router(router)

    @app.on_event("startup")
    async def _startup() -> None:
        setup_logging(settings.log_level)
        if init_db_on_startup:
            await init_db()

    return app


app = create_app()


def run() -> None:
    uvicorn.run(
        "app.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()

