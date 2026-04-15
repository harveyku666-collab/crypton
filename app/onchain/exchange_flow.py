"""Exchange inflow/outflow monitoring.

Tracks net flow of BTC/ETH into and out of major exchanges —
a key indicator for sell pressure vs accumulation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.cache import cached

logger = logging.getLogger("bitinfo.onchain.flow")


@cached(ttl=300, prefix="exchange_flow")
async def get_exchange_netflow() -> dict[str, Any]:
    """Get exchange net flow data.

    TODO: integrate with CryptoQuant, Glassnode, or similar on-chain data provider.
    Initial scaffold returns empty data.
    """
    return {
        "btc_netflow": None,
        "eth_netflow": None,
        "note": "On-chain data provider not yet configured. Integrate CryptoQuant or Glassnode API.",
    }


@cached(ttl=300, prefix="exchange_flow")
async def get_sopr() -> dict[str, Any]:
    """Spent Output Profit Ratio — measures whether coins moved on-chain are in profit.

    TODO: integrate data provider.
    """
    return {"sopr": None, "note": "Requires on-chain data provider integration."}
