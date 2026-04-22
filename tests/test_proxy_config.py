import pytest
from httpx import ASGITransport, AsyncClient

from app.common import http_client
from app.main import app
from app.news import okx_orbit


def test_resolve_proxy_url_uses_settings_when_env_missing(monkeypatch):
    monkeypatch.delenv("PROXY_URL", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.setattr(http_client.settings, "proxy_url", "socks5://127.0.0.1:7890")

    assert http_client._resolve_proxy_url() == "socks5://127.0.0.1:7890"
    status = http_client.get_proxy_status()
    assert status["configured"] is True
    assert status["url"] == "socks5://127.0.0.1:7890"


def test_resolve_proxy_url_prefers_env_over_settings(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://10.0.0.8:8080")
    monkeypatch.setattr(http_client.settings, "proxy_url", "socks5://127.0.0.1:7890")

    assert http_client._resolve_proxy_url() == "http://10.0.0.8:8080"


@pytest.mark.anyio
async def test_health_reports_proxy_configured(monkeypatch):
    monkeypatch.setenv("PROXY_URL", "http://10.0.0.8:8080")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["proxy_configured"] is True


def test_okx_host_is_not_forced_through_proxy():
    assert http_client._needs_proxy("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT") is False


@pytest.mark.anyio
async def test_orbit_sentiment_surfaces_upstream_warning(monkeypatch):
    async def fake_orbit_get(*args, **kwargs):
        return {"code": "50026", "data": None, "msg": ""}

    monkeypatch.setattr(okx_orbit, "_orbit_get", fake_orbit_get)

    payload = await okx_orbit.get_coin_sentiment(coins="DOGE", period="24h")

    assert payload["count"] == 0
    assert payload["code"] == "50026"
    assert payload["warning"] == "OKX Orbit is currently app-only; the public web Orbit API is unavailable"
