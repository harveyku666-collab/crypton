"""OI Signal Engine with multi-timeframe scoring and richer market context."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.analysis.oi_context import (
    compute_chip_zone,
    compute_flow_metrics,
    format_price,
    get_orderbook_context,
    get_symbol_config,
    get_timeframe_preset,
    normalize_chip_interval,
    normalize_timeframe,
    round_price,
)
from app.common.cache import cached
from app.common.http_client import fetch_json
from app.market.sources import binance, bitget, bybit, gateio, okx

logger = logging.getLogger("bitinfo.analysis.oi_signal")

HISTORY_WINDOWS = {
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


@dataclass
class ExchangeOI:
    exchange: str
    price: float | None = None
    oi_usd: float | None = None
    oi_coin: float | None = None
    funding: float | None = None
    volume_24h_usd: float | None = None
    long_short_ratio: float | None = None
    error: str | None = None


async def _fetch_binance(symbol: str) -> ExchangeOI:
    snap = ExchangeOI(exchange="binance")
    try:
        pair = get_symbol_config(symbol)["binance"]
        oi_data, ticker, fr, ls_rows = await asyncio.gather(
            binance.get_open_interest(pair),
            binance.get_futures_ticker(symbol),
            binance.get_funding_rate(symbol),
            binance.get_long_short_ratio(pair, "1h", 1),
            return_exceptions=True,
        )
        if isinstance(oi_data, dict):
            snap.oi_usd = oi_data.get("open_interest_usd")
            snap.oi_coin = oi_data.get("open_interest_coin")
            snap.price = oi_data.get("mark_price")
        if isinstance(ticker, dict):
            snap.price = snap.price or float(ticker.get("lastPrice", 0)) or None
            snap.volume_24h_usd = float(ticker.get("quoteVolume", 0)) or None
        if isinstance(fr, dict):
            rate = fr.get("lastFundingRate")
            snap.funding = float(rate) if rate is not None else None
        if isinstance(ls_rows, list) and ls_rows:
            snap.long_short_ratio = ls_rows[-1].get("long_short_ratio")
    except Exception as exc:
        snap.error = str(exc)
    return snap


async def _fetch_gateio(symbol: str) -> ExchangeOI:
    snap = ExchangeOI(exchange="gate.io")
    try:
        data = await gateio.get_open_interest(symbol)
        if data:
            snap.oi_usd = data.get("open_interest_usd")
            snap.price = data.get("mark_price")
            fr = data.get("funding_rate")
            snap.funding = float(fr) if fr is not None else None
            vol = data.get("volume_24h_usd")
            snap.volume_24h_usd = float(vol) if vol else None
    except Exception as exc:
        snap.error = str(exc)
    return snap


async def _fetch_okx(symbol: str) -> ExchangeOI:
    snap = ExchangeOI(exchange="okx")
    pair = get_symbol_config(symbol)["okx"]
    try:
        oi_data, ticker_data, fr_data, ls_rows = await asyncio.gather(
            fetch_json(
                "https://www.okx.com/api/v5/public/open-interest",
                params={"instType": "SWAP", "instId": pair},
            ),
            fetch_json("https://www.okx.com/api/v5/market/ticker", params={"instId": pair}),
            fetch_json("https://www.okx.com/api/v5/public/funding-rate", params={"instId": pair}),
            okx.get_long_short_ratio(symbol, limit=1),
            return_exceptions=True,
        )
        if isinstance(oi_data, dict) and oi_data.get("code") == "0":
            rows = oi_data.get("data") or []
            row = rows[0] if rows else {}
            oi_usd = row.get("oiUsd")
            snap.oi_usd = float(oi_usd) if oi_usd is not None else None
        if isinstance(ticker_data, dict) and ticker_data.get("code") == "0":
            rows = ticker_data.get("data") or []
            row = rows[0] if rows else {}
            snap.price = float(row.get("last", 0)) or None
            base_volume = float(row.get("volCcy24h", 0) or 0)
            snap.volume_24h_usd = base_volume * snap.price if snap.price and base_volume else None
        if isinstance(fr_data, dict) and fr_data.get("code") == "0":
            rows = fr_data.get("data") or []
            row = rows[0] if rows else {}
            rate = row.get("fundingRate")
            snap.funding = float(rate) if rate is not None else None
        if isinstance(ls_rows, list) and ls_rows:
            snap.long_short_ratio = ls_rows[-1].get("long_short_ratio")
    except Exception as exc:
        snap.error = str(exc)
    return snap


async def _fetch_bybit(symbol: str) -> ExchangeOI:
    snap = ExchangeOI(exchange="bybit")
    pair = get_symbol_config(symbol)["bybit"]
    try:
        ticker_data, oi_data, ls_data = await asyncio.gather(
            fetch_json(
                "https://api.bybit.com/v5/market/tickers",
                params={"category": "linear", "symbol": pair},
            ),
            fetch_json(
                "https://api.bybit.com/v5/market/open-interest",
                params={"category": "linear", "symbol": pair, "intervalTime": "5min", "limit": 1},
            ),
            fetch_json(
                "https://api.bybit.com/v5/market/account-ratio",
                params={"category": "linear", "symbol": pair, "period": "5min", "limit": 1},
            ),
            return_exceptions=True,
        )
        if isinstance(ticker_data, dict) and ticker_data.get("retCode") == 0:
            rows = ticker_data.get("result", {}).get("list") or []
            row = rows[0] if rows else {}
            snap.price = float(row.get("lastPrice", 0)) or None
            snap.funding = float(row.get("fundingRate", 0)) if row.get("fundingRate") is not None else None
            snap.volume_24h_usd = float(row.get("turnover24h", 0)) or None
        if isinstance(oi_data, dict) and oi_data.get("retCode") == 0:
            rows = oi_data.get("result", {}).get("list") or []
            row = rows[0] if rows else {}
            snap.oi_coin = float(row.get("openInterest", 0)) or None
            if snap.price and snap.oi_coin:
                snap.oi_usd = snap.oi_coin * snap.price
        if isinstance(ls_data, dict) and ls_data.get("retCode") == 0:
            rows = ls_data.get("result", {}).get("list") or []
            row = rows[0] if rows else {}
            buy_ratio = float(row.get("buyRatio", 0) or 0)
            sell_ratio = float(row.get("sellRatio", 0) or 0)
            snap.long_short_ratio = buy_ratio / sell_ratio if sell_ratio else None
    except Exception as exc:
        snap.error = str(exc)
    return snap


async def _fetch_bitget(symbol: str) -> ExchangeOI:
    snap = ExchangeOI(exchange="bitget")
    pair = f"{symbol.upper()}USDT"
    try:
        oi_data, ticker_data, fr_data = await asyncio.gather(
            bitget.get_open_interest(symbol),
            fetch_json(
                "https://api.bitget.com/api/v2/mix/market/ticker",
                params={"symbol": pair, "productType": "USDT-FUTURES"},
            ),
            fetch_json(
                "https://api.bitget.com/api/v2/mix/market/current-fund-rate",
                params={"symbol": pair, "productType": "USDT-FUTURES"},
            ),
            return_exceptions=True,
        )
        if isinstance(ticker_data, dict) and ticker_data.get("code") == "00000":
            rows = ticker_data.get("data") or []
            row = rows[0] if isinstance(rows, list) and rows else {}
            snap.price = float(row.get("lastPr", 0)) or None
            snap.volume_24h_usd = float(row.get("usdtVolume", 0)) or None
        if isinstance(oi_data, dict):
            snap.oi_coin = oi_data.get("open_interest_coin")
            if snap.price and snap.oi_coin:
                snap.oi_usd = snap.oi_coin * snap.price
        if isinstance(fr_data, dict) and fr_data.get("code") == "00000":
            payload = fr_data.get("data")
            if isinstance(payload, list) and payload:
                rate = payload[0].get("fundingRate")
            elif isinstance(payload, dict):
                rate = payload.get("fundingRate")
            else:
                rate = None
            snap.funding = float(rate) if rate is not None else None
    except Exception as exc:
        snap.error = str(exc)
    return snap


async def fetch_all_exchanges(symbol: str = "BTC") -> list[ExchangeOI]:
    results = await asyncio.gather(
        _fetch_binance(symbol),
        _fetch_gateio(symbol),
        _fetch_okx(symbol),
        _fetch_bybit(symbol),
        _fetch_bitget(symbol),
        return_exceptions=True,
    )
    return [item for item in results if isinstance(item, ExchangeOI)]


_history: dict[str, list[dict[str, float | int]]] = {}


def _push_history(symbol: str, price: float, oi: float, volume: float) -> None:
    key = symbol.upper()
    _history.setdefault(key, []).append(
        {"ts": int(time.time()), "price": price, "oi": oi, "volume": volume}
    )
    cutoff = time.time() - 48 * 3600
    _history[key] = [sample for sample in _history[key] if float(sample["ts"]) >= cutoff]


def _get_history_context(symbol: str) -> dict[str, float]:
    key = symbol.upper()
    samples = _history.get(key, [])
    if len(samples) < 2:
        return {}
    now = time.time()

    def nearest(delta: int) -> dict[str, float | int]:
        target = now - delta
        return min(samples, key=lambda sample: abs(float(sample["ts"]) - target))

    out: dict[str, float] = {}
    for label, delta in HISTORY_WINDOWS.items():
        sample = nearest(delta)
        out[f"price_{label}"] = float(sample["price"])
        out[f"oi_{label}"] = float(sample["oi"])
    last20 = samples[-20:]
    if len(last20) >= 3:
        out["volume_ma20"] = sum(float(sample["volume"]) for sample in last20) / len(last20)
    return out


def _pct_change(current: float, previous: float) -> float:
    return (current - previous) / previous if previous else 0.0


def _round_pct(value: float) -> float:
    return round(value * 100, 2)


async def score_oi_signal(
    exchanges: list[ExchangeOI],
    symbol: str = "BTC",
    *,
    timeframe: str = "1h",
    chip_interval: str | None = None,
) -> dict[str, Any]:
    tf = normalize_timeframe(timeframe)
    chip_tf = normalize_chip_interval(chip_interval, tf)
    cfg = get_timeframe_preset(tf)

    valid = [item for item in exchanges if item.error is None and item.oi_usd and item.oi_usd > 0]
    if not valid:
        return {"error": "No valid exchange data", "score": 50, "verdict": "数据不足"}

    total_oi = sum(item.oi_usd or 0 for item in valid)
    price_pool = [(item.price, item.oi_usd) for item in valid if item.price and item.oi_usd]
    price = (
        sum((p or 0) * (w or 0) for p, w in price_pool) / sum((w or 0) for _, w in price_pool)
        if price_pool
        else 0.0
    )

    funding_pool = [(item.funding, item.oi_usd) for item in valid if item.funding is not None and item.oi_usd]
    funding_weighted = (
        sum((rate or 0) * (weight or 0) for rate, weight in funding_pool) / sum((weight or 0) for _, weight in funding_pool)
        if funding_pool
        else 0.0
    )
    volume_total = sum(item.volume_24h_usd or 0 for item in valid)
    ls_pool = [item.long_short_ratio for item in valid if item.long_short_ratio]
    long_short_ratio = sum(ls_pool) / len(ls_pool) if ls_pool else None

    history = _get_history_context(symbol)
    changes = {
        label: {
            "price": _pct_change(price, history.get(f"price_{label}", price)),
            "oi": _pct_change(total_oi, history.get(f"oi_{label}", total_oi)),
        }
        for label in HISTORY_WINDOWS
    }
    volume_ma_ratio = volume_total / history["volume_ma20"] if history.get("volume_ma20") else 1.0

    _push_history(symbol, price, total_oi, volume_total)

    selected_price_change = changes[tf]["price"]
    selected_oi_change = changes[tf]["oi"]
    score = 50
    notes: list[str] = []
    signals: list[dict[str, Any]] = []

    same_dir_up = selected_price_change > 0 and selected_oi_change > 0
    same_dir_down = selected_price_change < 0 and selected_oi_change > 0
    fake_rally = selected_price_change > 0 and selected_oi_change < 0
    capitulation = selected_price_change < 0 and selected_oi_change < 0

    quadrant_weight = int(cfg["w_quadrant"])
    if same_dir_up:
        score += quadrant_weight
        quadrant = {"id": "A", "label": "健康上涨", "desc": "新多头进场，趋势性上涨", "bias": "bullish"}
    elif same_dir_down:
        score -= quadrant_weight
        quadrant = {"id": "C", "label": "健康下跌", "desc": "新空头进场，趋势性下跌", "bias": "bearish"}
    elif fake_rally:
        score -= max(5, quadrant_weight // 6)
        quadrant = {"id": "B", "label": "空头回补", "desc": "空头回补推涨，动能衰竭，警惕反转", "bias": "caution"}
    elif capitulation:
        score += max(10, quadrant_weight // 3)
        quadrant = {"id": "D", "label": "多头投降", "desc": "多头止损离场，跌势末端，警惕反弹", "bias": "reversal"}
    else:
        quadrant = {"id": "N", "label": "中性", "desc": "无明显方向", "bias": "neutral"}

    if abs(selected_price_change) >= float(cfg["dP_strong"]):
        notes.append(f"{tf} 价格波动已达强信号阈值 ({selected_price_change * 100:+.2f}%)")
    if abs(selected_oi_change) >= float(cfg["dOI_strong"]):
        notes.append(f"{tf} OI 变化已达强信号阈值 ({selected_oi_change * 100:+.2f}%)")

    funding_weight = int(cfg["w_funding"])
    if funding_weighted > 0.001:
        score -= funding_weight
        notes.append(f"Funding 过热 ({funding_weighted * 100:.3f}%)，多头成本偏高")
    elif funding_weighted > 0.0005:
        score -= max(5, funding_weight // 3)
        notes.append(f"Funding 偏热 ({funding_weighted * 100:.3f}%)")
    elif funding_weighted < -0.0005:
        score += max(10, funding_weight - 5)
        notes.append(f"Funding 极度悲观 ({funding_weighted * 100:.3f}%)，反弹概率升")
    else:
        notes.append("Funding 处于健康区间")

    volume_weight = int(cfg["w_vol"])
    if volume_ma_ratio > float(cfg["vol_hot"]):
        score += volume_weight if selected_price_change > 0 else -volume_weight
        notes.append(f"放量 {volume_ma_ratio:.2f}x，趋势确认")
    elif volume_ma_ratio < float(cfg["vol_low"]):
        score += -min(10, volume_weight) if selected_price_change > 0 else min(10, volume_weight)
        notes.append("缩量，趋势确认度偏弱")

    ls_weight = int(cfg["w_ls"])
    if long_short_ratio is not None:
        if long_short_ratio > 3:
            score -= ls_weight
            notes.append(f"多空比 {long_short_ratio:.2f} 极度偏多（反向信号）")
        elif long_short_ratio < 0.33:
            score += ls_weight
            notes.append(f"多空比 {long_short_ratio:.2f} 极度偏空（反向信号）")
        elif long_short_ratio > 2.5:
            score -= max(3, ls_weight // 2)
        elif long_short_ratio < 0.5:
            score += max(3, ls_weight // 2)

    dP_24h = changes["1d"]["price"]
    dOI_4h = changes["4h"]["oi"]
    dP_4h = changes["4h"]["price"]
    dOI_24h = changes["1d"]["oi"]

    def add_signal(
        *,
        signal_type: str,
        label: str,
        icon: str,
        desc: str,
        active: bool,
        score_delta: int = 0,
    ) -> None:
        nonlocal score
        if active:
            score += score_delta
            signals.append({"type": signal_type, "label": label, "icon": icon, "desc": desc})
        else:
            signals.append({"type": signal_type, "label": label, "icon": "✅", "desc": "未触发", "active": False})

    add_signal(
        signal_type="top_divergence",
        label="顶部背离",
        icon="🚨",
        desc="价涨仓减 + Funding 过热，警惕瀑布式回落",
        active=dP_24h > max(0.03, float(cfg["dP_extreme"])) and dOI_24h < -0.01 and funding_weighted > 0.001,
        score_delta=-15,
    )
    add_signal(
        signal_type="bottom_divergence",
        label="底部背离",
        icon="🟢",
        desc="多头投降完成，反弹临近",
        active=dP_24h < -max(0.03, float(cfg["dP_extreme"])) and dOI_24h < -0.05 and funding_weighted < -0.0005,
        score_delta=15,
    )
    add_signal(
        signal_type="squeeze",
        label="挤压预警",
        icon="⚡",
        desc="OI 急升 + 价格窄幅，波动可能即将放大",
        active=dOI_4h > float(cfg["dOI_squeeze"]) and abs(dP_4h) < max(0.01, float(cfg["dP_strong"]) / 2),
    )
    add_signal(
        signal_type="overheating",
        label="过热警报",
        icon="🔥",
        desc="Funding > 0.15%，建议减仓控制风险",
        active=funding_weighted > 0.0015,
    )
    add_signal(
        signal_type="oi_surge",
        label="持仓剧变",
        icon="📢",
        desc=f"24h OI 变化达到 {dOI_24h * 100:.1f}%，大行情在即",
        active=abs(dOI_24h) > float(cfg["dOI_surge"]),
    )

    book, chip, flow = await asyncio.gather(
        get_orderbook_context(symbol),
        compute_chip_zone(symbol, interval=chip_tf, price_now=price),
        compute_flow_metrics(symbol, timeframe=tf),
        return_exceptions=True,
    )

    if isinstance(book, Exception):
        book = {"error": str(book)}
    if isinstance(chip, Exception):
        chip = {"error": str(chip)}
    if isinstance(flow, Exception):
        flow = {"error": str(flow)}

    if isinstance(book, dict) and not book.get("error"):
        imbalance_1pct = book.get("imbalance_1pct")
        imbalance_5pct = book.get("imbalance_5pct")
        if imbalance_1pct is not None:
            if imbalance_1pct > 0.15:
                score += 8
                notes.append(f"盘口买强 {imbalance_1pct * 100:+.1f}%（±1%）")
            elif imbalance_1pct < -0.15:
                score -= 8
                notes.append(f"盘口卖强 {imbalance_1pct * 100:+.1f}%（±1%）")
        if imbalance_5pct is not None and abs(imbalance_5pct) > 0.25:
            notes.append(f"±5% 深度严重失衡 {imbalance_5pct * 100:+.1f}%")
        bid_walls = book.get("top_bid_walls") or []
        ask_walls = book.get("top_ask_walls") or []
        if bid_walls:
            signals.append(
                {
                    "type": "bid_wall",
                    "label": "买墙",
                    "icon": "🧱",
                    "desc": f"最大买墙 ${format_price(bid_walls[0]['price'])}（{bid_walls[0]['ex']} ${bid_walls[0]['usd'] / 1e6:.1f}M）",
                }
            )
        if ask_walls:
            signals.append(
                {
                    "type": "ask_wall",
                    "label": "卖墙",
                    "icon": "🧱",
                    "desc": f"最大卖墙 ${format_price(ask_walls[0]['price'])}（{ask_walls[0]['ex']} ${ask_walls[0]['usd'] / 1e6:.1f}M）",
                }
            )

    if isinstance(chip, dict) and not chip.get("error"):
        poc = float(chip.get("poc", 0) or 0)
        vah = float(chip.get("vah", 0) or 0)
        val = float(chip.get("val", 0) or 0)
        price_now = float(chip.get("price_now", 0) or 0)
        concentration = float(chip.get("concentration_score", 0) or 0)
        if price_now and poc:
            dist_poc = (price_now - poc) / poc
            if price_now > vah > 0:
                score -= 5
                notes.append(f"价格位于 VA 上方（超买区，POC ${format_price(poc)}）")
            elif price_now < val and val > 0:
                score += 5
                notes.append(f"价格位于 VA 下方（超卖区，POC ${format_price(poc)}）")
            else:
                notes.append(f"价格位于 VA 内部（POC ${format_price(poc)}）")
            if abs(dist_poc) < 0.003:
                notes.append("贴近 POC，价格易出现磁吸震荡")
        if concentration > 70:
            signals.append(
                {
                    "type": "chip_concentration",
                    "label": "筹码集中",
                    "icon": "🎯",
                    "desc": f"筹码高度集中，CR70 宽度 {chip.get('cr70_width_pct')}%，突破后趋势可能放大",
                }
            )
        elif concentration < 30:
            notes.append(f"筹码较分散，CR70 宽度 {chip.get('cr70_width_pct')}%")

    if isinstance(flow, dict) and not flow.get("error"):
        taker_delta_pct = flow.get("taker_delta_pct")
        if taker_delta_pct is not None:
            if taker_delta_pct > 0.05:
                score += 8
                notes.append(f"主动买盘占优 {taker_delta_pct * 100:+.2f}%")
            elif taker_delta_pct < -0.05:
                score -= 8
                notes.append(f"主动卖盘占优 {taker_delta_pct * 100:+.2f}%")

        cvd_trend = flow.get("cvd_trend") or ""
        if "上升" in cvd_trend and selected_price_change <= 0:
            score += 5
            notes.append("CVD 上行但价格未跟，疑似底部吸筹")
        elif "下降" in cvd_trend and selected_price_change >= 0:
            score -= 5
            notes.append("CVD 下行但价格未跌，疑似顶部派发")

        basis_pct = flow.get("basis_pct")
        if basis_pct is not None:
            if basis_pct > 0.003:
                score -= 5
                notes.append(f"期现基差 {basis_pct * 100:+.2f}% 过热")
            elif basis_pct < -0.002:
                score += 5
                notes.append(f"期现基差 {basis_pct * 100:+.2f}% 深度贴水")

        price_vs_vwap_pct = flow.get("price_vs_vwap_pct")
        if price_vs_vwap_pct is not None:
            if price_vs_vwap_pct > 0.02:
                score -= 2
                notes.append(f"价格高于 VWAP {price_vs_vwap_pct * 100:+.2f}%（回归压力）")
            elif price_vs_vwap_pct < -0.02:
                score += 2
                notes.append(f"价格低于 VWAP {price_vs_vwap_pct * 100:+.2f}%（回归支撑）")

        perp_to_spot_ratio = flow.get("perp_to_spot_ratio")
        if perp_to_spot_ratio is not None:
            if perp_to_spot_ratio > 5:
                score -= 5
                notes.append(f"合约/现货成交 {perp_to_spot_ratio:.1f}x，投机偏热")
            elif perp_to_spot_ratio < 1.5:
                notes.append(f"合约/现货成交 {perp_to_spot_ratio:.1f}x，现货主导")

        liq_ratio = flow.get("liq_ratio")
        if liq_ratio is not None:
            if liq_ratio > 0.75:
                score += 8
                signals.append(
                    {
                        "type": "liquidation_long",
                        "label": "清算失衡",
                        "icon": "💥",
                        "desc": f"多单爆仓占 {liq_ratio * 100:.0f}%，踩踏完成后反弹概率上升",
                    }
                )
            elif liq_ratio < 0.25:
                score -= 8
                signals.append(
                    {
                        "type": "liquidation_short",
                        "label": "清算失衡",
                        "icon": "💥",
                        "desc": f"空单爆仓占 {(1 - liq_ratio) * 100:.0f}%，轧空后警惕回落",
                    }
                )

        for note in flow.get("notes") or []:
            if note not in notes:
                notes.append(note)

    history_samples = len(_history.get(symbol.upper(), []))
    if history_samples < 5:
        notes.append("历史样本偏少，短周期变化率仍在建立中")

    score = max(0, min(100, score))
    if score >= 80:
        verdict = "强烈看多"
    elif score >= 60:
        verdict = "偏多"
    elif score >= 41:
        verdict = "中性观望"
    elif score >= 21:
        verdict = "偏空"
    else:
        verdict = "强烈看空"

    if score >= 70:
        direction = "做多"
        leverage = "≤3x" if tf in {"4h", "1d"} else "≤5x"
    elif score <= 30:
        direction = "做空"
        leverage = "≤3x" if tf in {"4h", "1d"} else "≤5x"
    else:
        direction = "观望"
        leverage = "-"

    return {
        "symbol": symbol.upper(),
        "timeframe": tf,
        "chip_interval": chip_tf,
        "timestamp": int(time.time()),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "score": score,
        "verdict": verdict,
        "quadrant": quadrant,
        "direction": direction,
        "leverage": leverage,
        "timeframe_meta": {
            "selected": tf,
            "chip_interval": chip_tf,
            "thresholds": {
                "price_strong_pct": round(float(cfg["dP_strong"]) * 100, 2),
                "oi_strong_pct": round(float(cfg["dOI_strong"]) * 100, 2),
                "volume_hot_x": float(cfg["vol_hot"]),
            },
        },
        "snapshot": {
            "price": round_price(price),
            "oi_total_usd": round(total_oi, 2),
            "funding_weighted": round(funding_weighted * 100, 5),
            "volume_24h_usd": round(volume_total, 2),
            "long_short_ratio": round(long_short_ratio, 4) if long_short_ratio is not None else None,
            "dP_selected": _round_pct(selected_price_change),
            "dOI_selected": _round_pct(selected_oi_change),
            "selected_label": tf,
            "dP_5m": _round_pct(changes["5m"]["price"]),
            "dP_15m": _round_pct(changes["15m"]["price"]),
            "dP_1h": _round_pct(changes["1h"]["price"]),
            "dP_4h": _round_pct(changes["4h"]["price"]),
            "dP_24h": _round_pct(changes["1d"]["price"]),
            "dOI_5m": _round_pct(changes["5m"]["oi"]),
            "dOI_15m": _round_pct(changes["15m"]["oi"]),
            "dOI_1h": _round_pct(changes["1h"]["oi"]),
            "dOI_4h": _round_pct(changes["4h"]["oi"]),
            "dOI_24h": _round_pct(changes["1d"]["oi"]),
            "volume_ma_ratio": round(volume_ma_ratio, 2),
        },
        "notes": notes,
        "alerts": [signal for signal in signals if signal.get("active") is not False],
        "all_signals": signals,
        "orderbook": book,
        "chip_zone": chip,
        "flow": flow,
        "exchanges": [
            {
                "exchange": item.exchange,
                "price": round_price(item.price) if item.price else None,
                "oi_usd": round(item.oi_usd, 2) if item.oi_usd else None,
                "oi_coin": round(item.oi_coin, 6) if item.oi_coin else None,
                "funding": round(item.funding * 100, 5) if item.funding is not None else None,
                "volume_24h_usd": round(item.volume_24h_usd, 2) if item.volume_24h_usd else None,
                "long_short_ratio": round(item.long_short_ratio, 4) if item.long_short_ratio is not None else None,
                "status": "ok" if item.error is None else "error",
                "error": item.error,
            }
            for item in exchanges
        ],
        "history_samples": history_samples,
    }


@cached(ttl=15, prefix="oi_signal")
async def get_oi_signal(
    symbol: str = "BTC",
    timeframe: str = "1h",
    chip_interval: str | None = None,
) -> dict[str, Any]:
    exchanges = await fetch_all_exchanges(symbol)
    return await score_oi_signal(
        exchanges,
        symbol,
        timeframe=timeframe,
        chip_interval=chip_interval,
    )
