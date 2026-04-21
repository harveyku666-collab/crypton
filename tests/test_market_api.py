import pytest

from app.common.models import WhaleAlert, WhaleTransferEvent
from app.market.aggregator import get_symbol_price
from app.onchain.monitor_service import _estimate_market_amount_usd, _merge_transfer_event_into_alert


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
