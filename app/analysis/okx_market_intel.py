"""Replicated OKX Market Intelligence Master workflow.

This module recreates the public-facing capability shape of the OKX
``market-intel`` skill using only read-only market and Orbit intelligence data
already integrated in this project.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from app.common.cache import cached
from app.market.sources import okx
from app.news import okx_orbit

LANGUAGE_MAP = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
}

TOPIC_RULES = [
    ("etf", "ETF / 机构", ("etf", "ibit", "etha", "黑岩", "贝莱德", "institutional", "custody")),
    ("macro", "宏观 / 美联储", ("fed", "fomc", "cpi", "ppi", "inflation", "rates", "宏观", "利率", "通胀")),
    ("regulation", "监管 / 政策", ("sec", "cftc", "regulation", "policy", "bill", "法案", "监管", "合规")),
    ("ai", "AI / Agent", ("ai", "agent", "gpu", "model", "inference", "算力", "模型", "智能体")),
    ("meme", "Meme / 社区", ("meme", "memecoin", "doge", "shib", "pepe", "bonk", "pumpfun", "fourmeme")),
    ("listing", "上币 / Launch", ("listing", "listed", "launchpool", "上线", "上币", "launch")),
    ("defi", "DeFi / 收益", ("defi", "tvl", "staking", "restaking", "yield", "收益", "质押")),
    ("security", "安全 / 黑客", ("hack", "exploit", "rug", "attack", "漏洞", "攻击", "安全")),
    ("stablecoin", "稳定币 / 支付", ("stablecoin", "usdt", "usdc", "rlusd", "支付", "稳定币")),
]

ORDERBOOK_BIAS_LABELS = {
    "bid_support": "买盘支撑",
    "ask_pressure": "卖压偏强",
    "balanced": "相对均衡",
}

FUNDING_BIAS_LABELS = {
    "crowded_longs": "多头拥挤",
    "crowded_shorts": "空头拥挤",
    "neutral": "中性",
}

SENTIMENT_LABELS = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "中性",
}

REGIME_LABELS = {
    "price_up_oi_up": "上涨增仓",
    "price_up_oi_down": "上涨减仓",
    "price_down_oi_up": "下跌增仓",
    "price_down_oi_down": "下跌减仓",
    "neutral": "中性结构",
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _labelize(mapping: dict[str, str], value: Any, fallback: str = "中性") -> str:
    key = str(value or "").strip().lower()
    if not key:
        return fallback
    return mapping.get(key, str(value))


def _normalize_language(language: str | None) -> str:
    key = (language or "zh-CN").strip().lower().replace("_", "-")
    return LANGUAGE_MAP.get(key, "zh-CN" if key.startswith("zh") else "en-US")


def _normalize_symbol(symbol: str | None) -> str:
    raw = (symbol or "BTC").strip().upper()
    if "-" in raw:
        return raw
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    return cleaned or "BTC"


def _resolve_inst_id(symbol: str | None, market_type: str = "SWAP") -> str:
    normalized = _normalize_symbol(symbol)
    if "-" in normalized:
        return normalized
    return f"{normalized}-USDT" if market_type == "SPOT" else f"{normalized}-USDT-SWAP"


def _base_symbol(symbol: str | None, market_type: str = "SWAP") -> str:
    normalized = _normalize_symbol(symbol)
    return normalized.split("-")[0] if "-" in normalized else normalized


def _normalize_market_type(symbol: str | None, market_type: str | None) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    if normalized_symbol.endswith("-SWAP"):
        return "SWAP"
    return "SPOT" if str(market_type or "").upper() == "SPOT" else "SWAP"


def _sentiment_period(timeframe: str) -> str:
    resolved = str(timeframe or "1H").upper()
    if resolved == "4H":
        return "4h"
    if resolved == "1D":
        return "24h"
    return "1h"


def _article_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "summary", "excerpt", "content")
    ).lower()


def _topic_counts(items: list[dict[str, Any]]) -> tuple[Counter[str], dict[str, list[str]]]:
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = {key: [] for key, _, _ in TOPIC_RULES}
    for item in items:
        text = _article_text(item)
        title = str(item.get("title") or "").strip()
        matched = False
        for key, _label, keywords in TOPIC_RULES:
            if any(keyword in text for keyword in keywords):
                counts[key] += 1
                if title and len(samples[key]) < 2:
                    samples[key].append(title)
                matched = True
        if not matched and title:
            counts["general"] += 1
    return counts, samples


def _compare_topics(
    recent_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    recent_counts, recent_samples = _topic_counts(recent_items)
    previous_counts, _ = _topic_counts(previous_items)
    topics: list[dict[str, Any]] = []
    for key, label, _keywords in TOPIC_RULES:
        current = recent_counts.get(key, 0)
        previous = previous_counts.get(key, 0)
        if current == 0 and previous == 0:
            continue
        delta = current - previous
        topics.append({
            "key": key,
            "topic": label,
            "count": current,
            "prev_count": previous,
            "delta": delta,
            "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
            "sample_titles": recent_samples.get(key, []),
        })
    topics.sort(key=lambda item: (item["delta"], item["count"]), reverse=True)
    return topics[:limit]


def _sentiment_distribution(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item.get("sentiment") or "neutral") for item in items)
    total = sum(counts.values()) or 1
    bullish = counts.get("bullish", 0)
    bearish = counts.get("bearish", 0)
    neutral = counts.get("neutral", 0)
    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "total": bullish + bearish + neutral,
        "bullish_ratio": bullish / total,
        "bearish_ratio": bearish / total,
        "neutral_ratio": neutral / total,
    }


def _associated_coins(items: list[dict[str, Any]], *, fallback: str | None = None) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in items:
        for coin in item.get("coins") or []:
            symbol = str(coin or "").strip().upper()
            if symbol:
                counts[symbol] += 1
    if not counts and fallback:
        counts[fallback.upper()] = 1
    return [
        {"symbol": symbol, "count": count}
        for symbol, count in counts.most_common(6)
    ]


def _first_numeric(values: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(values, dict):
        return None
    for key in keys:
        for actual_key, value in values.items():
            if actual_key.lower() == key.lower():
                number = _safe_float(value)
                if number is not None:
                    return number
    for key in keys:
        for actual_key, value in values.items():
            if key.lower() in actual_key.lower():
                number = _safe_float(value)
                if number is not None:
                    return number
    for value in values.values():
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _technical_validation(
    market: dict[str, Any],
    sentiment_item: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = (market.get("snapshot") or {}) if isinstance(market, dict) else {}
    diagnosis = (market.get("diagnosis") or {}) if isinstance(market, dict) else {}
    indicator_summary = (market.get("indicator_summary") or {}) if isinstance(market, dict) else {}

    rsi_item = indicator_summary.get("rsi") if isinstance(indicator_summary, dict) else None
    macd_item = indicator_summary.get("macd") if isinstance(indicator_summary, dict) else None
    bb_item = indicator_summary.get("bb") if isinstance(indicator_summary, dict) else None

    rsi = _first_numeric((rsi_item or {}).get("values"), "rsi")
    macd = _first_numeric((macd_item or {}).get("values"), "macd")
    signal = _first_numeric((macd_item or {}).get("values"), "signal")
    histogram = _first_numeric((macd_item or {}).get("values"), "histogram", "hist", "macdh")
    bb_upper = _first_numeric((bb_item or {}).get("values"), "upper", "upperband")
    bb_middle = _first_numeric((bb_item or {}).get("values"), "middle", "mid", "basis")
    bb_lower = _first_numeric((bb_item or {}).get("values"), "lower", "lowerband")
    last_price = _safe_float((snapshot or {}).get("last"))

    if rsi is None:
        rsi_status = "unknown"
    elif rsi >= 70:
        rsi_status = "overbought"
    elif rsi <= 30:
        rsi_status = "oversold"
    elif rsi >= 55:
        rsi_status = "bullish"
    elif rsi <= 45:
        rsi_status = "bearish"
    else:
        rsi_status = "neutral"

    macd_bias = "neutral"
    hist_value = histogram
    if hist_value is None and macd is not None and signal is not None:
        hist_value = macd - signal
    if hist_value is not None:
        macd_bias = "bullish" if hist_value > 0 else "bearish" if hist_value < 0 else "neutral"

    bb_position = "unknown"
    if last_price is not None and bb_upper is not None and bb_lower is not None:
        if last_price >= bb_upper:
            bb_position = "above_upper"
        elif last_price <= bb_lower:
            bb_position = "below_lower"
        elif bb_middle is not None and last_price >= bb_middle:
            bb_position = "upper_half"
        else:
            bb_position = "lower_half"

    bullish_ratio = _safe_float((sentiment_item or {}).get("bullish_ratio")) or 0.0
    bearish_ratio = _safe_float((sentiment_item or {}).get("bearish_ratio")) or 0.0
    price_change = _safe_float((snapshot or {}).get("price_change_pct_24h")) or 0.0
    oi_delta = _safe_float((snapshot or {}).get("oi_delta_pct")) or 0.0

    score = 50.0
    score += max(-8.0, min(8.0, price_change / 2))
    score += max(-8.0, min(8.0, oi_delta / 2))
    score += (bullish_ratio - bearish_ratio) * 16
    if diagnosis.get("orderbook_bias") == "bid_support":
        score += 6
    elif diagnosis.get("orderbook_bias") == "ask_pressure":
        score -= 6
    if diagnosis.get("funding_bias") == "crowded_longs":
        score -= 4
    elif diagnosis.get("funding_bias") == "crowded_shorts":
        score += 3
    if rsi_status == "bullish":
        score += 5
    elif rsi_status == "bearish":
        score -= 5
    elif rsi_status == "oversold":
        score += 3
    elif rsi_status == "overbought":
        score -= 3
    if macd_bias == "bullish":
        score += 5
    elif macd_bias == "bearish":
        score -= 5

    score = max(0.0, min(100.0, score))
    if score >= 62:
        bias = "bullish"
        bias_label = "偏多"
    elif score <= 38:
        bias = "bearish"
        bias_label = "偏空"
    else:
        bias = "neutral"
        bias_label = "中性"

    return {
        "score": round(score, 1),
        "bias": bias,
        "bias_label": bias_label,
        "rsi": {"value": rsi, "status": rsi_status},
        "macd": {"value": macd, "signal": signal, "histogram": hist_value, "bias": macd_bias},
        "bollinger": {
            "upper": bb_upper,
            "middle": bb_middle,
            "lower": bb_lower,
            "position": bb_position,
        },
        "price_oi_regime": diagnosis.get("price_oi_regime"),
        "price_oi_regime_label": _labelize(REGIME_LABELS, diagnosis.get("price_oi_regime"), "中性结构"),
        "orderbook_bias": diagnosis.get("orderbook_bias"),
        "orderbook_bias_label": _labelize(ORDERBOOK_BIAS_LABELS, diagnosis.get("orderbook_bias"), "暂无信号"),
        "funding_bias": diagnosis.get("funding_bias"),
        "funding_bias_label": _labelize(FUNDING_BIAS_LABELS, diagnosis.get("funding_bias"), "暂无信号"),
    }


def _daily_takeaways(
    market: dict[str, Any],
    sentiment_item: dict[str, Any] | None,
    topics: list[dict[str, Any]],
    technicals: dict[str, Any],
) -> list[str]:
    snapshot = (market.get("snapshot") or {}) if isinstance(market, dict) else {}
    diagnosis = (market.get("diagnosis") or {}) if isinstance(market, dict) else {}
    takeaways: list[str] = []

    takeaways.append(str(diagnosis.get("price_oi_comment") or "价格与持仓尚未形成明确的单边结构。"))

    mention_count = (sentiment_item or {}).get("mention_count")
    label = _labelize(SENTIMENT_LABELS, (sentiment_item or {}).get("label"), "中性")
    if mention_count is None:
        takeaways.append("当前情绪样本还不够稳定，建议把盘口、Funding 和新闻标题一起交叉看。")
    else:
        takeaways.append(f"社交情绪标签为 {label}，当前提及量 {int(mention_count)}，适合与盘口和 OI 一起交叉确认。")

    rising_topic = next((topic for topic in topics if topic.get("delta", 0) > 0), None)
    if rising_topic:
        takeaways.append(
            f"最近 24h 讨论上升最快的话题是「{rising_topic['topic']}」，出现 {rising_topic['count']} 次，较前一窗口变化 {rising_topic['delta']:+d}。"
        )

    funding_rate = _safe_float(snapshot.get("funding_rate"))
    if funding_rate is not None:
        takeaways.append(
            f"资金费率为 {funding_rate * 100:.4f}% ，当前拥挤方向是 {_labelize(FUNDING_BIAS_LABELS, diagnosis.get('funding_bias'))}。"
        )

    if technicals.get("bias_label"):
        takeaways.append(
            f"技术验证得分 {technicals['score']} / 100，综合判断为 {technicals['bias_label']}。"
        )

    return takeaways[:4]


def _keyword_summary(
    query: str,
    sentiment: dict[str, Any],
    top_topics: list[dict[str, Any]],
    coins: list[dict[str, Any]],
) -> str:
    topic_line = "、".join(topic["topic"] for topic in top_topics[:3]) or "暂无明显主题"
    coin_line = "、".join(item["symbol"] for item in coins[:4]) or "暂无明确关联币种"
    return (
        f"围绕「{query}」的结果中，主导情绪为 "
        f"{'偏多' if sentiment.get('bullish_ratio', 0) > sentiment.get('bearish_ratio', 0) else '偏空' if sentiment.get('bearish_ratio', 0) > sentiment.get('bullish_ratio', 0) else '中性'}，"
        f"高频主题集中在 {topic_line}，关联币种以 {coin_line} 为主。"
    )


def _build_alerts(
    market: dict[str, Any],
    sentiment_item: dict[str, Any] | None,
    recent_coin_news: list[dict[str, Any]],
    previous_coin_news: list[dict[str, Any]],
    important_news: list[dict[str, Any]],
    topic_board: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot = (market.get("snapshot") or {}) if isinstance(market, dict) else {}
    diagnosis = (market.get("diagnosis") or {}) if isinstance(market, dict) else {}
    trend = (sentiment_item or {}).get("trend") or []
    alerts: list[dict[str, Any]] = []

    if trend:
        latest_mentions = int(trend[0].get("mention_count") or 0)
        previous_mentions = [int(point.get("mention_count") or 0) for point in trend[1:] if point.get("mention_count") is not None]
        baseline = sum(previous_mentions) / len(previous_mentions) if previous_mentions else 0
        if latest_mentions >= 20 and baseline > 0 and latest_mentions >= baseline * 1.6:
            alerts.append({
                "id": "mention-spike",
                "severity": "high",
                "title": "讨论量异常放大",
                "summary": f"最新提及数 {latest_mentions}，较前序均值 {baseline:.1f} 提升明显，叙事可能正在出圈。",
                "evidence": [
                    f"当前提及量 {latest_mentions}",
                    f"趋势基线 {baseline:.1f}",
                    f"情绪标签 {(sentiment_item or {}).get('label') or 'neutral'}",
                ],
            })

    price_change = _safe_float(snapshot.get("price_change_pct_24h")) or 0.0
    bullish_ratio = _safe_float((sentiment_item or {}).get("bullish_ratio")) or 0.0
    bearish_ratio = _safe_float((sentiment_item or {}).get("bearish_ratio")) or 0.0
    if price_change <= -2 and bullish_ratio >= 0.55:
        alerts.append({
            "id": "bullish-divergence",
            "severity": "medium",
            "title": "价格走弱但情绪仍偏多",
            "summary": "市场价格和社交情绪出现背离，常见于抄底争议阶段，需要更多成交确认。",
            "evidence": [
                f"24h 涨跌 {price_change:.2f}%",
                f"Bullish ratio {bullish_ratio:.2%}",
                f"OI 变化 {(_safe_float(snapshot.get('oi_delta_pct')) or 0.0):.2f}%",
            ],
        })
    elif price_change >= 2 and bearish_ratio >= 0.35:
        alerts.append({
            "id": "bearish-divergence",
            "severity": "medium",
            "title": "价格上行但舆论开始谨慎",
            "summary": "价格上升同时 bearish 讨论没有同步退潮，说明追高情绪并不稳固。",
                "evidence": [
                    f"24h 涨跌 {price_change:.2f}%",
                    f"Bearish ratio {bearish_ratio:.2%}",
                    f"盘口偏向 {_labelize(ORDERBOOK_BIAS_LABELS, diagnosis.get('orderbook_bias'))}",
                ],
            })

    oi_delta = _safe_float(snapshot.get("oi_delta_pct")) or 0.0
    if abs(oi_delta) >= 4.5 or diagnosis.get("funding_bias") in {"crowded_longs", "crowded_shorts"}:
        alerts.append({
            "id": "leverage-crowding",
            "severity": "high" if abs(oi_delta) >= 7 else "medium",
            "title": "杠杆拥挤度上升",
            "summary": "Funding 与 OI 同步提示仓位正在堆积，波动放大的概率提升。",
                "evidence": [
                    f"OI 变化 {oi_delta:.2f}%",
                    f"Funding 偏向 {_labelize(FUNDING_BIAS_LABELS, diagnosis.get('funding_bias'))}",
                    f"价格/OI 结构 {_labelize(REGIME_LABELS, diagnosis.get('price_oi_regime'), '中性结构')}",
                ],
            })

    emerging = [topic for topic in topic_board if topic.get("delta", 0) >= 2 and topic.get("count", 0) >= 3]
    if emerging:
        top = emerging[0]
        alerts.append({
            "id": f"topic-{top['key']}",
            "severity": "medium",
            "title": f"新叙事抬头：{top['topic']}",
            "summary": "近 24h 话题频率较上一窗口明显升温，适合和新闻详情联动观察。",
            "evidence": [
                f"最近窗口 {top['count']} 次",
                f"上一窗口 {top['prev_count']} 次",
                f"变化 {top['delta']:+d}",
            ],
        })

    if len(important_news) >= 4:
        alerts.append({
            "id": "important-news-cluster",
            "severity": "low",
            "title": "高重要性新闻密集出现",
            "summary": "高重要性快讯集中出现时，市场会更容易进入事件驱动阶段。",
            "evidence": [
                f"重要新闻数量 {len(important_news)}",
                f"近 24h 币种相关新闻 {len(recent_coin_news)}",
                f"上一窗口相关新闻 {len(previous_coin_news)}",
            ],
        })

    if diagnosis.get("orderbook_bias") in {"bid_support", "ask_pressure"}:
        direction = diagnosis.get("orderbook_bias")
        alerts.append({
            "id": f"orderbook-{direction}",
            "severity": "low",
            "title": "盘口结构提醒",
            "summary": "当前前排挂单已经出现明显偏向，适合结合价格波动判断是吸筹还是抛压。",
            "evidence": [
                f"盘口信号 {_labelize(ORDERBOOK_BIAS_LABELS, direction)}",
                f"Funding {_labelize(FUNDING_BIAS_LABELS, diagnosis.get('funding_bias'))}",
                    f"价格/OI 结构 {_labelize(REGIME_LABELS, diagnosis.get('price_oi_regime'), '中性结构')}",
                ],
            })

    alerts.sort(key=lambda item: {"high": 3, "medium": 2, "low": 1}.get(item["severity"], 0), reverse=True)
    return {
        "count": len(alerts),
        "items": alerts[:5],
        "trend": trend,
        "window_hours": 24,
        "new_topics": [topic for topic in topic_board if topic.get("delta", 0) > 0][:4],
    }


async def _fetch_pair_snapshot(symbol: str, preferred_market_type: str = "SWAP") -> dict[str, Any]:
    candidates = [_resolve_inst_id(symbol, preferred_market_type)]
    fallback = _resolve_inst_id(symbol, "SPOT" if preferred_market_type == "SWAP" else "SWAP")
    if fallback not in candidates:
        candidates.append(fallback)

    for inst_id in candidates:
        try:
            ticker = await okx.get_ticker(inst_id)
        except Exception:
            ticker = None
        if not isinstance(ticker, dict):
            continue
        last = _safe_float(ticker.get("last"))
        open_24h = _safe_float(ticker.get("open24h"))
        change_pct = None
        if last is not None and open_24h not in {None, 0}:
            change_pct = (last - open_24h) / open_24h * 100
        return {
            "inst_id": inst_id,
            "symbol": symbol,
            "last": last,
            "change_pct_24h": change_pct,
            "volume_24h_quote": _safe_float(ticker.get("volCcy24h")),
        }
    return {"inst_id": candidates[0], "symbol": symbol, "last": None, "change_pct_24h": None, "volume_24h_quote": None}


async def _build_focus_pairs(
    base_symbol: str,
    market: dict[str, Any],
    ranking_items: list[dict[str, Any]],
    *,
    market_type: str,
) -> list[dict[str, Any]]:
    selected_symbols: list[str] = [base_symbol]
    for item in ranking_items:
        symbol = str(item.get("symbol") or "").upper()
        if symbol and symbol not in selected_symbols:
            selected_symbols.append(symbol)
        if len(selected_symbols) >= 4:
            break

    pairs = await asyncio.gather(*[
        _fetch_pair_snapshot(symbol, market_type)
        for symbol in selected_symbols
    ], return_exceptions=True)

    diagnosis = (market.get("diagnosis") or {}) if isinstance(market, dict) else {}
    results: list[dict[str, Any]] = []
    for idx, pair in enumerate(pairs):
        if isinstance(pair, Exception):
            continue
        if idx == 0:
            pair.update({
                "label": "当前主标的",
                "note": diagnosis.get("price_oi_comment") or "当前选择的重点观察标的。",
                "kind": "primary",
            })
        else:
            source = ranking_items[idx - 1] if idx - 1 < len(ranking_items) else {}
            pair.update({
                "label": "热度联动",
                "note": (
                    f"情绪标签 {_labelize(SENTIMENT_LABELS, source.get('label'))} · 提及 {source.get('mention_count')}"
                    if source.get("mention_count") is not None
                    else f"情绪标签 {_labelize(SENTIMENT_LABELS, source.get('label'))} · 暂无稳定提及样本"
                ),
                "kind": "watch",
            })
        results.append(pair)
    return results


@cached(ttl=60, prefix="okx_market_intel_master")
async def build_market_intel_master(
    *,
    symbol: str = "BTC",
    market_type: str = "SWAP",
    timeframe: str = "1H",
    language: str = "zh-CN",
    keyword: str | None = None,
    platform: str | None = None,
    news_limit: int = 8,
    important_limit: int = 6,
    search_limit: int = 12,
    ranking_limit: int = 8,
) -> dict[str, Any]:
    resolved_market_type = _normalize_market_type(symbol, market_type)
    inst_id = _resolve_inst_id(symbol, resolved_market_type)
    base_symbol = _base_symbol(symbol, resolved_market_type)
    resolved_language = _normalize_language(language)
    resolved_timeframe = str(timeframe or "1H").upper()
    query = (keyword or base_symbol).strip()[:80] or base_symbol
    now_ms = int(time.time() * 1000)
    window_ms = 24 * 60 * 60 * 1000
    errors: list[str] = []

    tasks = await asyncio.gather(
        okx.build_market_intelligence(
            inst_id,
            candle_bar=resolved_timeframe,
            oi_bar=resolved_timeframe,
        ),
        okx_orbit.get_news_by_coin(
            coins=base_symbol,
            platform=platform,
            language=resolved_language,
            detail_lvl="summary",
            limit=news_limit,
        ),
        okx_orbit.get_latest_news(
            importance="high",
            platform=platform,
            language=resolved_language,
            detail_lvl="summary",
            limit=important_limit,
        ),
        okx_orbit.get_coin_sentiment(
            coins=base_symbol,
            period=_sentiment_period(resolved_timeframe),
            trend_points=12,
        ),
        okx_orbit.get_sentiment_ranking(
            period=_sentiment_period(resolved_timeframe),
            sort_by="hot",
            limit=ranking_limit,
        ),
        okx_orbit.search_news(
            keyword=query,
            platform=platform,
            language=resolved_language,
            detail_lvl="summary",
            sort_by="relevant",
            limit=search_limit,
        ),
        okx_orbit.get_news_by_coin(
            coins=base_symbol,
            platform=platform,
            language=resolved_language,
            detail_lvl="summary",
            begin=now_ms - window_ms,
            end=now_ms,
            limit=min(max(news_limit * 2, 12), 50),
        ),
        okx_orbit.get_news_by_coin(
            coins=base_symbol,
            platform=platform,
            language=resolved_language,
            detail_lvl="summary",
            begin=now_ms - 2 * window_ms,
            end=now_ms - window_ms,
            limit=min(max(news_limit * 2, 12), 50),
        ),
        okx_orbit.get_news_platforms(),
        return_exceptions=True,
    )

    def _resolve_result(value: Any, label: str, default: Any) -> Any:
        if isinstance(value, Exception):
            detail = str(value).strip() or value.__class__.__name__
            errors.append(f"{label}: {detail}")
            return default
        return value

    market = _resolve_result(tasks[0], "market intelligence", {"error": "market intelligence unavailable"})
    coin_news = _resolve_result(tasks[1], "coin news", {"items": [], "count": 0})
    important_news = _resolve_result(tasks[2], "important news", {"items": [], "count": 0})
    coin_sentiment = _resolve_result(tasks[3], "coin sentiment", {"items": [], "count": 0})
    sentiment_ranking = _resolve_result(tasks[4], "sentiment ranking", {"items": [], "count": 0})
    keyword_research_raw = _resolve_result(tasks[5], "keyword research", {"items": [], "count": 0})
    recent_window_news = _resolve_result(tasks[6], "recent coin window", {"items": [], "count": 0})
    previous_window_news = _resolve_result(tasks[7], "previous coin window", {"items": [], "count": 0})
    platform_list = _resolve_result(tasks[8], "platform list", {"items": [], "count": 0})

    coin_news_items = list(coin_news.get("items") or [])
    important_news_items = list(important_news.get("items") or [])
    recent_coin_news = list(recent_window_news.get("items") or [])
    previous_coin_news = list(previous_window_news.get("items") or [])
    sentiment_item = (coin_sentiment.get("items") or [None])[0]
    ranking_items = list(sentiment_ranking.get("items") or [])
    keyword_articles = list(keyword_research_raw.get("items") or [])

    topic_board = _compare_topics(recent_coin_news or coin_news_items, previous_coin_news)
    technicals = _technical_validation(market if isinstance(market, dict) else {}, sentiment_item)
    focus_pairs = await _build_focus_pairs(
        base_symbol,
        market if isinstance(market, dict) else {},
        ranking_items,
        market_type=resolved_market_type,
    )
    alerts = _build_alerts(
        market if isinstance(market, dict) else {},
        sentiment_item,
        recent_coin_news,
        previous_coin_news,
        important_news_items,
        topic_board,
    )
    keyword_topics = _compare_topics(keyword_articles, [])
    keyword_sentiment = _sentiment_distribution(keyword_articles)
    related_coins = _associated_coins(keyword_articles, fallback=base_symbol)
    daily_takeaways = _daily_takeaways(
        market if isinstance(market, dict) else {},
        sentiment_item,
        topic_board,
        technicals,
    )

    pulse_score = technicals.get("score", 50.0)
    pulse_label = technicals.get("bias_label", "中性")
    headline = f"{base_symbol} 当前进入 {pulse_label} 情报阶段"
    news_count = len(recent_coin_news or coin_news_items)
    news_line = f"{news_count} 条相关新闻" if news_count else "暂无稳定新闻样本"
    alert_count = len(alerts.get("items") or [])
    alert_line = f"{alert_count} 个异动信号" if alert_count else "异动规则暂未触发"
    summary = (
        f"{base_symbol} 的价格/OI 结构为 "
        f"{_labelize(REGIME_LABELS, (market.get('diagnosis') or {}).get('price_oi_regime'), '中性结构')}，"
        f"当前 {news_line}，{alert_line}，适合先看结构，再看叙事。"
    )

    return {
        "skill": "market-intel",
        "version": "1.0",
        "generated_at": now_ms,
        "inst_id": inst_id,
        "symbol": base_symbol,
        "market_type": resolved_market_type,
        "timeframe": resolved_timeframe,
        "language": resolved_language,
        "query": query,
        "platform": platform,
        "available_platforms": list(platform_list.get("items") or []),
        "status": "partial" if errors else "ok",
        "errors": errors,
        "daily_brief": {
            "pulse_score": pulse_score,
            "bias": technicals.get("bias"),
            "bias_label": pulse_label,
            "headline": headline,
            "summary": summary,
            "takeaways": daily_takeaways,
            "market_pulse": {
                "last": (market.get("snapshot") or {}).get("last") if isinstance(market, dict) else None,
                "price_change_pct_24h": (market.get("snapshot") or {}).get("price_change_pct_24h") if isinstance(market, dict) else None,
                "oi_delta_pct": (market.get("snapshot") or {}).get("oi_delta_pct") if isinstance(market, dict) else None,
                "oi_usd": (market.get("snapshot") or {}).get("oi_usd") if isinstance(market, dict) else None,
                "funding_rate": (market.get("snapshot") or {}).get("funding_rate") if isinstance(market, dict) else None,
                "funding_bias": (market.get("diagnosis") or {}).get("funding_bias") if isinstance(market, dict) else None,
                "funding_bias_label": _labelize(FUNDING_BIAS_LABELS, (market.get("diagnosis") or {}).get("funding_bias"), "暂无信号") if isinstance(market, dict) else "暂无信号",
                "orderbook_bias": (market.get("diagnosis") or {}).get("orderbook_bias") if isinstance(market, dict) else None,
                "orderbook_bias_label": _labelize(ORDERBOOK_BIAS_LABELS, (market.get("diagnosis") or {}).get("orderbook_bias"), "暂无信号") if isinstance(market, dict) else "暂无信号",
                "price_oi_regime": (market.get("diagnosis") or {}).get("price_oi_regime") if isinstance(market, dict) else None,
                "price_oi_regime_label": _labelize(REGIME_LABELS, (market.get("diagnosis") or {}).get("price_oi_regime"), "中性结构") if isinstance(market, dict) else "中性结构",
                "mention_count": (sentiment_item or {}).get("mention_count"),
                "bullish_ratio": (sentiment_item or {}).get("bullish_ratio"),
                "bearish_ratio": (sentiment_item or {}).get("bearish_ratio"),
            },
            "focus_pairs": focus_pairs,
            "hot_topics": topic_board,
            "important_news": important_news_items,
            "coin_news": coin_news_items,
            "sentiment": sentiment_item,
            "technical_validation": technicals,
            "market": market,
        },
        "anomaly_alerts": alerts,
        "keyword_research": {
            "query": query,
            "article_count": keyword_research_raw.get("count") or len(keyword_articles),
            "summary": _keyword_summary(query, keyword_sentiment, keyword_topics, related_coins),
            "sentiment_distribution": keyword_sentiment,
            "associated_coins": related_coins,
            "top_topics": keyword_topics,
            "technical_validation": technicals,
            "articles": keyword_articles,
        },
    }
