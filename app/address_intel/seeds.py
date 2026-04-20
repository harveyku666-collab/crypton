"""Curated default monitored address seeds.

These are public, widely labeled addresses used to bootstrap the
institution / whale watchlist when the database is empty or when the
server runs a scheduled sync.
"""

from __future__ import annotations

from typing import Any


DEFAULT_MONITORED_ADDRESS_SEEDS: list[dict[str, Any]] = [
    {
        "address": "0xf584F8728B874a6a5c7A8d4d387C9aae9172D621",
        "blockchain": "ethereum",
        "label": "Jump Trading",
        "entity_name": "Jump Trading",
        "address_type": "institution",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0xf584F8728B874a6a5c7A8d4d387C9aae9172D621",
            "notes": "Publicly labeled Jump Trading address.",
        },
    },
    {
        "address": "0xad6eaa735D9dF3D7696fd03984379dAE02eD8862",
        "blockchain": "ethereum",
        "label": "Cumberland",
        "entity_name": "Cumberland",
        "address_type": "institution",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0xad6eaa735D9dF3D7696fd03984379dAE02eD8862",
            "notes": "Publicly labeled Cumberland address.",
        },
    },
    {
        "address": "0x4f3a120E72C76c22ae802D129F599BFDbc31cb81",
        "blockchain": "ethereum",
        "label": "Wintermute Multisig",
        "entity_name": "Wintermute",
        "address_type": "institution",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0x4f3a120E72C76c22ae802D129F599BFDbc31cb81",
            "notes": "Publicly labeled Wintermute multisig contract.",
        },
    },
    {
        "address": "0x5797F722b1FeE36e3D2c3481D938d1372bCD99A7",
        "blockchain": "ethereum",
        "label": "Galaxy Digital",
        "entity_name": "Galaxy Digital",
        "address_type": "institution",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0x5797F722b1FeE36e3D2c3481D938d1372bCD99A7",
            "notes": "Publicly labeled Galaxy Digital address.",
        },
    },
    {
        "address": "0xE11970f2F3dE9d637Fb786f2d869F8FeA44195AC",
        "blockchain": "ethereum",
        "label": "Amber Group",
        "entity_name": "Amber Group",
        "address_type": "institution",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0xE11970f2F3dE9d637Fb786f2d869F8FeA44195AC",
            "notes": "Publicly labeled Amber Group address.",
        },
    },
    {
        "address": "0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296",
        "blockchain": "ethereum",
        "label": "Justin Sun",
        "entity_name": "Justin Sun",
        "address_type": "whale",
        "is_whale": True,
        "alert_threshold": 1_000_000,
        "source": "public_seed",
        "metadata": {
            "seed_type": "public_whale_watchlist",
            "source_name": "Etherscan",
            "source_url": "https://etherscan.io/address/0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296",
            "notes": "Publicly labeled Justin Sun address.",
        },
    },
]


def get_default_monitored_address_seeds() -> list[dict[str, Any]]:
    return [dict(item) for item in DEFAULT_MONITORED_ADDRESS_SEEDS]
