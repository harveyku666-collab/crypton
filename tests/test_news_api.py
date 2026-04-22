import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.news.market_overview import get_market_overview_snapshot
from app.news.okx_fallback import _extract_symbols
from app.news.token_matching import build_search_terms, item_matches_terms
from app.news.url_utils import normalize_news_source_url


def test_normalize_news_source_url_expands_desk3_relative_path():
    assert normalize_news_source_url("/353567", source="desk3") == "https://www.aicoin.com/353567"


def test_extract_symbols_does_not_false_positive_eth_from_elizabeth():
    symbols = _extract_symbols(
        "地缘政治 | 美联储主席提名人 Kevin Warsh 听证会遭质询",
        "Senator Elizabeth Warren 质疑其可能为加密公司提供特殊账户。",
    )

    assert "ETH" not in symbols


def test_item_matches_terms_uses_word_boundaries_for_eth():
    item = {
        "title": "美联储主席提名人 Kevin Warsh 听证会遭质询",
        "summary": "Senator Elizabeth Warren raises concerns.",
        "excerpt": "",
        "content": "",
        "coins": [],
    }

    assert item_matches_terms(item, build_search_terms("ETH")) is False


@pytest.mark.anyio
async def test_news_market_overview_endpoint(monkeypatch):
    async def fake_market_overview_snapshot(*, symbols=None, limit=10, movers=3):
        return {
            "timestamp": "2026-04-20T12:00:00+00:00",
            "sentiment": "➡️ 震荡",
            "sentiment_label": "neutral",
            "avg_change_24h": 0.42,
            "up_count": 6,
            "down_count": 4,
            "flat_count": 0,
            "tracked_count": 10,
            "requested_symbols": list(symbols or ("BTC", "ETH")),
            "unavailable_symbols": [],
            "top_gainers": [{"symbol": "BTC", "change_24h": 2.5, "exchange": "binance"}],
            "top_losers": [{"symbol": "ETH", "change_24h": -1.8, "exchange": "okx"}],
            "tickers": [],
            "sources": {"binance": 7, "okx": 3},
        }

    monkeypatch.setattr("app.news.router.get_market_overview_snapshot", fake_market_overview_snapshot)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/news/market-overview",
            params={"symbols": "btc,eth,sol", "limit": 8, "movers": 2},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["sentiment_label"] == "neutral"
    assert data["requested_symbols"] == ["BTC", "ETH", "SOL"]
    assert data["top_gainers"][0]["symbol"] == "BTC"
    assert data["top_losers"][0]["symbol"] == "ETH"


@pytest.mark.anyio
async def test_market_overview_snapshot_summarizes_changes(monkeypatch):
    async def fake_fetch_symbol_snapshot(symbol: str):
        sample = {
            "BTC": {"symbol": "BTC", "price": 100000, "change_24h": 3.2, "exchange": "binance"},
            "ETH": {"symbol": "ETH", "price": 3000, "change_24h": -1.5, "exchange": "okx"},
            "SOL": {"symbol": "SOL", "price": 180, "change_24h": 1.3, "exchange": "binance"},
        }
        return sample.get(symbol)

    monkeypatch.setattr("app.news.market_overview._fetch_symbol_snapshot", fake_fetch_symbol_snapshot)

    payload = await get_market_overview_snapshot(symbols=("BTC", "ETH", "SOL"), limit=3, movers=2)

    assert payload["tracked_count"] == 3
    assert payload["up_count"] == 2
    assert payload["down_count"] == 1
    assert payload["avg_change_24h"] == 1.0
    assert payload["top_gainers"][0]["symbol"] == "BTC"
    assert payload["top_losers"][0]["symbol"] == "ETH"
