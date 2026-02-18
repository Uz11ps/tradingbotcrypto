from __future__ import annotations

import httpx

from app.api.main import create_app


async def test_health() -> None:
    app = create_app(init_db_on_startup=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

