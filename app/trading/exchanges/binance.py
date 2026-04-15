"""Binance exchange adapter — ported from agent-trading-bot.

Requires API key + secret for trading operations.
Read-only operations (balance, orders) work in testnet mode.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import logging
from typing import Any
from urllib.parse import urlencode

from app.common.http_client import fetch_json
from app.config import settings
from app.trading.exchanges.base import ExchangeBase, OrderResult

logger = logging.getLogger("bitinfo.trading.binance")

SPOT_BASE = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"
TESTNET_SPOT = "https://testnet.binance.vision"
TESTNET_FUTURES = "https://testnet.binancefuture.com"


class BinanceExchange(ExchangeBase):
    name = "binance"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        futures: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.futures = futures
        if futures:
            self.base = TESTNET_FUTURES if testnet else FUTURES_BASE
        else:
            self.base = TESTNET_SPOT if testnet else SPOT_BASE

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    async def get_balance(self) -> dict[str, float]:
        if not self.api_key:
            return {"error": "API key not configured"}
        path = "/fapi/v2/balance" if self.futures else "/api/v3/account"
        params = self._sign({})
        data = await fetch_json(
            f"{self.base}{path}", params=params, headers=self._headers()
        )
        if self.futures:
            return {b["asset"]: float(b["balance"]) for b in data if float(b.get("balance", 0)) > 0}
        balances = data.get("balances", [])
        return {b["asset"]: float(b["free"]) for b in balances if float(b.get("free", 0)) > 0}

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> OrderResult:
        if not self.api_key:
            return OrderResult(success=False, error="API key not configured")

        path = "/fapi/v1/order" if self.futures else "/api/v3/order"
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type,
            "quantity": quantity,
        }
        if order_type == "LIMIT" and price is not None:
            params["price"] = price
            params["timeInForce"] = "GTC"

        signed = self._sign(params)
        try:
            data = await fetch_json(
                f"{self.base}{path}", params=signed, headers=self._headers()
            )
            return OrderResult(
                success=True,
                order_id=str(data.get("orderId")),
                symbol=symbol,
                side=side,
                price=float(data.get("price", 0)),
                quantity=quantity,
                status=data.get("status", ""),
            )
        except Exception as e:
            return OrderResult(success=False, error=str(e), symbol=symbol, side=side)

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        if not self.api_key:
            return False
        path = "/fapi/v1/order" if self.futures else "/api/v3/order"
        params = self._sign({"symbol": symbol, "orderId": order_id})
        try:
            await fetch_json(f"{self.base}{path}", params=params, headers=self._headers())
            return True
        except Exception:
            return False

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        path = "/fapi/v1/openOrders" if self.futures else "/api/v3/openOrders"
        p: dict[str, Any] = {}
        if symbol:
            p["symbol"] = symbol
        data = await fetch_json(f"{self.base}{path}", params=self._sign(p), headers=self._headers())
        return data if isinstance(data, list) else []

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        if not self.futures or not self.api_key:
            return None
        data = await fetch_json(
            f"{self.base}/fapi/v2/positionRisk",
            params=self._sign({"symbol": symbol}),
            headers=self._headers(),
        )
        for pos in (data if isinstance(data, list) else []):
            if float(pos.get("positionAmt", 0)) != 0:
                return pos
        return None
