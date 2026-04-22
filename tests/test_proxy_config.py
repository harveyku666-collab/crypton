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


@pytest.mark.anyio
async def test_okx_cli_coin_news_normalizes_payload(monkeypatch):
    async def fake_run_okx_cli_json(*args, **kwargs):
        return {
            "details": [
                {
                    "id": "cli-1",
                    "title": "CLI BTC article",
                    "summary": "From installed OKX CLI.",
                    "content": "From installed OKX CLI.",
                    "sourceUrl": "/353567",
                    "platformList": ["aicoin"],
                    "ccyList": ["BTC"],
                    "importance": "high",
                    "sentiment": "bullish",
                    "cTime": "1776790261000",
                }
            ],
            "nextCursor": "cursor-1",
        }

    monkeypatch.setattr(okx_orbit.settings, "okx_news_source", "cli")
    monkeypatch.setattr(okx_orbit, "_run_okx_cli_json", fake_run_okx_cli_json)

    payload = await okx_orbit.get_news_by_coin(coins="BTC", language="zh-CN", limit=3)

    assert payload["backend"] == "okx_cli"
    assert payload["count"] == 1
    assert payload["items"][0]["source"] == "okx_cli_news"
    assert payload["items"][0]["source_url"] == "https://www.aicoin.com/353567"
    assert payload["next_cursor"] == "cursor-1"


@pytest.mark.anyio
async def test_okx_cli_coin_trend_normalizes_payload(monkeypatch):
    async def fake_run_okx_cli_json(*args, **kwargs):
        return [
            {
                "details": [
                    {
                        "ccy": "BTC",
                        "mentionCnt": "6",
                        "sentiment": {
                            "label": "bullish",
                            "bullishRatio": "0.5",
                            "bearishRatio": "0.1",
                        },
                        "trend": [
                            {"ts": "1776804859000", "bullishRatio": "1", "bearishRatio": "0", "mentionCnt": "1"},
                            {"ts": "1776803156000", "bullishRatio": "0", "bearishRatio": "0", "mentionCnt": "1"},
                        ],
                    }
                ]
            }
        ]

    monkeypatch.setattr(okx_orbit.settings, "okx_news_source", "cli")
    monkeypatch.setattr(okx_orbit, "_run_okx_cli_json", fake_run_okx_cli_json)

    payload = await okx_orbit.get_coin_sentiment(coins="BTC", period="24h", trend_points=2)

    assert payload["backend"] == "okx_cli"
    assert payload["count"] == 1
    assert payload["items"][0]["symbol"] == "BTC"
    assert payload["items"][0]["mention_count"] == 6
    assert len(payload["items"][0]["trend"]) == 2


@pytest.mark.anyio
async def test_okx_cli_sentiment_ranking_normalizes_payload(monkeypatch):
    async def fake_run_okx_cli_json(*args, **kwargs):
        return [
            {
                "details": [
                    {
                        "ccy": "BTC",
                        "mentionCnt": "1576",
                        "sentiment": {
                            "label": "neutral",
                            "bullishRatio": "0.42",
                            "bearishRatio": "0.11",
                        },
                    }
                ]
            }
        ]

    monkeypatch.setattr(okx_orbit.settings, "okx_news_source", "cli")
    monkeypatch.setattr(okx_orbit, "_run_okx_cli_json", fake_run_okx_cli_json)

    payload = await okx_orbit.get_sentiment_ranking(period="24h", sort_by="hot", limit=5)

    assert payload["backend"] == "okx_cli"
    assert payload["count"] == 1
    assert payload["sort_by"] == "hot"
    assert payload["items"][0]["symbol"] == "BTC"
    assert payload["items"][0]["bullish_ratio"] == 0.42
