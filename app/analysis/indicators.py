"""Technical indicators — ported from btc-quant-predictor predict_15m.py.

Computes RSI, MACD, Bollinger Bands, momentum, and volume analysis
from raw OHLCV kline data.
"""

from __future__ import annotations

import math
from typing import Any

from app.market.sources import binance


def compute_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def compute_macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, float | None]:
    if len(closes) < slow + signal:
        return {"macd": None, "signal": None, "histogram": None}

    def ema(data: list[float], period: int) -> list[float]:
        k = 2 / (period + 1)
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(data[i] * k + result[-1] * (1 - k))
        return result

    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line[slow - 1 :], signal)

    m = macd_line[-1]
    s = signal_line[-1] if signal_line else 0
    return {"macd": round(m, 4), "signal": round(s, 4), "histogram": round(m - s, 4)}


def compute_bollinger(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict[str, float | None]:
    if len(closes) < period:
        return {"upper": None, "middle": None, "lower": None}
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    sd = math.sqrt(variance)
    return {
        "upper": round(mid + std_dev * sd, 2),
        "middle": round(mid, 2),
        "lower": round(mid - std_dev * sd, 2),
    }


def compute_momentum(closes: list[float], period: int = 10) -> float | None:
    if len(closes) < period + 1:
        return None
    return round((closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100, 4)


def analyze_klines(klines: list[list]) -> dict[str, Any]:
    """Full technical analysis on OHLCV kline data (Binance format).

    Each kline: [open_time, open, high, low, close, volume, ...]
    """
    if not klines or len(klines) < 26:
        return {"error": "Not enough data (need >= 26 candles)"}

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    current_price = closes[-1]

    rsi = compute_rsi(closes)
    macd = compute_macd(closes)
    boll = compute_bollinger(closes)
    momentum = compute_momentum(closes)

    avg_vol = sum(volumes[-10:]) / 10 if len(volumes) >= 10 else sum(volumes) / len(volumes)
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    bull_score = 0
    bear_score = 0

    if rsi is not None:
        if rsi < 30:
            bull_score += 2
        elif rsi > 70:
            bear_score += 2
        elif rsi >= 50:
            bull_score += 1
        else:
            bear_score += 1

    if macd["histogram"] is not None:
        if macd["histogram"] > 0 and (macd["macd"] or 0) > (macd["signal"] or 0):
            bull_score += 2
        elif macd["histogram"] < 0:
            bear_score += 2

    if boll["lower"] is not None:
        if current_price <= boll["lower"]:
            bull_score += 2
        elif current_price >= (boll["upper"] or float("inf")):
            bear_score += 1

    if momentum is not None:
        if momentum > 1.5:
            bull_score += 1
        elif momentum < -1.5:
            bear_score += 1

    price_change = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0
    if vol_ratio > 1.5:
        if price_change > 0:
            bull_score += 1
        else:
            bear_score += 1

    total = bull_score + bear_score
    if total == 0:
        direction, confidence = "NEUTRAL", 0.0
    elif bull_score > bear_score:
        direction = "UP"
        confidence = round(bull_score / total * 100, 1)
    elif bear_score > bull_score:
        direction = "DOWN"
        confidence = round(bear_score / total * 100, 1)
    else:
        direction, confidence = "NEUTRAL", 50.0

    return {
        "price": current_price,
        "direction": direction,
        "confidence": confidence,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "indicators": {
            "rsi": rsi,
            "macd": macd,
            "bollinger": boll,
            "momentum": momentum,
            "volume_ratio": round(vol_ratio, 2),
        },
    }


def compute_moving_averages(closes: list[float]) -> dict[str, Any]:
    if not closes:
        return {}

    current = closes[-1]
    ma7 = sum(closes[-7:]) / 7 if len(closes) >= 7 else None
    ma14 = sum(closes[-14:]) / 14 if len(closes) >= 14 else None
    ma30 = sum(closes[-30:]) / 30 if len(closes) >= 30 else None

    ma_analysis: dict[str, Any] = {}
    if ma7 is not None:
        ma_analysis["ma7"] = round(ma7, 2)
        ma_analysis["price_vs_ma7_pct"] = round((current - ma7) / ma7 * 100, 2)
    if ma14 is not None:
        ma_analysis["ma14"] = round(ma14, 2)
        ma_analysis["price_vs_ma14_pct"] = round((current - ma14) / ma14 * 100, 2)
    if ma30 is not None:
        ma_analysis["ma30"] = round(ma30, 2)
        ma_analysis["price_vs_ma30_pct"] = round((current - ma30) / ma30 * 100, 2)
    if ma7 is not None and ma14 is not None:
        ma_analysis["golden_cross"] = ma7 > ma14
    return ma_analysis


def build_technical_snapshot(
    symbol: str,
    interval: str,
    klines: list[list],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    closes = [float(k[4]) for k in klines]
    current = closes[-1]
    price_change_pct = round((closes[-1] - closes[-2]) / closes[-2] * 100, 2) if len(closes) >= 2 else 0.0
    indicators = analysis.get("indicators", {})
    rsi = indicators.get("rsi")
    direction = analysis.get("direction", "NEUTRAL")
    confidence = analysis.get("confidence", 0.0)

    trend = "sideways"
    if direction == "UP":
        trend = "strong_bullish" if confidence > 70 else "bullish"
    elif direction == "DOWN":
        trend = "strong_bearish" if confidence > 70 else "bearish"

    rsi_status = "neutral"
    if rsi is not None and rsi > 70:
        rsi_status = "overbought"
    elif rsi is not None and rsi < 30:
        rsi_status = "oversold"

    pair = f"{symbol}USDT"
    return {
        "symbol": symbol,
        "pair": pair,
        "interval": interval,
        "source": "Binance",
        "candle_count": len(klines),
        "close_time": int(klines[-1][6]) if klines and len(klines[-1]) > 6 else None,
        "price": current,
        "price_change_pct": price_change_pct,
        "rsi": rsi,
        "rsi_status": rsi_status,
        "macd": indicators.get("macd"),
        "bollinger": indicators.get("bollinger"),
        "momentum": indicators.get("momentum"),
        "volume_ratio": indicators.get("volume_ratio"),
        "moving_averages": compute_moving_averages(closes),
        "trend": trend,
        "direction": direction,
        "confidence": confidence,
        "bull_score": analysis.get("bull_score"),
        "bear_score": analysis.get("bear_score"),
        "analysis": analysis,
    }


async def analyze_symbol_technical(
    symbol: str = "BTC",
    interval: str = "4h",
    limit: int = 120,
) -> dict[str, Any]:
    normalized_symbol = symbol.upper()
    klines = await binance.get_klines(f"{normalized_symbol}USDT", interval, limit)
    if not klines:
        return {"error": f"No kline data for {normalized_symbol}"}

    analysis = analyze_klines(klines)
    if "error" in analysis:
        return analysis

    return build_technical_snapshot(normalized_symbol, interval, klines, analysis)
