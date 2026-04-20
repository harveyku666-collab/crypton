from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.square.service import build_hot_token_board, extract_token_mentions, filter_items_to_window
from app.square.sources.binance import get_square_content as get_binance_square_content
from app.square.sources.okx import get_square_content as get_okx_square_content


def _sample_square_payload():
    return {
        "items": [
            {
                "external_id": "binance_post_1",
                "platform": "binance",
                "channel": "square",
                "item_type": "post",
                "title": "BTC momentum is back",
                "content": "Watching $BTC and $ETH closely.",
                "excerpt": "Watching $BTC and $ETH closely.",
                "author_name": "Alice",
                "author_handle": "alice",
                "language": "en",
                "published_at": 1710000000000,
                "url": "https://www.binance.com/en/square/post/1",
                "engagement": {"likes": 12},
                "symbols": ["BTC", "ETH"],
                "tags": [],
                "metadata": {"source_mode": "html-json"},
            },
            {
                "external_id": "okx_article_1",
                "platform": "okx",
                "channel": "square",
                "item_type": "article",
                "title": "ETF flows stay positive",
                "content": "BTC ETF inflows remain constructive.",
                "excerpt": "BTC ETF inflows remain constructive.",
                "author_name": None,
                "author_handle": None,
                "language": "en-US",
                "published_at": 1710000001000,
                "url": "https://www.okx.com/learn/btc-etf",
                "engagement": {},
                "symbols": ["BTC"],
                "tags": ["research"],
                "metadata": {"orbit_source": "okx_orbit"},
            },
        ],
        "count": 2,
        "platforms": ["binance", "okx"],
        "source_modes": {"binance": "html", "okx": "orbit"},
        "errors": [],
    }


@pytest.mark.anyio
async def test_square_live_endpoint(monkeypatch):
    async def fake_fetch_square_feed(*, platforms=None, limit=20, language="en"):
        return _sample_square_payload()

    monkeypatch.setattr("app.square.router.fetch_square_feed", fake_fetch_square_feed)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/square/live", params={"platforms": "binance,okx", "language": "en", "limit": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["source_modes"]["binance"] == "html"
    assert data["source_modes"]["okx"] == "orbit"
    assert data["items"][0]["external_id"] == "binance_post_1"
    assert data["items"][1]["language"] == "en-US"


@pytest.mark.anyio
async def test_square_history_fallback_to_live(monkeypatch):
    async def fake_fetch_square_feed(*, platforms=None, limit=20, language="en"):
        return _sample_square_payload()

    monkeypatch.setattr("app.square.service.fetch_square_feed", fake_fetch_square_feed)
    monkeypatch.setattr("app.square.service.db_available", lambda: False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/square/history",
            params={"platform": "binance", "item_type": "post", "language": "en", "page_size": 10},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["db_available"] is False
    assert data["source_mode"] == "live"
    assert len(data["items"]) == 1
    assert data["items"][0]["platform"] == "binance"
    assert data["items"][0]["item_type"] == "post"


@pytest.mark.anyio
async def test_generate_hot_coin_snapshot_endpoint(monkeypatch):
    async def fake_generate_hot_coin_snapshot(*, platforms=None, hours=24, kol_only=False, limit=20, snapshot_date=None):
        return {
            "snapshot_key": "2026-04-20:binance,okx:24h:all",
            "snapshot_date": "2026-04-20",
            "window_hours": hours,
            "platforms": platforms or ["binance", "okx"],
            "kol_only": kol_only,
            "items": [{"rank": 1, "token": "BTC"}],
            "count": 1,
            "replaced": 0,
        }

    monkeypatch.setattr("app.square.router.generate_hot_coin_snapshot", fake_generate_hot_coin_snapshot)
    monkeypatch.setattr("app.square.router.db_available", lambda: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/square/hot-coins/snapshots/generate", params={"platforms": "binance,okx", "hours": 24})

    assert resp.status_code == 200
    data = resp.json()
    assert data["snapshot_key"] == "2026-04-20:binance,okx:24h:all"
    assert data["count"] == 1
    assert data["items"][0]["token"] == "BTC"


@pytest.mark.anyio
async def test_run_square_collect_endpoint(monkeypatch):
    async def fake_collect_square_items(*, platforms=None, page_size=None, backfill_pages=None, language=None):
        return {
            "platforms": platforms or ["binance", "okx"],
            "created": 12,
            "skipped": 5,
            "fetched": 34,
            "pages": 4,
            "results": [{"platform": "binance", "created": 8}, {"platform": "okx", "created": 4}],
        }

    monkeypatch.setattr("app.square.router.collect_square_items", fake_collect_square_items)
    monkeypatch.setattr("app.square.router.db_available", lambda: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/square/collect/run",
            params={"platforms": "binance,okx", "page_size": 20, "backfill_pages": 2, "language": "en"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 12
    assert data["pages"] == 4
    assert data["results"][0]["platform"] == "binance"


@pytest.mark.anyio
async def test_square_collect_status_endpoint(monkeypatch):
    async def fake_list_square_collection_states(*, platforms=None, language=None):
        return [
            {
                "platform": "binance",
                "language": "en",
                "current_cursor": "8",
                "last_status": "ok",
                "last_created_count": 10,
            }
        ]

    monkeypatch.setattr("app.square.router.list_square_collection_states", fake_list_square_collection_states)
    monkeypatch.setattr("app.square.router.db_available", lambda: True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/square/collect/status", params={"platforms": "binance", "language": "en"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["platform"] == "binance"
    assert data["items"][0]["current_cursor"] == "8"


def test_hot_token_board_dedupes_same_author_within_window():
    board = build_hot_token_board(
        [
            {
                "platform": "binance",
                "external_id": "1",
                "author_key": "binance:handle:alice",
                "author_name": "Alice",
                "content": "Still bullish on $BTC and $ETH",
                "symbols": ["BTC", "ETH"],
                "is_kol": 1,
            },
            {
                "platform": "binance",
                "external_id": "2",
                "author_key": "binance:handle:alice",
                "author_name": "Alice",
                "content": "Again, $BTC looks strong",
                "symbols": ["BTC"],
                "is_kol": 1,
            },
            {
                "platform": "okx",
                "external_id": "3",
                "author_key": "okx:handle:bob",
                "author_name": "Bob",
                "content": "$BTC breakout soon",
                "symbols": ["BTC"],
                "is_kol": 0,
            },
        ],
        limit=10,
    )

    btc = next(item for item in board if item["token"] == "BTC")
    assert btc["unique_author_mentions"] == 2
    assert btc["unique_kol_mentions"] == 1
    assert btc["item_count"] == 3


def test_hot_token_board_prefers_tradable_symbols_when_provided():
    board = build_hot_token_board(
        [
            {
                "platform": "binance",
                "external_id": "1",
                "author_key": "binance:handle:alice",
                "author_name": "Alice",
                "content": "Watching $BTC and $ALTCOINRECOVERY",
                "symbols": ["BTC", "ALTCOINRECOVERY"],
                "is_kol": 0,
            }
        ],
        limit=10,
        tradable_symbols={"BTC", "ETH"},
    )

    assert [item["token"] for item in board] == ["BTC"]


def test_filter_items_to_window_prefers_published_at():
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    old_ms = int((datetime.now(timezone.utc) - timedelta(hours=30)).timestamp() * 1000)

    filtered = filter_items_to_window(
        [
            {"external_id": "fresh", "published_at": now_ms},
            {"external_id": "old", "published_at": old_ms},
        ],
        hours=24,
    )

    assert [item["external_id"] for item in filtered] == ["fresh"]


def test_extract_token_mentions_filters_noise_and_normalizes_aliases():
    tokens = extract_token_mentions(
        {
            "title": "Markets are nervous",
            "content": "#Bitcoin still looks strong but #DYOR and #markets are not tokens. Watching $BTC and $ETH.",
            "symbols": ["BTC", "DYOR", "CRYPTO", "ETHEREUM"],
        }
    )

    assert tokens == ["BTC", "ETH"]


@pytest.mark.anyio
async def test_okx_square_source_warns_when_orbit_is_app_only(monkeypatch):
    async def fake_get_latest_news(*, language="en-US", detail_lvl="summary", limit=20, after=None):
        return {
            "items": [],
            "count": 0,
            "next_cursor": None,
            "warning": "OKX Orbit is currently app-only; the public web Orbit API is unavailable",
            "code": "50026",
        }

    monkeypatch.setattr("app.square.sources.okx.okx_orbit.get_latest_news", fake_get_latest_news)
    monkeypatch.setattr("app.square.sources.okx.settings.okx_public_feed_urls", "")

    payload = await get_okx_square_content(language="en", limit=4)

    assert payload["count"] == 0
    assert payload["source_mode"] == "app-only"
    assert "app-only" in payload["warning"]


@pytest.mark.anyio
async def test_okx_square_source_falls_back_to_public_feed_page(monkeypatch):
    async def fake_get_latest_news(*, language="en-US", detail_lvl="summary", limit=20, after=None):
        return {
            "items": [],
            "count": 0,
            "next_cursor": None,
            "warning": "OKX Orbit is currently app-only; the public web Orbit API is unavailable",
            "code": "50026",
        }

    sample_html = """
    <html><body>
    <script data-id="__app_data_for_ssr__" type="application/json" id="appState">{
      "appContext": {
        "initialProps": {
          "contentDetail": {
            "author": {
              "authorId": "788088982939893765",
              "nickName": "OKX",
              "officialStatus": "1",
              "type": 2
            },
            "contentList": [
              {
                "content": "BTC and ETH setup still looks constructive.",
                "contentId": "48481661650019",
                "publishTime": "1740938158000",
                "tagList": {"hashTagList": [{"tagName": "Bitcoin"}]}
              }
            ],
            "source": {
              "platform": "twitter",
              "url": "https://x.com/okx/status/1896258192868560995"
            },
            "tokens": [
              {"coinName": "BTC", "instId": "BTC-USDT"},
              {"coinName": "ETH", "instId": "ETH-USDT"}
            ],
            "summary": "BTC and ETH setup still looks constructive.",
            "title": "BTC, ETH setup",
            "formatType": 2,
            "category": 3,
            "commentNum": 12
          }
        }
      }
    }</script>
    </body></html>
    """

    async def fake_fetch_bytes(url, *, params=None, headers=None, retries=3):
        return sample_html.encode("utf-8"), "text/html"

    monkeypatch.setattr("app.square.sources.okx.okx_orbit.get_latest_news", fake_get_latest_news)
    monkeypatch.setattr("app.square.sources.okx.fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr(
        "app.square.sources.okx.settings.okx_public_feed_urls",
        "https://www.okx.com/en-us/feed/post/48481661650019",
    )

    payload = await get_okx_square_content(language="en", limit=5)

    assert payload["count"] == 1
    assert payload["source_mode"] == "public_feed_pages"
    assert "fallback" in payload["warning"]
    assert payload["items"][0]["author_name"] == "OKX"
    assert payload["items"][0]["symbols"] == ["BTC", "ETH"]
    assert payload["items"][0]["is_kol"] == 1


@pytest.mark.anyio
async def test_binance_square_source_normalizes_official_feed(monkeypatch):
    detail_urls: list[str] = []

    async def fake_fetch_json_post(url, *, params=None, json_body=None, headers=None, retries=3):
        assert url.endswith("/bapi/composite/v9/friendly/pgc/feed/feed-recommend/list")
        assert params is None
        assert json_body == {
            "pageIndex": 3,
            "pageSize": 2,
            "scene": "web-homepage",
            "contentIds": [],
        }
        assert headers["Clienttype"] == "web"
        assert headers["Referer"].endswith("/zh-CN/square")
        return {
            "code": "000000",
            "message": None,
            "data": {
                "vos": [
                    {
                        "id": "312815870976001",
                        "cardType": "BUZZ_SHORT",
                        "contentType": 1,
                        "authorName": "CZ",
                        "username": "CZ",
                        "squareAuthorId": "dxCeCLOM7uOFJKX8EnS3Kw",
                        "date": 1776262262,
                        "content": "Thanks everyone for donating and participating!",
                        "translatedData": {"content": "感谢大家的捐款和参与！"},
                        "webLink": "https://www.binance.com/zh-CN/square/post/312815870976001",
                        "tradingPairsV2": [{"code": "BNB", "symbol": "BNBUSDT", "bridge": "USDT"}],
                        "hashtagList": ["#BinanceSquare "],
                        "authorVerificationType": 1,
                        "authorRole": 0,
                        "sourceType": 0,
                        "likeCount": 4859,
                        "commentCount": 1650,
                        "shareCount": 82,
                        "quoteCount": 421,
                        "viewCount": 7042295,
                    },
                    {
                        "id": "313851426066274",
                        "cardType": "BUZZ_LONG",
                        "contentType": 2,
                        "title": "BTC/USD Facing Bearish Rejection",
                        "subTitle": "Short-term correction ahead.",
                        "content": "After the sharp rally from support, BTC hit resistance.",
                        "authorName": "GK-ARONNO",
                        "username": "GK_ARONNO",
                        "squareAuthorId": "KckGPXHX_ScKrztSW5qZxQ",
                        "date": 1776515096,
                        "webLink": "https://www.binance.com/en/square/post/313851426066274",
                        "tradingPairs": [{"code": "BTC", "symbol": "BTCUSDT", "bridge": "USDT"}],
                        "authorVerificationType": 1,
                        "authorRole": 0,
                        "sourceType": 0,
                        "likeCount": 999,
                        "commentCount": 88,
                        "shareCount": 12,
                        "quoteCount": 3,
                        "viewCount": 456789,
                    },
                ]
            },
            "success": True,
        }

    async def fake_fetch_json(url, *, params=None, headers=None, retries=3):
        detail_urls.append(url)
        assert params is None
        assert headers["Clienttype"] == "web"
        assert headers["Referer"].endswith("/en/square/post/313851426066274")
        return {
            "code": "000000",
            "message": None,
            "data": {
                "id": 313851426066274,
                "contentType": 2,
                "title": "BTC/USD Facing Bearish Rejection",
                "bodyTextOnly": "Full article body from detail endpoint with more BTC context.",
                "authorVerificationType": 1,
                "roleCode": 11,
                "displayName": "GK-ARONNO",
                "username": "GK-ARONNO",
                "squareUid": "KckGPXHX_ScKrztSW5qZxQ",
                "firstReleaseTime": 1776515096000,
                "webLink": "https://www.binance.com/en/square/post/313851426066274",
                "tradingPairs": [{"code": "BTC", "symbol": "BTCUSDT", "bridge": "USDT"}],
                "bookmarkCount": 17,
                "tippingCount": 1,
                "tippingTotalAmount": 5,
                "userTag": {"name": "Open Trade"},
                "userLabels": [{"name": "1.9M 粉丝"}],
                "likeCount": 193,
                "commentCount": 29,
                "shareCount": 5,
                "quoteCount": 11,
                "viewCount": 245698,
            },
            "success": True,
        }

    monkeypatch.setattr("app.square.sources.binance.fetch_json_post", fake_fetch_json_post)
    monkeypatch.setattr("app.square.sources.binance.fetch_json", fake_fetch_json)
    monkeypatch.setattr("app.square.sources.binance.settings.binance_square_feed_url", "")

    payload = await get_binance_square_content(language="zh-CN", limit=2, cursor="3")

    assert payload["count"] == 2
    assert payload["next_cursor"] == "4"
    assert detail_urls == ["https://www.binance.com/bapi/composite/v2/friendly/pgc/special/content/detail/313851426066274"]
    first = next(item for item in payload["items"] if item["external_id"] == "binance_312815870976001")
    second = next(item for item in payload["items"] if item["external_id"] == "binance_313851426066274")

    assert first["external_id"] == "binance_312815870976001"
    assert first["author_handle"] == "CZ"
    assert first["content"] == "感谢大家的捐款和参与！"
    assert first["symbols"] == ["BNB"]
    assert first["tags"] == ["BinanceSquare"]
    assert first["published_at"] == 1776262262000
    assert first["is_kol"] == 1
    assert first["matched_kol_name"] == "CZ"
    assert first["matched_kol_tier"] == "platform_native"
    assert first["metadata"]["author_verification_type"] == 1

    assert second["item_type"] == "article"
    assert second["is_kol"] == 1
    assert second["matched_kol_name"] == "GK-ARONNO"
    assert second["title"] == "BTC/USD Facing Bearish Rejection"
    assert second["content"] == "Full article body from detail endpoint with more BTC context."
    assert second["metadata"]["detail_fetched"] is True
    assert second["metadata"]["detail_role_code"] == 11
    assert second["metadata"]["detail_user_tag"] == "Open Trade"
    assert second["symbols"] == ["BTC"]
