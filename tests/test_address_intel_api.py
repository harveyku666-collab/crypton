import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.address_intel.service import infer_address_type, infer_is_whale
from app.address_intel.legacy_store import build_freshness_status


@pytest.mark.anyio
async def test_address_intel_dashboard_endpoint(monkeypatch):
    async def fake_dashboard(*, q=None, chain="ethereum", entity_type=None, limit=20):
        return {
            "query": q,
            "chain": chain,
            "entity_type": entity_type,
            "overview": {
                "tracked_count": 12,
                "exchange_count": 4,
                "institution_count": 3,
                "whale_count": 5,
                "db_available": True,
            },
            "tracked_items": [{"address": "0xabc", "address_type": "exchange"}],
            "search_results": [{"address": "0xdef", "address_type": "institution"}],
            "profile": None,
            "featured": {"exchanges": [], "institutions": [], "whales": []},
        }

    monkeypatch.setattr("app.address_intel.router.build_address_intel_dashboard", fake_dashboard)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/address-intel/dashboard",
            params={"q": "Binance", "chain": "ethereum", "entity_type": "exchange", "limit": 10},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Binance"
    assert data["overview"]["tracked_count"] == 12
    assert data["search_results"][0]["address_type"] == "institution"


@pytest.mark.anyio
async def test_address_intel_profile_endpoint(monkeypatch):
    async def fake_profile(address, *, chain="ethereum", history_limit=10, transfer_limit=10, time_range="30d"):
        return {
            "entity": {
                "address": address,
                "blockchain": chain,
                "entity_name": "Binance Cold Wallet",
                "address_type": "exchange",
                "is_whale": True,
            },
            "wallet_detail": {"balance_usd": 2_500_000},
            "history": [{"action": "swap"}],
            "transfers": [{"token": "ETH"}],
            "net_worth": [{"value": 2_500_000}],
            "summary": {"history_count": 1, "transfer_count": 1},
        }

    monkeypatch.setattr("app.address_intel.router.get_address_profile", fake_profile)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/address-intel/profile/0x1234567890abcdef1234567890abcdef12345678")

    assert resp.status_code == 200
    data = resp.json()
    assert data["entity"]["address_type"] == "exchange"
    assert data["summary"]["transfer_count"] == 1


@pytest.mark.anyio
async def test_address_intel_bulk_upsert_endpoint(monkeypatch):
    async def fake_bulk_upsert(items):
        return {"count": len(items), "created": 1, "updated": 0, "items": items}

    monkeypatch.setattr("app.address_intel.router.bulk_upsert_monitored_addresses", fake_bulk_upsert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/address-intel/entities/bulk-upsert",
            json={
                "items": [
                    {
                        "address": "0x1234567890abcdef1234567890abcdef12345678",
                        "blockchain": "ethereum",
                        "label": "Binance Cold Wallet",
                        "address_type": "exchange",
                        "is_whale": True,
                    }
                ]
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["created"] == 1


def test_address_type_heuristics_detect_exchange_and_whale():
    exchange = infer_address_type({"label": "Binance Cold Wallet"})
    institution = infer_address_type({"label": "BlackRock ETF Treasury"})
    whale = infer_is_whale({"label": "Smart Money Whale", "balance_usd": 2_000_000}, address_type="whale")

    assert exchange == "exchange"
    assert institution == "institution"
    assert whale is True


def test_legacy_freshness_marks_future_sample_data():
    freshness = build_freshness_status(
        last_daily_report_date="2028-06-14",
        last_event_at="2028-06-14T09:30:00",
    )

    assert freshness["status"] == "future_sample_data"
    assert freshness["warnings"]
