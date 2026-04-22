import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.analysis.okx_market_intel import _prioritize_important_news, build_market_intel_master
from app.market.sources import okx
from app.market.sources.okx import _normalize_orderbook, _normalize_trade_rows
from app.news import translation as news_translation


@pytest.mark.anyio
async def test_okx_news_search_uses_fallback_when_orbit_fails(monkeypatch):
    async def fake_search_news(**kwargs):
        raise RuntimeError("orbit reset")

    async def fake_fallback_news_payload(**kwargs):
        return {
            "kind": "search",
            "language": "en-US",
            "items": [
                {
                    "id": "fallback-1",
                    "title": "Fallback BTC article",
                    "summary": "Recovered from internal index.",
                    "excerpt": "Recovered from internal index.",
                    "content": "Recovered from internal index.",
                    "platforms": ["desk3"],
                    "coins": ["BTC"],
                    "importance": "high",
                    "sentiment": "bullish",
                    "published_at": 1776600000000,
                    "source": "desk3",
                }
            ],
            "count": 1,
            "warning": "fallback active",
        }

    monkeypatch.setattr("app.news.router.okx_orbit.search_news", fake_search_news)
    monkeypatch.setattr("app.news.router.get_fallback_news_payload", fake_fallback_news_payload)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/news/okx/search", params={"keyword": "BTC", "language": "en-US"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["title"] == "Fallback BTC article"
    assert data["warning"] == "fallback active"


@pytest.mark.anyio
async def test_okx_overview_uses_market_intel_fallback_sections(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {"last": 100000.0, "price_change_pct_24h": 2.5},
            "diagnosis": {"price_oi_regime": "price_up_oi_up"},
            "indicator_summary": {},
            "orderbook": {"bids": [], "asks": []},
            "recent_trades": [],
        }

    async def empty_items(*args, **kwargs):
        return {"items": [], "count": 0}

    async def fake_market_intel_master(**kwargs):
        return {
            "daily_brief": {
                "coin_news": [
                    {
                        "id": "coin-fallback",
                        "title": "Coin fallback article",
                        "summary": "Fallback coin coverage.",
                        "excerpt": "Fallback coin coverage.",
                        "content": "Fallback coin coverage.",
                        "platforms": ["bitinfo"],
                        "coins": ["BTC"],
                        "importance": "high",
                        "sentiment": "bullish",
                        "published_at": 1776600000000,
                        "source": "bitinfo_intel",
                    }
                ],
                "important_news": [
                    {
                        "id": "important-fallback",
                        "title": "Important fallback article",
                        "summary": "Fallback important coverage.",
                        "excerpt": "Fallback important coverage.",
                        "content": "Fallback important coverage.",
                        "platforms": ["bitinfo"],
                        "coins": ["BTC"],
                        "importance": "high",
                        "sentiment": "neutral",
                        "published_at": 1776600000000,
                        "source": "bitinfo_intel",
                    }
                ],
            },
            "coin_sentiment": {
                "period": "1h",
                "items": [
                    {
                        "symbol": "BTC",
                        "label": "bullish",
                        "bullish_ratio": 0.67,
                        "bearish_ratio": 0.12,
                        "mention_count": 9,
                        "trend": [],
                    }
                ],
                "count": 1,
            },
            "sentiment_ranking": {
                "period": "1h",
                "sort_by": "hot",
                "items": [
                    {
                        "symbol": "BTC",
                        "label": "bullish",
                        "bullish_ratio": 0.67,
                        "bearish_ratio": 0.12,
                        "mention_count": 9,
                        "trend": [],
                    }
                ],
                "count": 1,
            },
        }

    monkeypatch.setattr("app.analysis.router.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_news_by_coin", empty_items)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_latest_news", empty_items)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_coin_sentiment", empty_items)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_sentiment_ranking", empty_items)
    monkeypatch.setattr("app.analysis.router.build_market_intel_master", fake_market_intel_master)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/analysis/okx/overview", params={"inst_id": "BTC-USDT-SWAP", "language": "en-US"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["coin_news"]["count"] == 1
    assert data["important_news"]["count"] == 1
    assert data["coin_sentiment"]["count"] == 1
    assert data["sentiment_ranking"]["count"] == 1
    assert data["coin_news"]["warning"] == "OKX coin news fallback active"
    assert data["sentiment_ranking"]["items"][0]["symbol"] == "BTC"
    assert data["source_meta"]["page_mode"] == "extended_dashboard"
    assert data["source_meta"]["strict_clone"] is False
    assert data["source_meta"]["strict_clone_path"] == "/market-intel"
    assert data["source_meta"]["uses_news_fallback"] is True
    assert "OKX coin news fallback active" in data["source_meta"]["warnings"]


@pytest.mark.anyio
async def test_okx_overview_reports_cli_news_source(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {"last": 100000.0, "price_change_pct_24h": 2.5},
            "diagnosis": {"price_oi_regime": "price_up_oi_up"},
            "indicator_summary": {},
            "orderbook": {"bids": [], "asks": []},
            "recent_trades": [],
        }

    def cli_news_payload(kind: str) -> dict:
        return {
            "kind": kind,
            "language": "en-US",
            "items": [
                {
                    "id": f"{kind}-1",
                    "title": f"{kind} cli article",
                    "summary": "Official CLI source.",
                    "excerpt": "Official CLI source.",
                    "content": "Official CLI source.",
                    "platforms": ["blockbeats"],
                    "coins": ["BTC"],
                    "importance": "high",
                    "sentiment": "bullish",
                    "published_at": 1776600000000,
                    "source": "okx_cli_news",
                }
            ],
            "count": 1,
            "backend": "okx_cli",
        }

    async def coin_news(*args, **kwargs):
        return cli_news_payload("coin")

    async def latest_news(*args, **kwargs):
        return cli_news_payload("latest")

    async def coin_sentiment(*args, **kwargs):
        return {
            "period": "1h",
            "items": [
                {
                    "symbol": "BTC",
                    "label": "bullish",
                    "bullish_ratio": 0.67,
                    "bearish_ratio": 0.12,
                    "mention_count": 9,
                    "trend": [],
                }
            ],
            "count": 1,
            "backend": "okx_cli",
        }

    async def sentiment_ranking(*args, **kwargs):
        return {
            "period": "1h",
            "sort_by": "hot",
            "items": [
                {
                    "symbol": "BTC",
                    "label": "bullish",
                    "bullish_ratio": 0.67,
                    "bearish_ratio": 0.12,
                    "mention_count": 9,
                    "trend": [],
                }
            ],
            "count": 1,
            "backend": "okx_cli",
        }

    monkeypatch.setattr("app.analysis.router.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_news_by_coin", coin_news)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_latest_news", latest_news)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_coin_sentiment", coin_sentiment)
    monkeypatch.setattr("app.analysis.router.okx_orbit.get_sentiment_ranking", sentiment_ranking)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/analysis/okx/overview", params={"inst_id": "BTC-USDT-SWAP", "language": "en-US"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["source_meta"]["news_data"] == "okx_cli_private"
    assert data["source_meta"]["uses_news_fallback"] is False
    assert "okx_cli" in data["source_meta"]["news_backends"]


@pytest.mark.anyio
async def test_okx_oi_history_uses_legacy_fallback(monkeypatch):
    async def fail_public_post(*args, **kwargs):
        raise RuntimeError("connection reset")

    async def fake_open_interest_history(symbol="BTC", period="1H", limit=48):
        return [
            {"timestamp": 1776603600, "open_interest_usd": 1100.0, "volume_usd": 5000.0},
            {"timestamp": 1776600000, "open_interest_usd": 1000.0, "volume_usd": 4800.0},
        ]

    monkeypatch.setattr("app.market.sources.okx._public_post", fail_public_post)
    monkeypatch.setattr("app.market.sources.okx.get_open_interest_history", fake_open_interest_history)

    payload = await okx.get_oi_history("DOGE-USDT-SWAP", bar="1H", limit=2)

    assert len(payload) == 2
    assert payload[0]["oiUsd"] == 1100.0
    assert payload[1]["oiUsd"] == 1000.0
    assert payload[0]["oiDeltaUsd"] == pytest.approx(100.0)
    assert payload[0]["oiDeltaPct"] == pytest.approx(10.0)


@pytest.mark.anyio
async def test_market_intel_synthesizes_sentiment_when_all_samples_missing(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {
                "last": 0.25,
                "price_change_pct_24h": 1.2,
                "oi_delta_pct": 0.0,
                "oi_usd": None,
                "funding_rate": None,
            },
            "diagnosis": {
                "price_oi_regime": "neutral",
                "price_oi_comment": "价格与持仓尚未形成明确的单边结构。",
                "orderbook_bias": None,
                "funding_bias": None,
            },
            "indicator_summary": {},
        }

    async def empty_page(**kwargs):
        return {"items": [], "count": 0}

    async def empty_platforms(**kwargs):
        return {"items": [], "count": 0}

    async def empty_internal_fallback(**kwargs):
        return {
            "important_news": [],
            "coin_news": [],
            "keyword_articles": [],
            "recent_coin_news": [],
            "previous_coin_news": [],
            "sentiment_item": None,
            "ranking_items": [],
            "platforms": [],
        }

    async def empty_focus_pairs(*args, **kwargs):
        return []

    monkeypatch.setattr("app.analysis.okx_market_intel.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_by_coin", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_latest_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_coin_sentiment", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_sentiment_ranking", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.search_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_platforms", empty_platforms)
    monkeypatch.setattr("app.analysis.okx_market_intel._load_internal_news_fallback", empty_internal_fallback)
    monkeypatch.setattr("app.analysis.okx_market_intel._build_focus_pairs", empty_focus_pairs)

    payload = await build_market_intel_master(
        symbol="DOGE-USDT-SWAP",
        market_type="SWAP",
        timeframe="1H",
        language="zh-CN",
        news_limit=6,
        important_limit=4,
        ranking_limit=8,
    )

    assert payload["coin_sentiment"]["count"] == 1
    assert payload["coin_sentiment"]["items"][0]["symbol"] == "DOGE"
    assert payload["sentiment_ranking"]["count"] == 1
    assert payload["sentiment_ranking"]["items"][0]["symbol"] == "DOGE"


@pytest.mark.anyio
async def test_market_intel_reuses_sentiment_snapshot_when_ranking_missing(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {
                "last": 75521.3,
                "price_change_pct_24h": -0.9,
                "oi_delta_pct": 0.0,
                "oi_usd": None,
                "funding_rate": None,
            },
            "diagnosis": {
                "price_oi_regime": "neutral",
                "price_oi_comment": "结构中性。",
                "orderbook_bias": None,
                "funding_bias": None,
            },
            "indicator_summary": {},
        }

    async def empty_page(**kwargs):
        return {"items": [], "count": 0}

    async def empty_platforms(**kwargs):
        return {"items": [], "count": 0}

    async def internal_fallback(**kwargs):
        sentiment_item = {
            "symbol": "BTC",
            "label": "bullish",
            "bullish_ratio": 0.3333333333333333,
            "bearish_ratio": 0.0,
            "mention_count": 6,
            "trend": [],
        }
        return {
            "important_news": [],
            "coin_news": [],
            "keyword_articles": [],
            "recent_coin_news": [],
            "previous_coin_news": [],
            "sentiment_item": sentiment_item,
            "ranking_items": [],
            "platforms": [],
        }

    async def empty_focus_pairs(*args, **kwargs):
        return []

    monkeypatch.setattr("app.analysis.okx_market_intel.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_by_coin", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_latest_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_coin_sentiment", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_sentiment_ranking", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.search_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_platforms", empty_platforms)
    monkeypatch.setattr("app.analysis.okx_market_intel._load_internal_news_fallback", internal_fallback)
    monkeypatch.setattr("app.analysis.okx_market_intel._build_focus_pairs", empty_focus_pairs)

    payload = await build_market_intel_master(
        symbol="BTC-USDT-SWAP",
        market_type="SWAP",
        timeframe="1H",
        language="zh-CN",
        news_limit=6,
        important_limit=4,
        ranking_limit=8,
    )

    snapshot = payload["coin_sentiment"]["items"][0]
    ranking = payload["sentiment_ranking"]["items"][0]
    assert ranking["symbol"] == snapshot["symbol"]
    assert ranking["label"] == snapshot["label"]
    assert ranking["bullish_ratio"] == snapshot["bullish_ratio"]
    assert ranking["bearish_ratio"] == snapshot["bearish_ratio"]
    assert ranking["mention_count"] == snapshot["mention_count"]


@pytest.mark.anyio
async def test_market_intel_builds_trend_from_fallback_news_when_missing(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {
                "last": 75521.3,
                "price_change_pct_24h": -0.9,
                "oi_delta_pct": 0.0,
                "oi_usd": None,
                "funding_rate": None,
            },
            "diagnosis": {
                "price_oi_regime": "neutral",
                "price_oi_comment": "结构中性。",
                "orderbook_bias": None,
                "funding_bias": None,
            },
            "indicator_summary": {},
        }

    async def empty_page(**kwargs):
        return {"items": [], "count": 0}

    async def empty_platforms(**kwargs):
        return {"items": [], "count": 0}

    async def internal_fallback(**kwargs):
        sentiment_item = {
            "symbol": "BTC",
            "label": "bullish",
            "bullish_ratio": 0.5,
            "bearish_ratio": 0.0,
            "mention_count": 4,
            "trend": [],
        }
        recent_coin_news = [
            {"title": "btc one", "sentiment": "bullish", "published_at": 1776603600000},
            {"title": "btc two", "sentiment": "neutral", "published_at": 1776600000000},
            {"title": "btc three", "sentiment": "bullish", "published_at": 1776596400000},
            {"title": "btc four", "sentiment": "bearish", "published_at": 1776592800000},
        ]
        return {
            "important_news": [],
            "coin_news": recent_coin_news,
            "keyword_articles": [],
            "recent_coin_news": recent_coin_news,
            "previous_coin_news": [],
            "sentiment_item": sentiment_item,
            "ranking_items": [],
            "platforms": [],
        }

    async def empty_focus_pairs(*args, **kwargs):
        return []

    monkeypatch.setattr("app.analysis.okx_market_intel.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_by_coin", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_latest_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_coin_sentiment", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_sentiment_ranking", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.search_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_platforms", empty_platforms)
    monkeypatch.setattr("app.analysis.okx_market_intel._load_internal_news_fallback", internal_fallback)
    monkeypatch.setattr("app.analysis.okx_market_intel._build_focus_pairs", empty_focus_pairs)

    payload = await build_market_intel_master(
        symbol="BTC-USDT-SWAP",
        market_type="SWAP",
        timeframe="1H",
        language="zh-CN",
        news_limit=6,
        important_limit=4,
        ranking_limit=8,
    )

    trend = payload["coin_sentiment"]["items"][0]["trend"]
    assert len(trend) == 4
    assert trend[0]["mention_count"] == 1
    assert trend[0]["bullish_ratio"] == 1.0


@pytest.mark.anyio
async def test_okx_market_intelligence_spot_skips_mark_price(monkeypatch):
    async def fake_ticker(inst_id):
        assert inst_id == "BTC-USDT"
        return {
            "instId": inst_id,
            "last": "100.0",
            "open24h": "95.0",
            "high24h": "101.0",
            "low24h": "90.0",
            "vol24h": "12.5",
            "volCcy24h": "1250.0",
        }

    async def fake_orderbook(inst_id, sz=20):
        return {
            "best_bid": 99.9,
            "best_ask": 100.1,
            "spread": 0.2,
            "bid_depth_notional_top5": 8000.0,
            "ask_depth_notional_top5": 7000.0,
            "imbalance_top5": 0.09,
            "bids": [{"price": 99.9, "size": 3}],
            "asks": [{"price": 100.1, "size": 2}],
        }

    async def fake_candles(inst_id, bar="4H", limit=120):
        return [{"close": 98.0}, {"close": 100.0}]

    async def fake_trades(inst_id, limit=20):
        return [{"tradeId": "1", "px": "100", "sz": "1", "side": "buy", "ts": "1776790000000"}]

    async def fake_instruments(inst_type, inst_id=None):
        return {"instType": inst_type, "instId": inst_id}

    async def unexpected_call(*args, **kwargs):
        raise AssertionError("derivatives-only endpoint should not be called for spot")

    async def fake_indicator(*args, **kwargs):
        return None

    monkeypatch.setattr("app.market.sources.okx.get_ticker", fake_ticker)
    monkeypatch.setattr("app.market.sources.okx.get_orderbook", fake_orderbook)
    monkeypatch.setattr("app.market.sources.okx.get_candles", fake_candles)
    monkeypatch.setattr("app.market.sources.okx.get_trades", fake_trades)
    monkeypatch.setattr("app.market.sources.okx.get_instruments", fake_instruments)
    monkeypatch.setattr("app.market.sources.okx.get_funding_rate", unexpected_call)
    monkeypatch.setattr("app.market.sources.okx.get_mark_price", unexpected_call)
    monkeypatch.setattr("app.market.sources.okx.get_public_open_interest", unexpected_call)
    monkeypatch.setattr("app.market.sources.okx.get_price_limit", unexpected_call)
    monkeypatch.setattr("app.market.sources.okx.get_oi_history", unexpected_call)
    monkeypatch.setattr("app.market.sources.okx.get_indicator", fake_indicator)

    payload = await okx.build_market_intelligence("BTC-USDT", candle_bar="4H", oi_bar="4H")

    assert payload["instType"] == "SPOT"
    assert payload["snapshot"]["last"] == 100.0
    assert payload["snapshot"]["mark_price"] is None
    assert payload["diagnosis"]["orderbook_bias"] == "bid_support"


@pytest.mark.anyio
async def test_market_intel_builds_snapshot_trend_when_no_news_samples(monkeypatch):
    async def fake_market_intelligence(*args, **kwargs):
        return {
            "snapshot": {
                "last": 2500.0,
                "price_change_pct_24h": 1.0,
                "oi_delta_pct": None,
                "oi_usd": None,
                "funding_rate": None,
            },
            "diagnosis": {
                "price_oi_regime": "neutral",
                "price_oi_comment": "结构中性。",
                "orderbook_bias": None,
                "funding_bias": None,
            },
            "indicator_summary": {},
        }

    async def empty_page(**kwargs):
        return {"items": [], "count": 0}

    async def empty_platforms(**kwargs):
        return {"items": [], "count": 0}

    async def internal_fallback(**kwargs):
        return {
            "important_news": [],
            "coin_news": [],
            "keyword_articles": [],
            "recent_coin_news": [],
            "previous_coin_news": [],
            "sentiment_item": {
                "symbol": "ETH",
                "label": "bearish",
                "bullish_ratio": 0.0,
                "bearish_ratio": 0.167,
                "mention_count": 6,
                "trend": [],
            },
            "ranking_items": [],
            "platforms": [],
        }

    async def empty_focus_pairs(*args, **kwargs):
        return []

    monkeypatch.setattr("app.analysis.okx_market_intel.okx.build_market_intelligence", fake_market_intelligence)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_by_coin", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_latest_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_coin_sentiment", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_sentiment_ranking", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.search_news", empty_page)
    monkeypatch.setattr("app.analysis.okx_market_intel.okx_orbit.get_news_platforms", empty_platforms)
    monkeypatch.setattr("app.analysis.okx_market_intel._load_internal_news_fallback", internal_fallback)
    monkeypatch.setattr("app.analysis.okx_market_intel._build_focus_pairs", empty_focus_pairs)

    payload = await build_market_intel_master(
        symbol="ETH-USDT-SWAP",
        market_type="SWAP",
        timeframe="4H",
        language="zh-CN",
        news_limit=6,
        important_limit=4,
        ranking_limit=8,
    )

    trend = payload["coin_sentiment"]["items"][0]["trend"]
    assert len(trend) == 6
    assert all(point["bullish_ratio"] == 0.0 for point in trend)
    assert all(point["mention_count"] == 6 for point in trend)


def test_prioritize_important_news_prefers_symbol_relevance():
    items = [
        {
            "id": "macro-1",
            "title": "地缘政治 | 美联储主席提名人 Kevin Warsh 听证会遭质询",
            "summary": "宏观新闻，但与 ETH 无关。",
            "excerpt": "",
            "content": "",
            "coins": [],
            "importance": "important",
            "published_at": 1776798300000,
        },
        {
            "id": "eth-1",
            "title": "以太坊财库公司 SharpLink 获得 470 枚 ETH 质押奖励",
            "summary": "ETH treasury update",
            "excerpt": "",
            "content": "",
            "coins": ["ETH"],
            "importance": "important",
            "published_at": 1776798200000,
        },
        {
            "id": "eth-2",
            "title": "ETH 跌破 2,300 USDT，24 小时跌幅 0.57%",
            "summary": "ETH market move",
            "excerpt": "",
            "content": "",
            "coins": ["ETH"],
            "importance": "important",
            "published_at": 1776798100000,
        },
    ]

    ordered = _prioritize_important_news(
        items,
        symbol_terms=["eth", "ethereum", "以太坊"],
        keyword_terms=["eth", "ethereum", "以太坊"],
        limit=3,
    )

    assert [item["id"] for item in ordered[:2]] == ["eth-1", "eth-2"]


def test_okx_normalizers_drop_zero_sized_levels_and_trades():
    orderbook = _normalize_orderbook(
        {
            "ts": "1776814743919",
            "bids": [["75843.2", "489.39"], ["75843.1", "0"], ["75843.0", "0.004"]],
            "asks": [["75843.3", "0"], ["75843.4", "0.95"], ["75843.5", "0.0008"]],
        },
        "BTC-USDT-SWAP",
        5,
    )
    trades = _normalize_trade_rows(
        [
            {"tradeId": "1", "px": "75843.2", "sz": "0", "side": "sell", "ts": "1776814743919"},
            {"tradeId": "2", "px": "75843.3", "sz": "0.004", "side": "buy", "ts": "1776814743886"},
            {"tradeId": "3", "px": "75843.4", "sz": "0.95", "side": "buy", "ts": "1776814743560"},
        ],
        5,
    )

    assert [level["size"] for level in orderbook["bids"]] == [489.39, 0.004]
    assert [level["size"] for level in orderbook["asks"]] == [0.95, 0.0008]
    assert [trade["tradeId"] for trade in trades] == ["2", "3"]
    assert trades[0]["sz"] == pytest.approx(0.004)


@pytest.mark.anyio
async def test_localize_article_for_language_adds_zh_fields(monkeypatch):
    async def fake_ai_chat(*args, **kwargs):
        return (
            '{"title":"比特币 ETF 再现资金流入",'
            '"summary":"美国现货比特币 ETF 再次录得净流入。",'
            '"content":"美国现货比特币 ETF 出现新增资金流入。\\n\\n市场将此视为机构需求回暖的信号。"}'
        )

    monkeypatch.setattr(news_translation.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(news_translation, "ai_chat", fake_ai_chat)

    localized = await news_translation.localize_article_for_language(
        {
            "id": "detail-1",
            "title": "Bitcoin ETF sees fresh inflows",
            "summary": "US spot ETFs posted another day of net inflows.",
            "content": "US spot Bitcoin ETFs posted another day of net inflows as institutional demand improved.",
        },
        language="zh-CN",
    )

    assert localized["translated_title"] == "比特币 ETF 再现资金流入"
    assert localized["translated_summary"] == "美国现货比特币 ETF 再次录得净流入。"
    assert "机构需求回暖" in localized["translated_content"]
    assert localized["translation_mode"] == "zh_key_points"


@pytest.mark.anyio
async def test_localize_article_for_language_uses_okx_public_feed_translation(monkeypatch):
    async def fake_fetch_bytes(*args, **kwargs):
        html = """
        <script data-id="__app_data_for_ssr__" id="appState" type="application/json">
        {
          "appContext": {
            "initialProps": {
              "contentDetail": {
                "title": "特朗普称伊朗财政正在崩溃",
                "summary": "特朗普称伊朗急需资金。",
                "contentList": [
                  {"translatedContent": "特朗普表示伊朗每天损失 5 亿美元。"},
                  {"translatedContent": "他称军警都在抱怨拿不到工资。"}
                ]
              }
            }
          }
        }
        </script>
        """
        return html.encode("utf-8"), {}

    monkeypatch.setattr(news_translation, "fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr(news_translation.settings, "openai_api_key", "")

    localized = await news_translation.localize_article_for_language(
        {
            "id": "74508611016992",
            "title": "Trump: Iran's finances are collapsing",
            "summary": "Main takeaway: Trump says Iran's finances are collapsing.",
            "content": "",
            "source_url": "https://www.okx.com/zh-hans/feed/post/74508611016992",
        },
        language="zh-CN",
    )

    assert localized["translated_title"] == "特朗普称伊朗财政正在崩溃"
    assert localized["translated_summary"] == "特朗普称伊朗急需资金。"
    assert "每天损失 5 亿美元" in localized["translated_content"]
    assert localized["translation_mode"] == "okx_public_feed"


@pytest.mark.anyio
async def test_okx_news_detail_returns_translated_fields_for_zh(monkeypatch):
    async def fake_get_news_detail(*args, **kwargs):
        return {
            "item": {
                "id": "detail-2",
                "title": "Ethereum treasury firm adds more ETH",
                "summary": "SharpLink expanded its ETH reserves.",
                "content": "SharpLink added more ETH to its treasury and reiterated its long-term staking plan.",
                "platforms": ["blockbeats"],
                "coins": ["ETH"],
                "importance": "high",
                "sentiment": "bullish",
                "published_at": 1776804859000,
            },
            "backend": "okx_cli",
        }

    async def fake_localize_article(item, *, language):
        return {
            **item,
            "translated_title": "以太坊财库公司继续增持 ETH",
            "translated_summary": "SharpLink 扩大 ETH 储备。",
            "translated_content": "SharpLink 再次增持 ETH，并重申长期质押计划。",
            "translation_mode": "zh_key_points",
        }

    monkeypatch.setattr("app.news.router.okx_orbit.get_news_detail", fake_get_news_detail)
    monkeypatch.setattr("app.news.router.localize_article_for_language", fake_localize_article)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/news/okx/detail/detail-2", params={"language": "zh-CN"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["item"]["translated_title"] == "以太坊财库公司继续增持 ETH"
    assert data["item"]["translated_content"] == "SharpLink 再次增持 ETH，并重申长期质押计划。"
