import pytest
from httpx import AsyncClient, ASGITransport
from app.skills.loader import load_all_skills
from app.main import app

load_all_skills()


@pytest.mark.anyio
async def test_list_skills():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/skills")
    assert resp.status_code == 200
    skills = resp.json()
    names = {s["name"] for s in skills}
    assert "health_check" in names
    assert "investigate" in names


@pytest.mark.anyio
async def test_run_skill_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/skills/nonexistent/run", json={"params": {}})
    assert resp.status_code == 404
