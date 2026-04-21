import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.anyio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.anyio
async def test_whale_monitor_page_route():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/whale-monitor")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_skill_page_inline_script_has_valid_js():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")

    html = Path("app/static/skill.html").read_text(encoding="utf-8")
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    inline_js = html[start:end]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(inline_js)
        temp_path = Path(handle.name)

    try:
        result = subprocess.run([node, "--check", str(temp_path)], capture_output=True, text=True)
    finally:
        temp_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
