"""Abstract exchange interface — all exchange adapters implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class OrderResult:
    success: bool
    order_id: str | None = None
    symbol: str = ""
    side: str = ""
    price: float = 0
    quantity: float = 0
    status: str = ""
    error: str | None = None


class ExchangeBase(ABC):
    name: str = ""

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Get account balances."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> OrderResult:
        """Place a buy/sell order."""

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order."""

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Get all open orders."""

    @abstractmethod
    async def get_position(self, symbol: str) -> dict[str, Any] | None:
        """Get current position for a symbol (futures)."""
