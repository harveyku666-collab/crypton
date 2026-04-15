"""
技能注册表 — 定义所有已融合的 OpenClaw 技能及其元数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    name_zh: str
    description: str
    description_zh: str
    icon: str
    category: str
    status: str  # active / beta / planned
    api_endpoint: str
    features: List[str] = field(default_factory=list)
    features_zh: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)


SKILLS: list[Skill] = [
    Skill(
        id="market-briefing",
        name="Cryptocurrency Market Live Briefing",
        name_zh="加密货币市场实时简报",
        description="Comprehensive market briefing aggregating prices, global stats, fear & greed index, trending coins, BTC technical analysis, DeFi yields, market cycles, funding rates, and news with sentiment.",
        description_zh="全面的市场简报，聚合价格、全球统计、恐惧贪婪指数、趋势币种、BTC技术分析、DeFi收益、市场周期、资金费率及带情绪标签的新闻。",
        icon="📊",
        category="market",
        status="active",
        api_endpoint="/api/v1/briefing/live",
        features=[
            "Real-time major coin prices with market cap",
            "Global market stats (total market cap, BTC dominance, 24h volume)",
            "Fear & Greed Index with historical comparison",
            "Top trending coins with price, change%, market cap",
            "BTC 4H technical analysis (RSI, MACD, Bollinger, MA)",
            "Top DeFi yield opportunities",
            "Market cycle indicators (Puell Multiple, Pi Cycle, Altcoin Season)",
            "Funding rate extremes",
            "News highlights with sentiment (bullish/bearish/neutral) and importance tags",
            "Daily/weekly/monthly scheduled reports",
        ],
        features_zh=[
            "主流币实时价格及市值",
            "全球市场统计（总市值、BTC主导率、24h交易量）",
            "恐惧贪婪指数及历史对比",
            "热门趋势币种（含价格、涨跌幅、市值）",
            "BTC 4H 技术分析（RSI、MACD、布林带、均线）",
            "DeFi 最佳收益机会",
            "市场周期指标（Puell乘数、Pi周期、山寨季指数）",
            "资金费率异常",
            "新闻快讯（含看涨/看跌/中性情绪 + 重要性标签）",
            "每日/每周/每月定时生成报告",
        ],
        data_sources=["Desk3", "CoinGecko", "Alternative.me", "Binance", "DefiLlama"],
    ),
    Skill(
        id="defi-yield-scanner",
        name="DeFi Yield Scanner",
        name_zh="DeFi 收益扫描器",
        description="Scans DeFi protocols across chains for the best yield opportunities, filtering by APY, TVL, and risk level.",
        description_zh="跨链扫描 DeFi 协议，寻找最佳收益机会，按 APY、TVL 和风险等级过滤。",
        icon="🌾",
        category="defi",
        status="active",
        api_endpoint="/api/v1/analysis/defi-yields",
        features=[
            "Multi-chain yield scanning",
            "APY/TVL filtering and ranking",
            "Historical yield trend tracking",
        ],
        features_zh=[
            "多链收益扫描",
            "APY/TVL 过滤与排名",
            "历史收益趋势追踪",
        ],
        data_sources=["DefiLlama"],
    ),
    Skill(
        id="funding-rate-monitor",
        name="Funding Rate Monitor",
        name_zh="资金费率监控",
        description="Monitors perpetual futures funding rates across exchanges, identifying arbitrage and extreme sentiment signals.",
        description_zh="监控永续合约资金费率，识别套利机会和极端市场情绪信号。",
        icon="💰",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/analysis/funding",
        features=[
            "Real-time funding rate tracking",
            "Historical rate comparison",
            "Extreme rate alerts (arbitrage opportunities)",
        ],
        features_zh=[
            "实时资金费率追踪",
            "历史费率对比",
            "极端费率预警（套利机会）",
        ],
        data_sources=["Binance"],
    ),
    Skill(
        id="technical-analysis",
        name="Technical Analysis Engine",
        name_zh="技术分析引擎",
        description="Computes technical indicators (RSI, MACD, Bollinger Bands, Moving Averages) on kline data for any trading pair.",
        description_zh="基于K线数据计算技术指标（RSI、MACD、布林带、均线），支持任意交易对。",
        icon="📈",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/analysis/indicators",
        features=[
            "RSI, MACD, Bollinger Bands, MA crossovers",
            "Multi-timeframe analysis",
            "Signal generation (overbought/oversold)",
        ],
        features_zh=[
            "RSI、MACD、布林带、均线交叉",
            "多时间周期分析",
            "信号生成（超买/超卖）",
        ],
        data_sources=["Binance"],
    ),
    Skill(
        id="news-sentiment",
        name="News Sentiment Tracker",
        name_zh="新闻情绪追踪",
        description="Aggregates crypto news with real-time sentiment classification (bullish/bearish/neutral) and importance tagging.",
        description_zh="聚合加密货币新闻，实时分类情绪（看涨/看跌/中性）并标注重要性。",
        icon="📰",
        category="news",
        status="active",
        api_endpoint="/api/v1/news/history?limit=30",
        features=[
            "Multi-language news (EN/ZH)",
            "Sentiment classification (bullish/bearish/neutral)",
            "Importance tagging (important/normal)",
            "Automatic database storage",
        ],
        features_zh=[
            "多语言新闻（中文/英文）",
            "情绪分类（看涨/看跌/中性）",
            "重要性标签（重要/普通）",
            "自动入库存储",
        ],
        data_sources=["Desk3"],
    ),
    Skill(
        id="whale-tracker",
        name="Whale Activity Tracker",
        name_zh="鲸鱼动向追踪",
        description="Monitors large on-chain transactions and whale wallet movements for early market signals.",
        description_zh="监控链上大额转账和鲸鱼钱包动向，提供早期市场信号。",
        icon="🐋",
        category="onchain",
        status="planned",
        api_endpoint="/api/v1/onchain/whales",
        features=[
            "Large transaction monitoring",
            "Whale wallet tracking",
            "Exchange inflow/outflow alerts",
        ],
        features_zh=[
            "大额转账监控",
            "鲸鱼钱包追踪",
            "交易所资金流入/流出预警",
        ],
        data_sources=["Whale Alert"],
    ),
    Skill(
        id="ai-prediction",
        name="AI Market Prediction",
        name_zh="AI 市场预测",
        description="AI-powered short-term price direction predictions based on multi-dimensional market data analysis.",
        description_zh="基于多维市场数据分析的 AI 短期价格方向预测。",
        icon="🤖",
        category="ai",
        status="beta",
        api_endpoint="/api/v1/ai/predict",
        features=[
            "Multi-factor analysis",
            "Direction prediction with confidence score",
            "AI reasoning explanation",
        ],
        features_zh=[
            "多因子分析",
            "方向预测（含置信度）",
            "AI 推理解释",
        ],
        data_sources=["OpenAI", "Binance", "CoinGecko"],
    ),
    Skill(
        id="btc-quant-predictor",
        name="BTC Quantitative Short-term Predictor",
        name_zh="BTC 量化短线预测",
        description="Multi-factor quantitative scoring system for BTC short-term direction prediction. Combines RSI, MACD, Bollinger Bands, momentum, and volume analysis to output UP/DOWN/NEUTRAL signals with confidence levels, stop-loss and take-profit targets.",
        description_zh="BTC 多因子量化评分系统，综合 RSI、MACD、布林带、动量和成交量分析，输出涨跌方向预测、置信度评级、止损止盈建议。支持多币种和多时间周期。",
        icon="🎯",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/analysis/btc-predict",
        features=[
            "Multi-factor scoring: RSI + MACD + Bollinger + Momentum + Volume",
            "Direction prediction: UP/DOWN/NEUTRAL with confidence %",
            "Auto stop-loss and 3-level take-profit calculation",
            "Detailed per-indicator signal breakdown",
            "24h market context (high/low/volume/change%)",
            "Multi-coin support (BTC, ETH, SOL, etc.)",
            "Multi-timeframe (1m/5m/15m/1h/4h)",
            "Conservative leverage guidance",
        ],
        features_zh=[
            "多因子评分：RSI + MACD + 布林带 + 动量 + 成交量",
            "方向预测：涨/跌/震荡 + 置信度百分比",
            "自动计算止损 + 三级止盈目标",
            "每个指标的详细信号说明",
            "24h 行情数据（最高/最低/交易量/涨跌幅）",
            "多币种支持（BTC、ETH、SOL 等）",
            "多时间周期（1m/5m/15m/1h/4h）",
            "保守杠杆建议（最多 2-3x）",
        ],
        data_sources=["Binance"],
    ),
    Skill(
        id="auto-trading",
        name="Automated Trading",
        name_zh="自动化交易",
        description="Execute trades on Binance/OKX based on analysis signals with risk management and position sizing.",
        description_zh="基于分析信号在 Binance/OKX 执行交易，包含风险管理和仓位管理。",
        icon="⚡",
        category="trading",
        status="beta",
        api_endpoint="/api/v1/trading/execute",
        features=[
            "Multi-exchange support (Binance, OKX)",
            "Risk management (stop-loss, position sizing)",
            "Testnet simulation mode",
        ],
        features_zh=[
            "多交易所支持（Binance、OKX）",
            "风险管理（止损、仓位管理）",
            "测试网模拟模式",
        ],
        data_sources=["Binance", "OKX"],
    ),
]

SKILL_MAP: dict[str, Skill] = {s.id: s for s in SKILLS}
