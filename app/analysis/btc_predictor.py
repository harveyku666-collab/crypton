"""BTC 量化短线预测器 — 融合自 btc-quant-predictor 技能

双引擎：15分钟多因子量化评分 + 综合投资分析
数据源：Binance 公开 API（免费无 Key，多端点 fallback）

增强功能：
  - 每个指标的详细信号说明（用户可理解的中文描述）
  - 止损 / 止盈自动计算
  - 24h 行情数据整合
  - 置信度分级解读
  - 支持多币种
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.market.sources import binance
from app.analysis.indicators import (
    compute_rsi,
    compute_macd,
    compute_bollinger,
    compute_momentum,
)

logger = logging.getLogger("bitinfo.analysis.btc_predictor")


async def predict_short_term(
    symbol: str = "BTC",
    interval: str = "15m",
    limit: int = 50,
) -> dict[str, Any]:
    """运行完整的量化短线预测。

    Returns structured result with signals, scores, stop-loss/take-profit,
    and 24h context for frontend visualization.
    """
    pair = f"{symbol}USDT"

    klines = await binance.get_klines(pair, interval, limit)
    if not klines:
        return {"error": f"无法获取 {pair} K线数据"}

    if len(klines) < 26:
        return {"error": f"K线数据不足（需要 >= 26 根，当前 {len(klines)} 根）"}

    ticker = await binance.get_ticker_24h(pair)

    closes = [float(k[4]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    current_price = closes[-1]

    signals = []
    bull_score = 0
    bear_score = 0

    rsi = compute_rsi(closes)
    if rsi is not None:
        if rsi < 30:
            bull_score += 2
            signals.append({
                "indicator": "RSI",
                "value": rsi,
                "display": f"{rsi:.1f}",
                "signal": "超卖区间 → 看涨反弹",
                "signal_en": "Oversold → Bullish bounce",
                "bullish": True,
                "weight": 2,
            })
        elif rsi > 70:
            bear_score += 2
            signals.append({
                "indicator": "RSI",
                "value": rsi,
                "display": f"{rsi:.1f}",
                "signal": "超买区间 → 看跌回调",
                "signal_en": "Overbought → Bearish pullback",
                "bullish": False,
                "weight": 2,
            })
        elif rsi >= 50:
            bull_score += 1
            signals.append({
                "indicator": "RSI",
                "value": rsi,
                "display": f"{rsi:.1f}",
                "signal": "偏多区间 → 温和看涨",
                "signal_en": "Above midline → Mildly bullish",
                "bullish": True,
                "weight": 1,
            })
        else:
            bear_score += 1
            signals.append({
                "indicator": "RSI",
                "value": rsi,
                "display": f"{rsi:.1f}",
                "signal": "偏空区间 → 温和看跌",
                "signal_en": "Below midline → Mildly bearish",
                "bullish": False,
                "weight": 1,
            })

    macd = compute_macd(closes)
    if macd and macd["histogram"] is not None:
        hist = macd["histogram"]
        macd_val = macd["macd"] or 0
        sig_val = macd["signal"] or 0
        if hist > 0 and macd_val > sig_val:
            bull_score += 2
            signals.append({
                "indicator": "MACD",
                "value": hist,
                "display": "金叉",
                "signal": "多头动能增强 → 看涨",
                "signal_en": "Golden cross → Bullish momentum",
                "bullish": True,
                "weight": 2,
            })
        elif hist < 0:
            bear_score += 2
            signals.append({
                "indicator": "MACD",
                "value": hist,
                "display": "死叉",
                "signal": "空头动能增强 → 看跌",
                "signal_en": "Death cross → Bearish momentum",
                "bullish": False,
                "weight": 2,
            })
        else:
            signals.append({
                "indicator": "MACD",
                "value": hist,
                "display": "震荡",
                "signal": "动能不明确 → 观望",
                "signal_en": "Consolidating → Wait",
                "bullish": None,
                "weight": 0,
            })

    boll = compute_bollinger(closes)
    if boll and boll["lower"] is not None:
        if current_price <= boll["lower"] * 1.01:
            bull_score += 2
            signals.append({
                "indicator": "BOLL",
                "value": current_price,
                "display": "触及下轨",
                "signal": "价格在布林下轨附近 → 反弹信号",
                "signal_en": "Near lower band → Bounce signal",
                "bullish": True,
                "weight": 2,
            })
        elif current_price >= (boll["upper"] or float("inf")) * 0.99:
            bear_score += 1
            signals.append({
                "indicator": "BOLL",
                "value": current_price,
                "display": "触及上轨",
                "signal": "价格在布林上轨附近 → 回调风险",
                "signal_en": "Near upper band → Pullback risk",
                "bullish": False,
                "weight": 1,
            })
        else:
            signals.append({
                "indicator": "BOLL",
                "value": current_price,
                "display": "中轨区间",
                "signal": "价格在中间区域 → 无明确方向",
                "signal_en": "Middle zone → Neutral",
                "bullish": None,
                "weight": 0,
            })

    avg_vol = sum(volumes[-10:]) / 10 if len(volumes) >= 10 else sum(volumes) / max(len(volumes), 1)
    vol_change = ((volumes[-1] - avg_vol) / avg_vol * 100) if avg_vol > 0 else 0
    momentum = compute_momentum(closes, 5)

    if abs(vol_change) > 20:
        if momentum is not None and momentum > 0:
            bull_score += 1
            signals.append({
                "indicator": "成交量",
                "value": vol_change,
                "display": f"+{vol_change:.0f}%",
                "signal": "放量上涨 → 多头确认",
                "signal_en": "High volume + up → Bullish confirmation",
                "bullish": True,
                "weight": 1,
            })
        else:
            bear_score += 1
            signals.append({
                "indicator": "成交量",
                "value": vol_change,
                "display": f"{vol_change:+.0f}%",
                "signal": "放量下跌 → 空头确认",
                "signal_en": "High volume + down → Bearish confirmation",
                "bullish": False,
                "weight": 1,
            })
    else:
        signals.append({
            "indicator": "成交量",
            "value": vol_change,
            "display": f"{vol_change:+.0f}%",
            "signal": "成交量正常 → 无特殊信号",
            "signal_en": "Normal volume → No signal",
            "bullish": None,
            "weight": 0,
        })

    if momentum is not None:
        if momentum > 1.5:
            bull_score += 1
            signals.append({
                "indicator": "动量",
                "value": momentum,
                "display": f"+{momentum:.2f}%",
                "signal": "强势上涨动量",
                "signal_en": "Strong upward momentum",
                "bullish": True,
                "weight": 1,
            })
        elif momentum < -1.5:
            bear_score += 1
            signals.append({
                "indicator": "动量",
                "value": momentum,
                "display": f"{momentum:.2f}%",
                "signal": "强势下跌动量",
                "signal_en": "Strong downward momentum",
                "bullish": False,
                "weight": 1,
            })
        else:
            signals.append({
                "indicator": "动量",
                "value": momentum,
                "display": f"{momentum:+.2f}%",
                "signal": "温和波动 → 无明确方向",
                "signal_en": "Moderate fluctuation → Neutral",
                "bullish": None,
                "weight": 0,
            })

    total = bull_score + bear_score
    confidence = (max(bull_score, bear_score) / total * 100) if total > 0 else 50
    confidence = min(confidence, 95)

    if bull_score > bear_score:
        direction = "UP"
    elif bear_score > bull_score:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    if confidence >= 70:
        confidence_label = "强信号"
        confidence_label_en = "Strong signal"
        confidence_note = "可执行，但仍需结合大周期判断"
    elif confidence >= 50:
        confidence_label = "参考信号"
        confidence_label_en = "Reference signal"
        confidence_note = "结合更大周期和市场情绪综合判断"
    else:
        confidence_label = "弱信号"
        confidence_label_en = "Weak signal"
        confidence_note = "观望为主，等待更明确信号"

    if direction == "UP":
        stop_loss = round(current_price * 0.997, 2)
        take_profit_1 = round(current_price * 1.005, 2)
        take_profit_2 = round(current_price * 1.008, 2)
        take_profit_3 = round(current_price * 1.015, 2)
    elif direction == "DOWN":
        stop_loss = round(current_price * 1.003, 2)
        take_profit_1 = round(current_price * 0.995, 2)
        take_profit_2 = round(current_price * 0.992, 2)
        take_profit_3 = round(current_price * 0.985, 2)
    else:
        stop_loss = None
        take_profit_1 = None
        take_profit_2 = None
        take_profit_3 = None

    now_utc8 = datetime.now(timezone(timedelta(hours=8)))
    next_period_min = (now_utc8.minute // 15 + 1) * 15
    if next_period_min >= 60:
        next_close = now_utc8.replace(
            hour=(now_utc8.hour + 1) % 24, minute=0, second=0, microsecond=0
        )
    else:
        next_close = now_utc8.replace(minute=next_period_min, second=0, microsecond=0)

    ticker_data = None
    if ticker and isinstance(ticker, dict):
        ticker_data = {
            "price": float(ticker.get("lastPrice", 0)),
            "high_24h": float(ticker.get("highPrice", 0)),
            "low_24h": float(ticker.get("lowPrice", 0)),
            "change_pct_24h": float(ticker.get("priceChangePercent", 0)),
            "volume_usd_24h": float(ticker.get("quoteVolume", 0)),
        }

    return {
        "symbol": symbol,
        "pair": pair,
        "interval": interval,
        "timestamp": now_utc8.isoformat(),
        "period": f"{now_utc8.strftime('%H:%M')} - {next_close.strftime('%H:%M')}",
        "current_price": current_price,
        "direction": direction,
        "direction_zh": {"UP": "看涨", "DOWN": "看跌", "NEUTRAL": "震荡"}[direction],
        "confidence": round(confidence, 1),
        "confidence_label": confidence_label,
        "confidence_label_en": confidence_label_en,
        "confidence_note": confidence_note,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "total_score": total,
        "signals": signals,
        "trade_plan": {
            "action": {
                "UP": "BUY (做多)",
                "DOWN": "SELL (做空)",
                "NEUTRAL": "WAIT (观望)",
            }[direction],
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "take_profit_3": take_profit_3,
            "risk_reward": round(
                abs(take_profit_2 - current_price) / abs(current_price - stop_loss), 2
            ) if stop_loss and take_profit_2 and abs(current_price - stop_loss) > 0 else None,
        },
        "indicators_raw": {
            "rsi": rsi,
            "macd": macd,
            "bollinger": boll,
            "momentum": momentum,
            "volume_change_pct": round(vol_change, 1),
        },
        "ticker_24h": ticker_data,
        "leverage_warning": "杠杆建议: 最多 2-3x，止损必须严格执行。急拉阶段不加杠杆，5x 以上 BTC 正常波动就能被洗。",
        "disclaimer": "⚠️ 仅供参考，不构成投资建议。短线预测适合做参考，长线决策应以综合投资分析为主。",
    }
