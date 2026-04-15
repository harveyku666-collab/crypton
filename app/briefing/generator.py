"""Briefing generator — aggregates all data sources into structured reports.

Produces comprehensive briefings matching the OpenClaw cryptocurrency-market-live-briefing
output: prices with market cap, global stats, fear & greed with context, trending coins,
BTC technical analysis, DeFi yields, news highlights, cycles, and anomaly detection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.market.sources import desk3, binance, coingecko
from app.market.sources.defi_llama import scan_yields
from app.analysis.indicators import analyze_klines
from app.analysis.btc_predictor import predict_short_term

logger = logging.getLogger("bitinfo.briefing")

MAIN_SYMBOLS = ["BTC", "ETH", "SOL"]


async def _fetch_prices_with_marketcap() -> list[dict[str, Any]]:
    """Prices from Desk3 + market cap from CoinGecko."""
    raw_desk3, gecko_data = await asyncio.gather(
        desk3.get_prices("BTCUSDT,ETHUSDT,SOLUSDT"),
        coingecko.get_prices("bitcoin,ethereum,solana"),
        return_exceptions=True,
    )

    gecko_mc = {}
    if not isinstance(gecko_data, BaseException) and isinstance(gecko_data, dict):
        for coin_id, vals in gecko_data.items():
            sym = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}.get(coin_id)
            if sym and isinstance(vals, dict):
                gecko_mc[sym] = {
                    "market_cap": vals.get("usd_market_cap"),
                    "price_fallback": vals.get("usd"),
                    "change_fallback": vals.get("usd_24h_change"),
                }

    prices = []
    if not isinstance(raw_desk3, BaseException):
        for item in raw_desk3:
            sym = item.get("s", "").replace("USDT", "")
            if sym in MAIN_SYMBOLS:
                mc_info = gecko_mc.get(sym, {})
                prices.append({
                    "symbol": sym,
                    "price": float(item.get("c", 0)),
                    "change_24h_pct": round(float(item.get("P", 0)), 2),
                    "market_cap": mc_info.get("market_cap"),
                    "volume_24h": float(item.get("q", 0)),
                    "high_24h": float(item.get("h", 0)),
                    "low_24h": float(item.get("l", 0)),
                })
    if not prices:
        for coin_id, sym in [("bitcoin", "BTC"), ("ethereum", "ETH"), ("solana", "SOL")]:
            mc = gecko_mc.get(sym, {})
            if mc.get("price_fallback"):
                prices.append({
                    "symbol": sym,
                    "price": mc["price_fallback"],
                    "change_24h_pct": round(mc.get("change_fallback") or 0, 2),
                    "market_cap": mc.get("market_cap"),
                })
    return prices


async def _fetch_global_market() -> dict[str, Any]:
    """Global stats from CoinGecko + dominance from Desk3."""
    gecko, dom = await asyncio.gather(
        coingecko.get_global(),
        desk3.get_dominance(),
        return_exceptions=True,
    )
    result: dict[str, Any] = {}
    if not isinstance(gecko, BaseException) and gecko:
        gd = gecko if isinstance(gecko, dict) else {}
        result["total_market_cap"] = gd.get("total_market_cap", {}).get("usd")
        result["total_volume_24h"] = gd.get("total_volume", {}).get("usd")
        result["active_cryptocurrencies"] = gd.get("active_cryptocurrencies")
        result["market_cap_change_24h_pct"] = gd.get("market_cap_change_percentage_24h_usd")
        result["btc_dominance"] = f"{gd.get('market_cap_percentage', {}).get('btc', 0):.1f}%"
        result["eth_dominance"] = f"{gd.get('market_cap_percentage', {}).get('eth', 0):.1f}%"
    if not isinstance(dom, BaseException) and dom:
        if not result.get("btc_dominance") and dom.get("btc"):
            result["btc_dominance"] = f"{dom['btc']:.1f}%"
        if not result.get("eth_dominance") and dom.get("eth"):
            result["eth_dominance"] = f"{dom['eth']:.1f}%"
    return result


async def _fetch_fear_greed() -> dict[str, Any]:
    """Fear & Greed with historical context."""
    desk3_fg, alt_fg = await asyncio.gather(
        desk3.get_fear_greed(),
        coingecko.get_fear_greed(),
        return_exceptions=True,
    )
    fg = None
    if not isinstance(desk3_fg, BaseException) and desk3_fg:
        fg = desk3_fg
    if not fg and not isinstance(alt_fg, BaseException) and alt_fg:
        fg = {"now": {"score": alt_fg.get("value"), "name": alt_fg.get("value_classification")}}
    return fg or {}


async def _fetch_trending() -> list[dict[str, Any]]:
    """Trending from CoinGecko with price, change, and market cap."""
    gecko_trending = await coingecko.get_trending()
    if gecko_trending and isinstance(gecko_trending, list):
        results = []
        for item in gecko_trending[:10]:
            price_str = item.get("price_usd")
            price = None
            if price_str:
                try:
                    price = float(str(price_str).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    pass
            mc_str = item.get("market_cap")
            mc = None
            if mc_str:
                try:
                    mc = float(str(mc_str).replace("$", "").replace(",", ""))
                except (ValueError, TypeError):
                    pass
            results.append({
                "name": item.get("name", ""),
                "symbol": item.get("symbol", ""),
                "price": price,
                "change_24h_pct": item.get("price_change_24h"),
                "market_cap": mc,
                "market_cap_rank": item.get("market_cap_rank"),
            })
        return results
    raw = await desk3.get_trending(10)
    if raw:
        return [
            {
                "symbol": item.get("s", "").replace("USDT", ""),
                "price": float(item.get("c", 0)),
                "change_24h_pct": float(item.get("P", 0)),
                "volume": float(item.get("q", 0)),
            }
            for item in raw
            if item.get("s")
        ]
    return []


async def _fetch_btc_analysis() -> dict[str, Any]:
    """Comprehensive BTC technical analysis from Binance 4h klines."""
    klines = await binance.get_klines("BTCUSDT", "4h", 100)
    if not klines or len(klines) < 26:
        return {"error": "Not enough data"}

    analysis = analyze_klines(klines)
    closes = [float(k[4]) for k in klines]
    current = closes[-1]

    ma7 = sum(closes[-7:]) / 7 if len(closes) >= 7 else None
    ma14 = sum(closes[-14:]) / 14 if len(closes) >= 14 else None
    ma30 = sum(closes[-30:]) / 30 if len(closes) >= 30 else None

    ma_analysis: dict[str, Any] = {}
    if ma7 and ma14:
        ma_analysis["ma7"] = round(ma7, 2)
        ma_analysis["ma14"] = round(ma14, 2)
        if ma30:
            ma_analysis["ma30"] = round(ma30, 2)
        ma_analysis["price_vs_ma7_pct"] = round((current - ma7) / ma7 * 100, 2)
        ma_analysis["price_vs_ma14_pct"] = round((current - ma14) / ma14 * 100, 2)
        if ma30:
            ma_analysis["price_vs_ma30_pct"] = round((current - ma30) / ma30 * 100, 2)
        ma_analysis["golden_cross"] = ma7 > ma14

    trend = "sideways"
    rsi = analysis.get("indicators", {}).get("rsi")
    if analysis.get("direction") == "UP":
        trend = "strong_bullish" if (analysis.get("confidence", 0) > 70) else "bullish"
    elif analysis.get("direction") == "DOWN":
        trend = "strong_bearish" if (analysis.get("confidence", 0) > 70) else "bearish"

    rsi_status = "neutral"
    if rsi and rsi > 70:
        rsi_status = "overbought"
    elif rsi and rsi < 30:
        rsi_status = "oversold"

    return {
        "price": current,
        "rsi": rsi,
        "rsi_status": rsi_status,
        "macd": analysis.get("indicators", {}).get("macd"),
        "bollinger": analysis.get("indicators", {}).get("bollinger"),
        "momentum": analysis.get("indicators", {}).get("momentum"),
        "volume_ratio": analysis.get("indicators", {}).get("volume_ratio"),
        "moving_averages": ma_analysis,
        "trend": trend,
        "direction": analysis.get("direction"),
        "confidence": analysis.get("confidence"),
        "bull_score": analysis.get("bull_score"),
        "bear_score": analysis.get("bear_score"),
    }


async def _fetch_defi_top(n: int = 5) -> list[dict[str, Any]]:
    """Top DeFi yields with lower thresholds to actually get results."""
    yields = await scan_yields(min_tvl=100_000, min_apy=50, limit=n)
    if not yields:
        yields = await scan_yields(min_tvl=50_000, min_apy=10, limit=n)
    return [
        {
            "project": y.get("project"),
            "symbol": y.get("symbol"),
            "apy": round(y.get("apy", 0), 0),
            "apy_base": y.get("apy_base"),
            "apy_reward": y.get("apy_reward"),
            "tvl": y.get("tvl"),
            "chain": y.get("chain"),
        }
        for y in yields
    ]


async def _fetch_news_highlights(language: str, count: int = 8) -> list[dict[str, str]]:
    from app.news.fetcher import fetch_desk3_news
    news = await fetch_desk3_news("crypto", count, language)
    return [
        {
            "title": n["title"],
            "url": n.get("url", ""),
            "sentiment": n.get("sentiment", "neutral"),
            "importance": n.get("importance", "normal"),
        }
        for n in news
    ]


async def _fetch_cycles() -> dict[str, Any]:
    """Market cycle indicators from Desk3."""
    cycles, indicators, altseason = await asyncio.gather(
        desk3.get_cycles(),
        desk3.get_cycle_indicators(),
        desk3.get_altcoin_season(),
        return_exceptions=True,
    )
    result: dict[str, Any] = {}
    if not isinstance(cycles, BaseException) and cycles:
        result["cycles"] = cycles
    if not isinstance(indicators, BaseException) and indicators:
        result["cycle_indicators"] = indicators
    if not isinstance(altseason, BaseException) and altseason:
        result["altcoin_season"] = altseason
    return result


async def _fetch_funding_rates() -> list[dict[str, Any]]:
    """Top funding rates from Binance."""
    from app.market.sources.binance import scan_funding_rates
    try:
        rates = await scan_funding_rates(min_abs_rate=0.0001, min_volume=5_000_000)
        return [
            {
                "symbol": r.get("symbol", ""),
                "rate": round(r.get("rate_pct", 0), 4),
                "price": r.get("last_price", 0),
                "signal": r.get("signal", ""),
            }
            for r in rates[:5]
        ]
    except Exception:
        return []


async def _fetch_btc_short_prediction() -> dict[str, Any]:
    """BTC 15分钟量化短线预测 — 多因子评分。"""
    try:
        result = await predict_short_term("BTC", "15m", 50)
        if "error" in result:
            return {}
        return {
            "symbol": result.get("symbol"),
            "direction": result.get("direction"),
            "direction_zh": result.get("direction_zh"),
            "confidence": result.get("confidence"),
            "confidence_label": result.get("confidence_label"),
            "confidence_note": result.get("confidence_note"),
            "bull_score": result.get("bull_score"),
            "bear_score": result.get("bear_score"),
            "current_price": result.get("current_price"),
            "signals": result.get("signals", []),
            "trade_plan": result.get("trade_plan"),
            "period": result.get("period"),
            "interval": result.get("interval"),
            "leverage_warning": result.get("leverage_warning"),
        }
    except Exception as e:
        logger.warning("BTC short prediction failed: %s", e)
        return {}


async def generate_briefing(
    period: str = "daily",
    language: str = "zh",
) -> dict[str, Any]:
    """Generate a comprehensive market briefing."""
    title_map = {
        "zh": {"daily": "每日市场简报", "weekly": "每周市场简报", "monthly": "每月市场简报"},
        "en": {"daily": "Daily Market Briefing", "weekly": "Weekly Market Briefing", "monthly": "Monthly Market Briefing"},
    }
    titles = title_map.get(language, title_map["en"])
    title = titles.get(period, titles["daily"])
    now = datetime.now(timezone.utc).isoformat()

    tasks = {
        "prices": _fetch_prices_with_marketcap(),
        "global_market": _fetch_global_market(),
        "fear_greed": _fetch_fear_greed(),
        "trending": _fetch_trending(),
        "btc_analysis": _fetch_btc_analysis(),
        "btc_short_prediction": _fetch_btc_short_prediction(),
        "defi_top": _fetch_defi_top(5),
        "news_highlights": _fetch_news_highlights(language, 8),
        "cycles": _fetch_cycles(),
        "funding_rates": _fetch_funding_rates(),
    }

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    data: dict[str, Any] = {"title": title, "period": period, "language": language, "generated_at": now}

    for key, result in zip(tasks.keys(), results):
        if isinstance(result, BaseException):
            logger.warning("Briefing section '%s' failed: %s", key, result)
            data[key] = [] if key in ("prices", "trending", "defi_top", "news_highlights", "funding_rates") else {}
        else:
            data[key] = result

    # Anomaly detection
    fg = data.get("fear_greed", {})
    prices = data.get("prices", [])
    btc_price = next((p for p in prices if p["symbol"] == "BTC"), {})
    if fg and btc_price:
        now_fg = fg.get("now", fg)
        fg_val = now_fg.get("score") or now_fg.get("value")
        btc_change = btc_price.get("change_24h_pct", 0)
        if fg_val and int(fg_val) < 30 and btc_change > 3:
            data["anomaly"] = {
                "zh": f"⚠️ 有趣的现象：今天 BTC 涨了 {btc_change}%，但恐惧贪婪指数仍然 {fg_val}（极度恐惧），说明市场情绪还没跟上价格反弹。",
                "en": f"⚠️ Interesting: BTC is up {btc_change}% today, but Fear & Greed is still {fg_val} (Extreme Fear). Market sentiment hasn't caught up with the price bounce.",
            }.get(language, f"⚠️ BTC +{btc_change}%, but Fear & Greed still {fg_val}")

    data["content_text"] = _format_text(data, language)
    return data


def _format_text(data: dict[str, Any], lang: str) -> str:
    """Render structured briefing into rich text format."""
    lines: list[str] = []
    lines.append(f"{'=' * 50}")
    lines.append(f"  {data.get('title', '')}")
    lines.append(f"  {data.get('generated_at', '')}")
    lines.append(f"{'=' * 50}")

    # Prices
    prices = data.get("prices", [])
    if prices:
        lines.append(f"\n💰 实时价格" if lang == "zh" else "\n💰 Real-time Prices")
        lines.append(f"{'─' * 40}")
        for p in prices:
            sign = "🟢" if p["change_24h_pct"] >= 0 else "🔴"
            mc_str = f"  ${p['market_cap']/1e9:.0f}B" if p.get("market_cap") else ""
            lines.append(
                f"  {p['symbol']:<6} ${p['price']:>10,.0f}  {sign} {p['change_24h_pct']:+.1f}%{mc_str}"
            )

    # Global
    gm = data.get("global_market", {})
    if gm and any(gm.get(k) for k in ["total_market_cap", "btc_dominance"]):
        lines.append(f"\n📊 全球市场" if lang == "zh" else "\n📊 Global Market")
        lines.append(f"{'─' * 40}")
        if gm.get("total_market_cap"):
            cap_change = gm.get("market_cap_change_24h_pct")
            change_str = f" 🟢{cap_change:+.2f}%" if cap_change and cap_change >= 0 else f" 🔴{cap_change:+.2f}%" if cap_change else ""
            lines.append(f"  总市值    ${gm['total_market_cap']/1e12:.2f}T{change_str}")
        if gm.get("total_volume_24h"):
            lines.append(f"  24h成交量 ${gm['total_volume_24h']/1e9:.1f}B")
        if gm.get("btc_dominance"):
            lines.append(f"  BTC占比   {gm['btc_dominance']}")
        if gm.get("eth_dominance"):
            lines.append(f"  ETH占比   {gm['eth_dominance']}")
        if gm.get("active_cryptocurrencies"):
            lines.append(f"  活跃币种  {gm['active_cryptocurrencies']:,}")

    # Fear & Greed
    fg = data.get("fear_greed", {})
    if fg:
        now_fg = fg.get("now", fg)
        val = now_fg.get("score") or now_fg.get("value")
        label = now_fg.get("name") or now_fg.get("label", "")
        if val:
            lines.append(f"\n😱 恐惧贪婪指数：{val}/100 {label}")
            yesterday = fg.get("yesterday", {})
            if yesterday.get("score"):
                lines.append(f"  昨日: {yesterday['score']}/100 {yesterday.get('name', '')}")
            last_week = fg.get("lastWeek", {})
            if last_week.get("score"):
                lines.append(f"  上周: {last_week['score']}/100 {last_week.get('name', '')}")

    # Anomaly
    if data.get("anomaly"):
        lines.append(f"\n{data['anomaly']}")

    # Trending
    trending = data.get("trending", [])
    if trending:
        lines.append(f"\n🔥 当前趋势币种" if lang == "zh" else "\n🔥 Trending Coins")
        lines.append(f"{'─' * 40}")
        for i, t in enumerate(trending[:10], 1):
            name = t.get("name", "")
            sym = t.get("symbol", "")
            price = t.get("price")
            change = t.get("change_24h_pct")
            mc = t.get("market_cap")
            parts = [f"  {i}. {name} ({sym})" if name else f"  {i}. {sym}"]
            if price is not None:
                parts.append(f"${price:,.4f}" if price < 1 else f"${price:,.2f}")
            if change is not None:
                sign = "🟢" if change >= 0 else "🔴"
                parts.append(f"{sign}{change:+.1f}%")
            if mc is not None:
                if mc >= 1e9:
                    parts.append(f"MC:${mc/1e9:.1f}B")
                elif mc >= 1e6:
                    parts.append(f"MC:${mc/1e6:.0f}M")
            lines.append("  ".join(parts))

    # BTC Analysis
    ta = data.get("btc_analysis", {})
    if ta and not ta.get("error"):
        lines.append(f"\n📈 BTC 技术分析" if lang == "zh" else "\n📈 BTC Technical Analysis")
        lines.append(f"{'─' * 40}")
        rsi = ta.get("rsi")
        if rsi:
            status_map = {"overbought": "超买", "oversold": "超卖", "neutral": "中性"}
            status = status_map.get(ta.get("rsi_status", ""), ta.get("rsi_status", ""))
            icon = "🔴" if ta.get("rsi_status") == "overbought" else ("🟢" if ta.get("rsi_status") == "oversold" else "⚪")
            lines.append(f"  RSI(14): {rsi} {icon} {status}")
            if rsi > 70:
                lines.append(f"  • 市场可能过热，考虑减仓或观望")
            elif rsi < 30:
                lines.append(f"  • 市场超卖，可能是买入机会")

        ma = ta.get("moving_averages", {})
        if ma:
            cross = "🟢 金叉信号" if ma.get("golden_cross") else "🔴 死叉信号"
            lines.append(f"  均线分析：{cross}")
            for key, label in [("price_vs_ma7_pct", "Price vs MA7"), ("price_vs_ma14_pct", "Price vs MA14"), ("price_vs_ma30_pct", "Price vs MA30")]:
                if key in ma:
                    val = ma[key]
                    icon = "🟢" if val >= 0 else "🔴"
                    lines.append(f"  • {label}: {val:+.2f}% {icon}")

        trend_map = {"strong_bullish": "强势上涨 (Strong Bullish)", "bullish": "看涨", "strong_bearish": "强势下跌 (Strong Bearish)", "bearish": "看跌", "sideways": "横盘"}
        trend = trend_map.get(ta.get("trend", ""), ta.get("trend", ""))
        lines.append(f"  趋势：{trend}")

    # BTC Short-term Prediction
    sp = data.get("btc_short_prediction", {})
    if sp and sp.get("direction"):
        dir_emoji = {"UP": "📈", "DOWN": "📉", "NEUTRAL": "➡️"}
        lines.append(f"\n🎯 BTC 15分钟量化预测" if lang == "zh" else "\n🎯 BTC 15-min Quantitative Prediction")
        lines.append(f"{'─' * 40}")
        lines.append(f"  预测: {sp['direction_zh']} {dir_emoji.get(sp['direction'], '')}  置信度: {sp['confidence']}% ({sp['confidence_label']})")
        lines.append(f"  牛分: {sp['bull_score']} | 熊分: {sp['bear_score']}")
        for sig in sp.get("signals", []):
            icon = "✅" if sig.get("bullish") is True else ("❌" if sig.get("bullish") is False else "➖")
            lines.append(f"  {icon} {sig['indicator']}({sig['display']}) → {sig['signal']}")
        tp = sp.get("trade_plan", {})
        if tp and sp["direction"] != "NEUTRAL":
            lines.append(f"  方向: {tp.get('action', '')} | 止损: ${tp.get('stop_loss', 0):,.2f} | 止盈: ${tp.get('take_profit_2', 0):,.2f}")
        lines.append(f"  {sp.get('confidence_note', '')}")

    # Funding Rates
    funding = data.get("funding_rates", [])
    if funding:
        lines.append(f"\n💸 资金费率 Top 5" if lang == "zh" else "\n💸 Top Funding Rates")
        lines.append(f"{'─' * 40}")
        for f in funding:
            sign = "🟢" if f["rate"] >= 0 else "🔴"
            lines.append(f"  {f['symbol']:<10} {sign} {f['rate']:+.4f}%  ${f['price']:,.0f}")

    # DeFi
    defi = data.get("defi_top", [])
    if defi:
        lines.append(f"\n🌾 DeFi 收益 Top 5" if lang == "zh" else "\n🌾 DeFi Yield Top 5")
        lines.append(f"{'─' * 40}")
        lines.append(f"  {'#':<3} {'协议':<18} {'APY':>8} {'TVL':>10} {'链'}")
        for i, d in enumerate(defi, 1):
            tvl_str = f"${d['tvl']/1e6:.1f}M" if d.get("tvl") else "N/A"
            lines.append(f"  {i:<3} {d['project']:<18} {d['apy']:>7.0f}%  {tvl_str:>10} {d.get('chain', '')}")

    # News
    news = data.get("news_highlights", [])
    if news:
        lines.append(f"\n📰 新闻摘要" if lang == "zh" else "\n📰 News Highlights")
        lines.append(f"{'─' * 40}")
        for n in news:
            sentiment = n.get("sentiment", "neutral")
            importance = n.get("importance", "normal")
            s_icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(sentiment, "⚪")
            s_label = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}.get(sentiment, "中性")
            imp_mark = " ⭐" if importance == "important" else ""
            lines.append(f"  {s_icon} [{s_label}] {n['title']}{imp_mark}")

    # Cycles
    cycles = data.get("cycles", {})
    if cycles:
        cycle_data = cycles.get("cycles", {})
        indicators = cycles.get("cycle_indicators", {})
        if cycle_data or indicators:
            lines.append(f"\n🔄 市场周期" if lang == "zh" else "\n🔄 Market Cycles")
            lines.append(f"{'─' * 40}")
            if cycle_data.get("puellMultiple"):
                lines.append(f"  Puell Multiple: {cycle_data['puellMultiple']:.4f}")
            pi = cycle_data.get("piCycleTop", {})
            if pi:
                lines.append(f"  Pi Cycle Top: MA110=${pi.get('ma110', 0):,.0f}  MA350x2=${pi.get('ma350mu2', 0):,.0f}")
            likelihood = cycle_data.get("likelihood", {})
            if likelihood:
                total = likelihood.get("totalCount", 0)
                hold = likelihood.get("holdCount", 0)
                sell = likelihood.get("sellCount", 0)
                lines.append(f"  指标共识: {hold}/{total} 持有, {sell}/{total} 卖出")
            ind_list = indicators.get("indicators", [])
            if ind_list:
                lines.append(f"  关键指标:")
                for ind in ind_list[:5]:
                    name = ind.get("indicatorName", "")
                    val = ind.get("currentValue", "")
                    target = ind.get("targetValue", "")
                    change = ind.get("percentChange24h")
                    change_str = f" ({change:+.1f}%)" if change is not None else ""
                    lines.append(f"    {name}: {val} / {target}{change_str}")

    lines.append(f"\n{'=' * 50}")
    return "\n".join(lines)
