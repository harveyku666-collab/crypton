import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.anyio
async def test_whale_monitor_status_endpoint(monkeypatch):
    async def fake_status():
        return {
            "db_available": True,
            "status": "ok",
            "watched_address_count": 2,
            "event_count": 5,
            "monitor_interval_minutes": 15,
        }

    monkeypatch.setattr("app.onchain.router.get_whale_monitor_status", fake_status)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whale-monitor/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["watched_address_count"] == 2


@pytest.mark.anyio
async def test_whale_monitor_run_endpoint(monkeypatch):
    async def fake_collect(*, force=False):
        return {
            "status": "ok",
            "watched_address_count": 1,
            "stored_event_count": 3,
            "force": force,
        }

    monkeypatch.setattr("app.onchain.router.collect_whale_transfer_events", fake_collect)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/onchain/whale-monitor/run", json={"force": True})

    assert resp.status_code == 200
    data = resp.json()
    assert data["stored_event_count"] == 3
    assert data["force"] is True


@pytest.mark.anyio
async def test_whale_monitor_events_endpoint(monkeypatch):
    async def fake_events(*, chain=None, address=None, limit=50):
        return [
            {
                "address": "0xabc",
                "blockchain": chain or "ethereum",
                "token": "ETH",
                "amount_usd": 1500000,
            }
        ]

    monkeypatch.setattr("app.onchain.router.list_whale_transfer_events", fake_events)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whale-monitor/events", params={"chain": "ethereum", "limit": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["token"] == "ETH"


@pytest.mark.anyio
async def test_whale_monitor_alerts_endpoint(monkeypatch):
    async def fake_alerts(*, severity=None, limit=50):
        return [
            {
                "address": "0xabc",
                "severity": severity or "high",
                "token": "USDT",
                "amount_usd": 5_600_000,
            }
        ]

    monkeypatch.setattr("app.onchain.router.list_whale_alerts", fake_alerts)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whale-monitor/alerts", params={"severity": "high", "limit": 10})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["severity"] == "high"


@pytest.mark.anyio
async def test_whale_monitor_channels_endpoint(monkeypatch):
    async def fake_channels():
        return [
            {
                "name": "default-log",
                "channel_type": "log",
                "min_severity": "high",
                "is_active": True,
            }
        ]

    monkeypatch.setattr("app.onchain.router.list_whale_notification_channels", fake_channels)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whale-monitor/channels")

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["channel_type"] == "log"


@pytest.mark.anyio
async def test_whale_monitor_channel_bulk_upsert_endpoint(monkeypatch):
    async def fake_upsert(rows):
        return {"count": len(rows), "created": len(rows), "updated": 0}

    monkeypatch.setattr("app.onchain.router.upsert_whale_notification_channels", fake_upsert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/onchain/whale-monitor/channels/bulk-upsert",
            json=[
                {
                    "name": "ops-webhook",
                    "channel_type": "webhook",
                    "target": "https://example.com/hook",
                    "min_severity": "critical",
                    "is_active": True,
                    "metadata": {"headers": {"X-Test": "1"}},
                }
            ],
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] == 1


@pytest.mark.anyio
async def test_whale_monitor_deliveries_endpoint(monkeypatch):
    async def fake_deliveries(*, delivery_status=None, limit=50):
        return [
            {
                "alert_id": 1,
                "channel_id": 1,
                "delivery_status": delivery_status or "sent",
            }
        ]

    monkeypatch.setattr("app.onchain.router.list_whale_notification_deliveries", fake_deliveries)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whale-monitor/deliveries", params={"delivery_status": "sent"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["items"][0]["delivery_status"] == "sent"


@pytest.mark.anyio
async def test_whale_transactions_endpoint(monkeypatch):
    async def fake_recent(min_value=1_000_000, limit=20):
        return [{"address": "0xabc", "amount_usd": min_value, "token": "BTC"}]

    monkeypatch.setattr("app.onchain.router.get_recent_transactions", fake_recent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/onchain/whales", params={"min_value": 2000000, "limit": 5})

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["amount_usd"] == 2000000
