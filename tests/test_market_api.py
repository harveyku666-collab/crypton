import pytest

from app.market.aggregator import get_symbol_price
from app.onchain.monitor_service import _estimate_market_amount_usd


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
