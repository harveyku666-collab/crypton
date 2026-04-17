"""Supplemental OI context: timeframe presets, orderbook, chip zone, and flow."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.common.http_client import fetch_json
from app.market.sources import binance, gateio

SUPPORTED_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
DEFAULT_TIMEFRAME = "1h"
DEFAULT_CHIP_INTERVAL = "4h"

TIMEFRAME_PRESETS: dict[str, dict[str, float | int]] = {
    "5m": {
        "dP_strong": 0.010,
        "dOI_strong": 0.015,
        "dP_extreme": 0.020,
        "dOI_squeeze": 0.025,
        "dOI_surge": 0.040,
        "vol_hot": 3.0,
        "vol_low": 0.5,
        "w_quadrant": 20,
        "w_funding": 10,
        "w_vol": 20,
        "w_ls": 8,
    },
    "15m": {
        "dP_strong": 0.015,
        "dOI_strong": 0.025,
        "dP_extreme": 0.030,
        "dOI_squeeze": 0.040,
        "dOI_surge": 0.060,
        "vol_hot": 2.5,
        "vol_low": 0.6,
        "w_quadrant": 25,
        "w_funding": 12,
        "w_vol": 18,
        "w_ls": 9,
    },
    "1h": {
        "dP_strong": 0.025,
        "dOI_strong": 0.040,
        "dP_extreme": 0.040,
        "dOI_squeeze": 0.060,
        "dOI_surge": 0.100,
        "vol_hot": 2.0,
        "vol_low": 0.7,
        "w_quadrant": 30,
        "w_funding": 15,
        "w_vol": 15,
        "w_ls": 10,
    },
    "4h": {
        "dP_strong": 0.050,
        "dOI_strong": 0.080,
        "dP_extreme": 0.070,
        "dOI_squeeze": 0.100,
        "dOI_surge": 0.150,
        "vol_hot": 1.8,
        "vol_low": 0.8,
        "w_quadrant": 35,
        "w_funding": 18,
        "w_vol": 12,
        "w_ls": 12,
    },
    "1d": {
        "dP_strong": 0.080,
        "dOI_strong": 0.120,
        "dP_extreme": 0.120,
        "dOI_squeeze": 0.150,
        "dOI_surge": 0.250,
        "vol_hot": 1.6,
        "vol_low": 0.8,
        "w_quadrant": 40,
        "w_funding": 20,
        "w_vol": 10,
        "w_ls": 15,
    },
}

SYMBOL_CONFIG: dict[str, dict[str, str]] = {
    "BTC": {"binance": "BTCUSDT", "okx": "BTC-USDT-SWAP", "bybit": "BTCUSDT"},
    "ETH": {"binance": "ETHUSDT", "okx": "ETH-USDT-SWAP", "bybit": "ETHUSDT"},
    "SOL": {"binance": "SOLUSDT", "okx": "SOL-USDT-SWAP", "bybit": "SOLUSDT"},
}

CHIP_BINS = {"BTC": 60, "ETH": 60, "SOL": 50}
CHIP_LIMITS = {"5m": 240, "15m": 192, "1h": 168, "4h": 240, "1d": 180}
FLOW_LOOKBACKS = {"5m": 288, "15m": 192, "1h": 72, "4h": 60, "1d": 30}
PRICE_MIN_DECIMALS = 2
PRICE_MAX_DECIMALS = 8
PRICE_SIGNIFICANT_DIGITS = 4


def normalize_timeframe(timeframe: str | None) -> str:
    if not timeframe:
        return DEFAULT_TIMEFRAME
    tf = timeframe.strip().lower()
    return tf if tf in SUPPORTED_TIMEFRAMES else DEFAULT_TIMEFRAME


def normalize_chip_interval(interval: str | None, timeframe: str | None = None) -> str:
    if interval:
        tf = normalize_timeframe(interval)
        if tf != "5m":
            return tf
    tf = normalize_timeframe(timeframe)
    return "15m" if tf == "5m" else tf if tf in {"15m", "1h", "4h", "1d"} else DEFAULT_CHIP_INTERVAL


def get_timeframe_preset(timeframe: str) -> dict[str, float | int]:
    return TIMEFRAME_PRESETS[normalize_timeframe(timeframe)]


def get_symbol_config(symbol: str) -> dict[str, str]:
    key = symbol.upper()
    if key in SYMBOL_CONFIG:
        return SYMBOL_CONFIG[key]
    return {
        "binance": f"{key}USDT",
        "okx": f"{key}-USDT-SWAP",
        "bybit": f"{key}USDT",
    }


def price_decimals(value: float | None) -> int:
    if value is None:
        return PRICE_MIN_DECIMALS
    numeric = abs(float(value))
    if numeric == 0:
        return PRICE_MIN_DECIMALS
    digits = PRICE_SIGNIFICANT_DIGITS - int(math.floor(math.log10(numeric))) - 1
    return max(PRICE_MIN_DECIMALS, min(PRICE_MAX_DECIMALS, digits))


def round_price(value: float | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    return round(numeric, price_decimals(numeric))


def format_price(value: float | None) -> str:
    if value is None:
        return "-"
    numeric = float(value)
    return f"{numeric:,.{price_decimals(numeric)}f}"


@dataclass
class OrderbookSnapshot:
    exchange: str
    symbol: str
    mid: float | None = None
    spread_bps: float | None = None
    bid_usd_1pct: float = 0.0
    ask_usd_1pct: float = 0.0
    bid_usd_5pct: float = 0.0
    ask_usd_5pct: float = 0.0
    imbalance_1pct: float | None = None
    imbalance_5pct: float | None = None
    bid_walls: list[dict[str, Any]] = field(default_factory=list)
    ask_walls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _imbalance(bid: float, ask: float) -> float | None:
    total = bid + ask
    return (bid - ask) / total if total else None


def _analyze_orderbook(
    bids: list[list[Any]],
    asks: list[list[Any]],
    *,
    exchange: str,
    symbol: str,
) -> OrderbookSnapshot:
    snap = OrderbookSnapshot(exchange=exchange, symbol=symbol)
    if not bids or not asks:
        snap.error = "empty book"
        return snap

    best_bid_px, best_bid_sz = float(bids[0][0]), float(bids[0][1])
    best_ask_px, best_ask_sz = float(asks[0][0]), float(asks[0][1])
    mid = (best_bid_px + best_ask_px) / 2
    if mid <= 0:
        snap.error = "invalid mid price"
        return snap
    snap.mid = mid
    snap.spread_bps = (best_ask_px - best_bid_px) / mid * 1e4

    def accumulate(side: list[list[Any]], sign: int) -> dict[int, float]:
        totals = {1: 0.0, 5: 0.0}
        for px_raw, sz_raw, *_ in side:
            px = float(px_raw)
            sz = float(sz_raw)
            diff = (px - mid) / mid * 100 * sign
            if diff < 0:
                continue
            for band in (1, 5):
                if diff <= band:
                    totals[band] += px * sz
        return totals

    bid_totals = accumulate(bids, -1)
    ask_totals = accumulate(asks, +1)
    snap.bid_usd_1pct = bid_totals[1]
    snap.ask_usd_1pct = ask_totals[1]
    snap.bid_usd_5pct = bid_totals[5]
    snap.ask_usd_5pct = ask_totals[5]
    snap.imbalance_1pct = _imbalance(snap.bid_usd_1pct, snap.ask_usd_1pct)
    snap.imbalance_5pct = _imbalance(snap.bid_usd_5pct, snap.ask_usd_5pct)

    def find_walls(side: list[list[Any]], sign: int) -> list[dict[str, Any]]:
        in_band: list[tuple[float, float]] = []
        for px_raw, sz_raw, *_ in side:
            px = float(px_raw)
            sz = float(sz_raw)
            diff = (px - mid) / mid * 100 * sign
            if 0 <= diff <= 5:
                in_band.append((px, px * sz))
        if not in_band:
            return []
        avg_usd = sum(v for _, v in in_band) / len(in_band)
        walls = [{"price": p, "usd": round(v, 2)} for p, v in in_band if v > avg_usd * 5]
        walls.sort(key=lambda item: item["usd"], reverse=True)
        return walls[:5]

    snap.bid_walls = find_walls(bids, -1)
    snap.ask_walls = find_walls(asks, +1)
    return snap


async def _fetch_binance_orderbook(symbol: str) -> OrderbookSnapshot:
    pair = get_symbol_config(symbol)["binance"]
    try:
        data = await fetch_json(
            f"{binance.FAPI}/fapi/v1/depth",
            params={"symbol": pair, "limit": 500},
        )
        return _analyze_orderbook(data.get("bids") or [], data.get("asks") or [], exchange="binance", symbol=pair)
    except Exception as exc:
        return OrderbookSnapshot(exchange="binance", symbol=pair, error=str(exc))


async def _fetch_okx_orderbook(symbol: str) -> OrderbookSnapshot:
    pair = get_symbol_config(symbol)["okx"]
    try:
        data = await fetch_json(
            "https://www.okx.com/api/v5/market/books-full",
            params={"instId": pair, "sz": 400},
        )
        rows = data.get("data") or []
        row = rows[0] if rows else {}
        return _analyze_orderbook(row.get("bids") or [], row.get("asks") or [], exchange="okx", symbol=pair)
    except Exception as exc:
        return OrderbookSnapshot(exchange="okx", symbol=pair, error=str(exc))


async def _fetch_bybit_orderbook(symbol: str) -> OrderbookSnapshot:
    pair = get_symbol_config(symbol)["bybit"]
    try:
        data = await fetch_json(
            "https://api.bybit.com/v5/market/orderbook",
            params={"category": "linear", "symbol": pair, "limit": 500},
        )
        row = data.get("result") or {}
        return _analyze_orderbook(row.get("b") or [], row.get("a") or [], exchange="bybit", symbol=pair)
    except Exception as exc:
        return OrderbookSnapshot(exchange="bybit", symbol=pair, error=str(exc))


async def get_orderbook_context(symbol: str) -> dict[str, Any]:
    snaps = await asyncio.gather(
        _fetch_binance_orderbook(symbol),
        _fetch_okx_orderbook(symbol),
        _fetch_bybit_orderbook(symbol),
    )
    valid = [snap for snap in snaps if snap.error is None and snap.mid is not None]
    if not valid:
        return {"error": "no valid orderbook"}

    bid1 = sum(item.bid_usd_1pct for item in valid)
    ask1 = sum(item.ask_usd_1pct for item in valid)
    bid5 = sum(item.bid_usd_5pct for item in valid)
    ask5 = sum(item.ask_usd_5pct for item in valid)
    bid_walls = sorted(
        [{**wall, "ex": snap.exchange} for snap in valid for wall in snap.bid_walls],
        key=lambda item: item["usd"],
        reverse=True,
    )
    ask_walls = sorted(
        [{**wall, "ex": snap.exchange} for snap in valid for wall in snap.ask_walls],
        key=lambda item: item["usd"],
        reverse=True,
    )

    return {
        "mid": round_price(sum(item.mid or 0 for item in valid) / len(valid)),
        "spread_bps_avg": round(sum(item.spread_bps or 0 for item in valid) / len(valid), 2),
        "bid_usd_1pct": round(bid1, 2),
        "ask_usd_1pct": round(ask1, 2),
        "bid_usd_5pct": round(bid5, 2),
        "ask_usd_5pct": round(ask5, 2),
        "imbalance_1pct": round(_imbalance(bid1, ask1), 4) if _imbalance(bid1, ask1) is not None else None,
        "imbalance_5pct": round(_imbalance(bid5, ask5), 4) if _imbalance(bid5, ask5) is not None else None,
        "top_bid_walls": bid_walls[:5],
        "top_ask_walls": ask_walls[:5],
        "per_exchange": {snap.exchange: snap.as_dict() for snap in snaps},
    }


async def _load_chip_klines(symbol: str, interval: str, limit: int) -> tuple[list[dict[str, float]], str]:
    pair = get_symbol_config(symbol)["binance"]
    rows = await binance.get_klines(pair, interval, limit)
    if rows:
        return [
            {"h": float(item[2]), "l": float(item[3]), "c": float(item[4]), "v": float(item[5])}
            for item in rows
        ], "binance-spot"

    raw = await fetch_json(
        f"{binance.FAPI}/fapi/v1/klines",
        params={"symbol": pair, "interval": interval, "limit": limit},
    )
    return [
        {"h": float(item[2]), "l": float(item[3]), "c": float(item[4]), "v": float(item[5])}
        for item in raw
    ], "binance-futures"


async def compute_chip_zone(
    symbol: str,
    *,
    interval: str = DEFAULT_CHIP_INTERVAL,
    price_now: float | None = None,
) -> dict[str, Any]:
    chip_interval = normalize_chip_interval(interval)
    limit = CHIP_LIMITS.get(chip_interval, CHIP_LIMITS[DEFAULT_CHIP_INTERVAL])
    bins_count = CHIP_BINS.get(symbol.upper(), 60)
    ts = int(time.time())

    try:
        klines, source = await _load_chip_klines(symbol, chip_interval, limit)
    except Exception as exc:
        return {
            "source": "none",
            "interval": chip_interval,
            "n_candles": 0,
            "price_now": price_now or 0,
            "poc": 0,
            "vah": 0,
            "val": 0,
            "hvn_zones": [],
            "lvn_zones": [],
            "cr70_width_pct": 0,
            "cr90_width_pct": 0,
            "concentration_score": 0,
            "position_vs_poc": "-",
            "position_vs_va": "-",
            "distribution": [],
            "ts": ts,
            "error": str(exc),
        }

    low = min(item["l"] for item in klines)
    high = max(item["h"] for item in klines)
    if high <= low:
        return {
            "source": source,
            "interval": chip_interval,
            "n_candles": len(klines),
            "price_now": price_now or 0,
            "poc": 0,
            "vah": 0,
            "val": 0,
            "hvn_zones": [],
            "lvn_zones": [],
            "cr70_width_pct": 0,
            "cr90_width_pct": 0,
            "concentration_score": 0,
            "position_vs_poc": "-",
            "position_vs_va": "-",
            "distribution": [],
            "ts": ts,
            "error": "invalid range",
        }

    bin_size = (high - low) / bins_count
    volumes = [0.0] * bins_count
    for item in klines:
        typical = (item["h"] + item["l"] + item["c"]) / 3
        idx = min(int((typical - low) / bin_size), bins_count - 1)
        volumes[idx] += item["v"]

    total_volume = sum(volumes)
    if total_volume <= 0:
        return {
            "source": source,
            "interval": chip_interval,
            "n_candles": len(klines),
            "price_now": price_now or (klines[-1]["c"] if klines else 0),
            "poc": 0,
            "vah": 0,
            "val": 0,
            "hvn_zones": [],
            "lvn_zones": [],
            "cr70_width_pct": 0,
            "cr90_width_pct": 0,
            "concentration_score": 0,
            "position_vs_poc": "-",
            "position_vs_va": "-",
            "distribution": [],
            "ts": ts,
            "error": "zero volume",
        }

    poc_idx = max(range(bins_count), key=lambda idx: volumes[idx])
    poc = low + (poc_idx + 0.5) * bin_size

    def expand(target: float) -> tuple[int, int]:
        lo_idx = hi_idx = poc_idx
        covered = volumes[poc_idx]
        while covered / total_volume < target and (lo_idx > 0 or hi_idx < bins_count - 1):
            left = volumes[lo_idx - 1] if lo_idx > 0 else -1
            right = volumes[hi_idx + 1] if hi_idx < bins_count - 1 else -1
            if left >= right:
                lo_idx -= 1
                covered += volumes[lo_idx]
            else:
                hi_idx += 1
                covered += volumes[hi_idx]
        return lo_idx, hi_idx

    val_lo, val_hi = expand(0.70)
    cr90_lo, cr90_hi = expand(0.90)
    val_price = low + val_lo * bin_size
    vah_price = low + (val_hi + 1) * bin_size
    total_width = high - low
    cr70_width_pct = ((val_hi - val_lo + 1) * bin_size) / total_width * 100
    cr90_width_pct = ((cr90_hi - cr90_lo + 1) * bin_size) / total_width * 100
    concentration = max(0.0, min(100.0, 100 - cr70_width_pct))

    def _zones(pairs: list[tuple[int, float]]) -> list[dict[str, Any]]:
        return [
            {
                "price": round_price(low + (idx + 0.5) * bin_size),
                "volume_pct": round(value / total_volume * 100, 2),
            }
            for idx, value in pairs
        ]

    hvn = sorted(enumerate(volumes), key=lambda item: item[1], reverse=True)[:5]
    lvn = sorted([item for item in enumerate(volumes) if item[1] > 0], key=lambda item: item[1])[:5]
    price_ref = price_now if price_now is not None else klines[-1]["c"]

    if abs(price_ref - poc) / poc < 0.005:
        pos_poc = "贴近 POC（主力成本区）"
    elif price_ref > poc:
        pos_poc = f"高于 POC {(price_ref - poc) / poc * 100:+.2f}%（多头获利）"
    else:
        pos_poc = f"低于 POC {(price_ref - poc) / poc * 100:+.2f}%（多头套牢）"

    if price_ref > vah_price:
        pos_va = "位于 VA 上方（超买区，回归 POC 概率大）"
    elif price_ref < val_price:
        pos_va = "位于 VA 下方（超卖区，回归 POC 概率大）"
    else:
        pos_va = "位于 VA 内部（价值区震荡）"

    return {
        "source": source,
        "interval": chip_interval,
        "n_candles": len(klines),
        "price_now": round_price(price_ref),
        "poc": round_price(poc),
        "vah": round_price(vah_price),
        "val": round_price(val_price),
        "hvn_zones": _zones(hvn),
        "lvn_zones": _zones(lvn),
        "cr70_width_pct": round(cr70_width_pct, 2),
        "cr90_width_pct": round(cr90_width_pct, 2),
        "concentration_score": round(concentration, 1),
        "position_vs_poc": pos_poc,
        "position_vs_va": pos_va,
        "distribution": [
            {
                "price": round_price(low + (idx + 0.5) * bin_size),
                "volume_pct": round(value / total_volume * 100, 3),
            }
            for idx, value in enumerate(volumes)
            if value > 0
        ],
        "ts": ts,
    }


async def compute_flow_metrics(symbol: str, *, timeframe: str = DEFAULT_TIMEFRAME) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    pair = get_symbol_config(symbol)["binance"]
    limit = FLOW_LOOKBACKS.get(tf, FLOW_LOOKBACKS[DEFAULT_TIMEFRAME])

    try:
        raw_klines = await fetch_json(
            f"{binance.FAPI}/fapi/v1/klines",
            params={"symbol": pair, "interval": tf, "limit": limit},
        )
        klines = [
            {
                "o": float(item[1]),
                "h": float(item[2]),
                "l": float(item[3]),
                "c": float(item[4]),
                "v": float(item[5]),
                "quote_v": float(item[7]),
                "taker_buy_quote": float(item[10]),
            }
            for item in raw_klines
        ]
    except Exception as exc:
        return {"error": f"klines: {exc}"}

    buy_total = sum(item["taker_buy_quote"] for item in klines)
    sell_total = sum(item["quote_v"] - item["taker_buy_quote"] for item in klines)
    delta_total = buy_total - sell_total
    volume_total = buy_total + sell_total
    delta_pct = delta_total / volume_total if volume_total else None

    half = max(1, len(klines) // 2)
    cvd_first = sum(item["taker_buy_quote"] * 2 - item["quote_v"] for item in klines[:half])
    cvd_second = sum(item["taker_buy_quote"] * 2 - item["quote_v"] for item in klines[half:])
    if cvd_second > cvd_first * 1.2:
        cvd_trend = "上升（主动买入加速）"
    elif cvd_second < cvd_first * 0.8:
        cvd_trend = "下降（主动卖出加速）"
    else:
        cvd_trend = "震荡（多空均衡）"

    volume_base = sum(item["v"] for item in klines) or 1
    vwap = sum(((item["h"] + item["l"] + item["c"]) / 3) * item["v"] for item in klines) / volume_base

    atr_series: list[float] = []
    for idx in range(1, len(klines)):
        current = klines[idx]
        previous = klines[idx - 1]
        tr = max(
            current["h"] - current["l"],
            abs(current["h"] - previous["c"]),
            abs(current["l"] - previous["c"]),
        )
        atr_series.append(tr)
    atr_14 = sum(atr_series[-14:]) / min(14, len(atr_series)) if atr_series else None

    closes = [item["c"] for item in klines]
    returns = [math.log(closes[idx] / closes[idx - 1]) for idx in range(1, len(closes)) if closes[idx - 1] > 0]
    periods_per_year = {"5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
    realized_vol = None
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        realized_vol = math.sqrt(variance * periods_per_year.get(tf, 8760))

    spot_price = perp_price = None
    try:
        spot = await fetch_json("https://api.binance.com/api/v3/ticker/price", params={"symbol": pair})
        spot_price = float(spot.get("price", 0)) or None
    except Exception:
        pass
    try:
        premium = await fetch_json(f"{binance.FAPI}/fapi/v1/premiumIndex", params={"symbol": pair})
        perp_price = float(premium.get("markPrice", 0)) or None
    except Exception:
        pass

    ls_now = ls_prev = ls_change = None
    try:
        ls_rows = await fetch_json(
            f"{binance.FAPI}/futures/data/globalLongShortAccountRatio",
            params={"symbol": pair, "period": "1h", "limit": 2},
        )
        if isinstance(ls_rows, list) and len(ls_rows) >= 2:
            ls_now = float(ls_rows[-1].get("longShortRatio", 0) or 0) or None
            ls_prev = float(ls_rows[-2].get("longShortRatio", 0) or 0) or None
            if ls_now is not None and ls_prev:
                ls_change = (ls_now - ls_prev) / ls_prev
    except Exception:
        pass

    spot_vol = perp_vol = None
    try:
        spot_ticker, perp_ticker = await asyncio.gather(
            fetch_json("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": pair}),
            fetch_json(f"{binance.FAPI}/fapi/v1/ticker/24hr", params={"symbol": pair}),
        )
        spot_vol = float(spot_ticker.get("quoteVolume", 0) or 0) or None
        perp_vol = float(perp_ticker.get("quoteVolume", 0) or 0) or None
    except Exception:
        pass

    liq_long = liq_short = liq_ratio = None
    try:
        latest_gate = await gateio.get_open_interest_history(symbol, limit=1)
        if latest_gate:
            row = latest_gate[0]
            liq_long = float(row.get("long_liq_usd") or 0) or None
            liq_short = float(row.get("short_liq_usd") or 0) or None
            total = (liq_long or 0) + (liq_short or 0)
            liq_ratio = (liq_long or 0) / total if total else None
    except Exception:
        pass

    last_close = closes[-1] if closes else 0.0
    notes: list[str] = []
    if delta_pct is not None:
        if delta_pct > 0.05:
            notes.append("主动买盘明显占优")
        elif delta_pct < -0.05:
            notes.append("主动卖盘明显占优")
    if realized_vol is not None and realized_vol > 1.2:
        notes.append("年化波动率偏高，建议缩小仓位")
    if atr_14 and last_close and atr_14 / last_close > 0.03:
        notes.append("ATR 偏大，止损需要更宽")

    return {
        "symbol": pair,
        "interval": tf,
        "taker_buy_usd": round(buy_total, 2),
        "taker_sell_usd": round(sell_total, 2),
        "taker_delta_usd": round(delta_total, 2),
        "taker_delta_pct": round(delta_pct, 6) if delta_pct is not None else None,
        "cvd_24h": round(delta_total, 2),
        "cvd_trend": cvd_trend,
        "vwap_24h": round_price(vwap),
        "price_vs_vwap_pct": round((last_close / vwap - 1), 6) if vwap else None,
        "atr_14": round(atr_14, 2) if atr_14 is not None else None,
        "atr_pct": round((atr_14 / last_close), 6) if atr_14 and last_close else None,
        "realized_vol_24h": round(realized_vol, 6) if realized_vol is not None else None,
        "spot_price": round_price(spot_price) if spot_price is not None else None,
        "perp_price": round_price(perp_price) if perp_price is not None else None,
        "basis_pct": round((perp_price - spot_price) / spot_price, 6) if spot_price and perp_price else None,
        "ls_ratio_now": round(ls_now, 4) if ls_now is not None else None,
        "ls_ratio_1h_ago": round(ls_prev, 4) if ls_prev is not None else None,
        "ls_ratio_change": round(ls_change, 6) if ls_change is not None else None,
        "spot_vol_24h_usd": round(spot_vol, 2) if spot_vol is not None else None,
        "perp_vol_24h_usd": round(perp_vol, 2) if perp_vol is not None else None,
        "perp_to_spot_ratio": round(perp_vol / spot_vol, 4) if spot_vol and perp_vol else None,
        "liq_long_24h_usd": round(liq_long, 2) if liq_long is not None else None,
        "liq_short_24h_usd": round(liq_short, 2) if liq_short is not None else None,
        "liq_ratio": round(liq_ratio, 6) if liq_ratio is not None else None,
        "ts": int(time.time()),
        "notes": notes,
    }
