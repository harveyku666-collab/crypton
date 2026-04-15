"""OKX exchange adapter — ported from btc-strategy-v40.

Placeholder: implements the ExchangeBase interface for OKX.
Requires OKX API credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import logging
from typing import Any
from datetime import datetime, timezone

from app.common.http_client import fetch_json
from app.trading.exchanges.base import ExchangeBase, OrderResult

logger = logging.getLogger("bitinfo.trading.okx")

OKX_BASE = "https://www.okx.com"
OKX_DEMO = "https://www.okx.com"


class OKXExchange(ExchangeBase):
    name = "okx"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        demo: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo = demo
        self.base = OKX_BASE

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        msg = timestamp + method + path + body
        mac = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        sign = self._sign(ts, method, path, body)
        h = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            h["x-simulated-trading"] = "1"
        return h

    async def get_balance(self) -> dict[str, float]:
        if not self.api_key:
            return {"error": "API key not configured"}
        path = "/api/v5/account/balance"
        data = await fetch_json(
            f"{self.base}{path}", headers=self._headers("GET", path)
        )
        result = {}
        for detail in data.get("data", [{}])[0].get("details", []):
            bal = float(detail.get("availBal", 0))
            if bal > 0:
                result[detail["ccy"]] = bal
        return result

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

        okx_type = "market" if order_type == "MARKET" else "limit"
        inst_id = symbol.replace("USDT", "-USDT")

        import json
        body = json.dumps({
            "instId": inst_id,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": okx_type,
            "sz": str(quantity),
            **({"px": str(price)} if price and okx_type == "limit" else {}),
        })

        path = "/api/v5/trade/order"
        try:
            data = await fetch_json(
                f"{self.base}{path}", headers=self._headers("POST", path, body)
            )
            order_data = data.get("data", [{}])[0]
            return OrderResult(
                success=data.get("code") == "0",
                order_id=order_data.get("ordId"),
                symbol=symbol,
                side=side,
                quantity=quantity,
                status="submitted",
            )
        except Exception as e:
            return OrderResult(success=False, error=str(e), symbol=symbol, side=side)

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        if not self.api_key:
            return False
        import json
        inst_id = symbol.replace("USDT", "-USDT")
        body = json.dumps({"instId": inst_id, "ordId": order_id})
        path = "/api/v5/trade/cancel-order"
        try:
            data = await fetch_json(
                f"{self.base}{path}", headers=self._headers("POST", path, body)
            )
            return data.get("code") == "0"
        except Exception:
            return False

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        path = "/api/v5/trade/orders-pending"
        params = {}
        if symbol:
            params["instId"] = symbol.replace("USDT", "-USDT")
        data = await fetch_json(
            f"{self.base}{path}", params=params, headers=self._headers("GET", path)
        )
        return data.get("data", [])

    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        path = "/api/v5/account/positions"
        inst_id = symbol.replace("USDT", "-USDT")
        data = await fetch_json(
            f"{self.base}{path}",
            params={"instId": inst_id},
            headers=self._headers("GET", path),
        )
        positions = data.get("data", [])
        for pos in positions:
            if float(pos.get("pos", 0)) != 0:
                return pos
        return None
