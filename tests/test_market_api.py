import pytest
from httpx import ASGITransport, AsyncClient

from app.common.models import WhaleAlert, WhaleTransferEvent
from app.market.aggregator import get_symbol_price
from app.main import app
from app.market.sources.binance_rank import build_unified_filters_from_strings
from app.onchain.monitor_service import (
    _estimate_market_amount_usd,
    _estimate_market_snapshot,
    _merge_transfer_event_into_alert,
)


@pytest.mark.anyio
async def test_get_symbol_price_falls_back_to_coingecko(monkeypatch):
    async def fake_surf_price(symbol):
        return None

    async def fake_binance_ticker(symbol):
        return {"code": -1121, "msg": "Invalid symbol."}

    async def fake_desk3_prices(symbols):
        return []

    async def fake_gecko_price(symbol):
        return {
            "symbol": symbol,
            "price": 0.12,
            "change_pct": 3.5,
            "source": "coingecko",
        }

    monkeypatch.setattr("app.market.aggregator.surf.get_price", fake_surf_price)
    monkeypatch.setattr("app.market.aggregator.binance.get_ticker_24h", fake_binance_ticker)
    monkeypatch.setattr("app.market.aggregator.desk3.get_prices", fake_desk3_prices)
    monkeypatch.setattr("app.market.aggregator.coingecko.get_price_by_symbol", fake_gecko_price)

    payload = await get_symbol_price("KPER")

    assert payload is not None
    assert payload["price"] == 0.12
    assert payload["source"] == "coingecko"


def test_build_unified_filters_supports_binance_skill_ranges():
    filters = build_unified_filters_from_strings(
        keywords="DOGE,PEPE",
        excludes="BTC,ETH",
        socials="1,2",
        alpha_tag_filter="AI,MEME",
        audit_filter="0,1",
        tag_filter="23,29",
        holders_top10_percent_min=10.5,
        holders_top10_percent_max=75.0,
        kyc_holders_min=100,
        kyc_holders_max=2500,
        count_min=50,
        count_max=5000,
        launch_time_min=1704067200000,
        launch_time_max=1767225600000,
    )

    assert filters["keywords"] == ["DOGE", "PEPE"]
    assert filters["excludes"] == ["BTC", "ETH"]
    assert filters["socials"] == [1, 2]
    assert filters["alphaTagFilter"] == ["AI", "MEME"]
    assert filters["auditFilter"] == [0, 1]
    assert filters["tagFilter"] == [23, 29]
    assert filters["holdersTop10PercentMin"] == 10.5
    assert filters["holdersTop10PercentMax"] == 75.0
    assert filters["kycHoldersMin"] == 100
    assert filters["kycHoldersMax"] == 2500
    assert filters["countMin"] == 50
    assert filters["countMax"] == 5000
    assert filters["launchTimeMin"] == 1704067200000
    assert filters["launchTimeMax"] == 1767225600000


@pytest.mark.anyio
async def test_binance_unified_rank_endpoint_forwards_skill_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get_unified_token_rank(**kwargs):
        captured.update(kwargs)
        return {"items": [], "pagination": {"page": 1, "size": 1, "total": 0, "total_pages": 0}}

    monkeypatch.setattr("app.market.router.binance_rank.get_unified_token_rank", fake_get_unified_token_rank)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/market/binance/rank/unified",
            params={
                "rank_type": 20,
                "chain_id": "56",
                "period": 50,
                "sort_by": 40,
                "order_asc": "true",
                "keywords": "DOGE,PEPE",
                "excludes": "BTC,ETH",
                "socials": "1,2",
                "alpha_tag_filter": "AI,MEME",
                "audit_filter": "0,1",
                "tag_filter": "23,29",
                "holders_top10_percent_max": 80,
                "kyc_holders_min": 120,
                "count_min": 55,
                "launch_time_min": 1704067200000,
            },
        )

    assert resp.status_code == 200
    assert captured["rank_type"] == 20
    assert captured["chain_id"] == "56"
    assert captured["sort_by"] == 40
    assert captured["order_asc"] is True
    assert captured["filters"] == {
        "keywords": ["DOGE", "PEPE"],
        "excludes": ["BTC", "ETH"],
        "socials": [1, 2],
        "alphaTagFilter": ["AI", "MEME"],
        "auditFilter": [0, 1],
        "tagFilter": [23, 29],
        "holdersTop10PercentMax": 80.0,
        "kycHoldersMin": 120,
        "countMin": 55,
        "launchTimeMin": 1704067200000,
    }


@pytest.mark.anyio
async def test_binance_rank_dashboard_endpoint_forwards_advanced_skill_filters(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get_rank_dashboard(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "filters": kwargs}

    monkeypatch.setattr("app.market.router.binance_rank.get_rank_dashboard", fake_get_rank_dashboard)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/market/binance/rank/dashboard",
            params={
                "chain_id": "8453",
                "target_language": "en",
                "social_language": "en",
                "social_sentiment": "Positive",
                "unified_rank_type": 20,
                "unified_period": 50,
                "unified_sort_by": 40,
                "unified_order_asc": "true",
                "keyword": "DOGE",
                "unified_excludes": "BTC,ETH",
                "unified_socials": "1,2",
                "unified_alpha_tag_filter": "AI,MEME",
                "unified_audit_filter": "0,1",
                "unified_tag_filter": "23,29",
                "unified_holders_top10_percent_max": 80,
                "unified_kyc_holders_min": 120,
                "unified_count_min": 55,
                "unified_launch_time_min": 1704067200000,
                "limit": 12,
            },
        )

    assert resp.status_code == 200
    assert captured["chain_id"] == "8453"
    assert captured["target_language"] == "en"
    assert captured["social_language"] == "en"
    assert captured["social_sentiment"] == "Positive"
    assert captured["unified_rank_type"] == 20
    assert captured["unified_period"] == 50
    assert captured["unified_sort_by"] == 40
    assert captured["unified_order_asc"] is True
    assert captured["keyword"] == "DOGE"
    assert captured["unified_excludes"] == "BTC,ETH"
    assert captured["unified_socials"] == "1,2"
    assert captured["unified_alpha_tag_filter"] == "AI,MEME"
    assert captured["unified_audit_filter"] == "0,1"
    assert captured["unified_tag_filter"] == "23,29"
    assert captured["unified_holders_top10_percent_max"] == 80.0
    assert captured["unified_kyc_holders_min"] == 120
    assert captured["unified_count_min"] == 55
    assert captured["unified_launch_time_min"] == 1704067200000
    assert captured["limit"] == 12


@pytest.mark.anyio
async def test_estimate_market_amount_usd_uses_symbol_price(monkeypatch):
    async def fake_get_symbol_price(symbol):
        return {"symbol": symbol, "price": 2.0, "source": "coingecko"}

    async def fake_get_token_pairs(address, limit=20):
        return []

    monkeypatch.setattr("app.onchain.monitor_service.aggregator.get_symbol_price", fake_get_symbol_price)
    monkeypatch.setattr("app.onchain.monitor_service.dexscreener.get_token_pairs", fake_get_token_pairs)

    amount_usd, source = await _estimate_market_amount_usd(
        token="KPER",
        amount=418.29,
        amount_usd=None,
        blockchain="ethereum",
        metadata={},
    )

    assert amount_usd == pytest.approx(836.58)
    assert source == "coingecko"


@pytest.mark.anyio
async def test_estimate_market_amount_usd_uses_contract_price(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        return None

    async def fake_get_token_pairs(address, limit=20):
        assert address == "0xabc"
        return [
            {
                "chain": "ethereum",
                "price_usd": "1.5",
                "liquidity_usd": 150000,
                "volume_24h": 200000,
                "base_token": {"symbol": "KPER"},
            }
        ]

    async def fake_get_symbol_price(symbol):
        return None

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)
    monkeypatch.setattr("app.onchain.monitor_service.dexscreener.get_token_pairs", fake_get_token_pairs)
    monkeypatch.setattr("app.onchain.monitor_service.aggregator.get_symbol_price", fake_get_symbol_price)

    amount_usd, source = await _estimate_market_amount_usd(
        token="KPER",
        amount=100,
        amount_usd=None,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert amount_usd == pytest.approx(150.0)
    assert source == "dexscreener"


@pytest.mark.anyio
async def test_estimate_market_amount_usd_uses_contract_price_when_symbol_unknown(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        return None

    async def fake_get_token_pairs(address, limit=20):
        return [
            {
                "chain": "ethereum",
                "price_usd": "0.25",
                "liquidity_usd": 300000,
                "volume_24h": 120000,
                "base_token": {"symbol": "BAYC"},
            }
        ]

    async def fake_get_price_by_contract(blockchain, contract_address):
        return None

    async def fake_get_symbol_price(symbol):
        return None

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)
    monkeypatch.setattr("app.onchain.monitor_service.dexscreener.get_token_pairs", fake_get_token_pairs)
    monkeypatch.setattr("app.onchain.monitor_service.coingecko.get_price_by_contract", fake_get_price_by_contract)
    monkeypatch.setattr("app.onchain.monitor_service.aggregator.get_symbol_price", fake_get_symbol_price)

    amount_usd, source = await _estimate_market_amount_usd(
        token="UNKNOWN",
        amount=100,
        amount_usd=None,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert amount_usd == pytest.approx(25.0)
    assert source == "dexscreener"


@pytest.mark.anyio
async def test_estimate_market_snapshot_promotes_unknown_symbol_from_contract_price(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        assert blockchain == "ethereum"
        assert contract_address == "0xabc"
        return {
            "price": 0.25,
            "source": "geckoterminal",
            "symbol": "BAYC",
            "name": "Bored Ape Yacht Club",
        }

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)

    snapshot = await _estimate_market_snapshot(
        token="UNKNOWN",
        amount=100,
        amount_usd=None,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert snapshot is not None
    assert snapshot["amount_usd"] == pytest.approx(25.0)
    assert snapshot["amount_usd_source"] == "geckoterminal"
    assert snapshot["resolved_symbol"] == "BAYC"
    assert snapshot["resolved_name"] == "Bored Ape Yacht Club"


@pytest.mark.anyio
async def test_estimate_market_snapshot_resolves_symbol_even_when_amount_usd_exists(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        return {
            "price": 0.25,
            "source": "geckoterminal",
            "symbol": "BAYC",
            "name": "Bored Ape Yacht Club",
        }

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)

    snapshot = await _estimate_market_snapshot(
        token="UNKNOWN",
        amount=100,
        amount_usd=0.00009483,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert snapshot is not None
    assert snapshot["amount_usd"] == pytest.approx(0.00009483)
    assert snapshot["amount_usd_source"] is None
    assert snapshot["resolved_symbol"] == "BAYC"
    assert snapshot["resolved_name"] == "Bored Ape Yacht Club"


@pytest.mark.anyio
async def test_estimate_market_amount_usd_uses_geckoterminal_contract_price(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        assert blockchain == "ethereum"
        assert contract_address == "0xabc"
        return {"price": 0.00001594, "source": "geckoterminal"}

    async def fake_get_token_pairs(address, limit=20):
        return []

    async def fake_get_price_by_contract(blockchain, contract_address):
        return None

    async def fake_get_symbol_price(symbol):
        return None

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)
    monkeypatch.setattr("app.onchain.monitor_service.dexscreener.get_token_pairs", fake_get_token_pairs)
    monkeypatch.setattr("app.onchain.monitor_service.coingecko.get_price_by_contract", fake_get_price_by_contract)
    monkeypatch.setattr("app.onchain.monitor_service.aggregator.get_symbol_price", fake_get_symbol_price)

    amount_usd, source = await _estimate_market_amount_usd(
        token="KPER",
        amount=418.29,
        amount_usd=None,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert amount_usd == pytest.approx(0.0066675426)
    assert source == "geckoterminal"


@pytest.mark.anyio
async def test_estimate_market_amount_usd_uses_coingecko_contract_price(monkeypatch):
    async def fake_geckoterminal_price(blockchain, contract_address):
        return None

    async def fake_get_token_pairs(address, limit=20):
        return []

    async def fake_get_price_by_contract(blockchain, contract_address):
        assert blockchain == "ethereum"
        assert contract_address == "0xabc"
        return {"price": 0.5, "source": "coingecko_contract"}

    async def fake_get_symbol_price(symbol):
        return None

    monkeypatch.setattr("app.onchain.monitor_service.geckoterminal.get_token_price", fake_geckoterminal_price)
    monkeypatch.setattr("app.onchain.monitor_service.dexscreener.get_token_pairs", fake_get_token_pairs)
    monkeypatch.setattr("app.onchain.monitor_service.coingecko.get_price_by_contract", fake_get_price_by_contract)
    monkeypatch.setattr("app.onchain.monitor_service.aggregator.get_symbol_price", fake_get_symbol_price)

    amount_usd, source = await _estimate_market_amount_usd(
        token="UNKNOWN",
        amount=100,
        amount_usd=None,
        blockchain="ethereum",
        metadata={"token_address": "0xabc"},
    )

    assert amount_usd == pytest.approx(50.0)
    assert source == "coingecko_contract"


def test_merge_transfer_event_into_alert_backfills_metadata():
    alert = WhaleAlert(
        address="0xabc",
        action="incoming",
        amount=10,
        token="UNKNOWN",
        tx_hash="0xhash",
        notification_status=None,
        metadata_json={},
    )
    transfer = WhaleTransferEvent(
        id=12,
        external_id="evt-12",
        address="0xabc",
        blockchain="ethereum",
        entity_name="Wintermute",
        label="Wintermute Multisig",
        counterparty_address="0xdef",
        token=None,
        amount=10,
        amount_usd=None,
        tx_hash="0xhash",
        source="surf:wallet-transfers",
        metadata_json={"token_address": "0x123", "token_symbol": "NEWT"},
    )

    changed = _merge_transfer_event_into_alert(alert, transfer)

    assert changed is True
    assert alert.event_id == 12
    assert alert.external_id == "evt-12"
    assert alert.blockchain == "ethereum"
    assert alert.entity_name == "Wintermute"
    assert alert.label == "Wintermute Multisig"
    assert alert.counterparty_address == "0xdef"
    assert alert.token == "NEWT"
    assert alert.metadata_json["token_address"] == "0x123"
