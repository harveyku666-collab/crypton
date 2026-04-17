"""
技能注册表 — 首页展示免费技能，Surf 专业功能归类到一个入口
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
    requires_credits: bool = False
    features: List[str] = field(default_factory=list)
    features_zh: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)


# Surf PRO 子模块定义，用于前端渲染
SURF_PRO_MODULES: list[dict] = [
    {
        "id": "exchange-data",
        "name": "Exchange Trading Data",
        "name_zh": "交易所高级数据",
        "icon": "🏦",
        "desc_zh": "订单簿深度、多空比、永续合约快照、跨交易所实时价格",
        "features_zh": ["订单簿深度（多交易所）", "多空比历史", "永续合约快照", "跨交易所价格"],
        "requires_credits": True,
        "free_alt": "基础深度/多空比已接入 Binance 免费 API",
    },
    {
        "id": "etf-flows",
        "name": "ETF Fund Flows",
        "name_zh": "ETF 资金流向",
        "icon": "🏛️",
        "desc_zh": "追踪 BTC/ETH ETF 资金流入流出，机构资金动向信号",
        "features_zh": ["BTC/ETH ETF 每日资金流", "历史流入/流出趋势", "净流量追踪"],
        "requires_credits": True,
    },
    {
        "id": "options-market",
        "name": "Options Market Data",
        "name_zh": "期权市场数据",
        "icon": "📐",
        "desc_zh": "期权未平仓量、最大痛点、看跌/看涨比率",
        "features_zh": ["期权未平仓量", "最大痛点价格", "看跌/看涨比率", "到期日分析"],
        "requires_credits": True,
    },
    {
        "id": "onchain-indicators",
        "name": "On-Chain Indicators",
        "name_zh": "链上指标分析",
        "icon": "⛓️",
        "desc_zh": "NUPL、SOPR、MVRV、S2F 等链上指标",
        "features_zh": ["NUPL", "SOPR", "MVRV", "Stock-to-Flow 模型"],
        "requires_credits": True,
    },
    {
        "id": "liquidation-monitor",
        "name": "Liquidation Monitor",
        "name_zh": "清算数据监控",
        "icon": "💥",
        "desc_zh": "清算图表、按交易所分布、大额清算单",
        "features_zh": ["清算图表（小时级）", "多空清算比例", "按交易所分布", "大额清算单"],
        "requires_credits": True,
    },
    {
        "id": "funding-rate-monitor",
        "name": "Multi-Exchange Funding Rates",
        "name_zh": "多交易所资金费率",
        "icon": "💰",
        "desc_zh": "跨交易所永续合约资金费率排名和套利信号",
        "features_zh": ["多交易所实时费率", "极端费率预警", "逐交易对历史"],
        "requires_credits": True,
        "free_alt": "Binance 单交易所费率已免费接入",
    },
    {
        "id": "prediction-advanced",
        "name": "Prediction Markets Advanced",
        "name_zh": "预测市场高级版",
        "icon": "🔮",
        "desc_zh": "Polymarket 聪明资金/排行榜/订单簿/K线 + Kalshi 全套 + 跨平台对比",
        "features_zh": [
            "Polymarket 聪明资金追踪", "排行榜", "订单簿", "K线",
            "Kalshi 事件和市场", "跨平台对比", "预测市场分析",
        ],
        "requires_credits": True,
        "free_alt": "基础 Polymarket 事件数据已免费接入",
    },
    {
        "id": "token-analysis-pro",
        "name": "Token Deep Analysis",
        "name_zh": "代币深度分析",
        "icon": "🪙",
        "desc_zh": "代币持有者分布、解锁计划、DEX 交易详情、转账历史",
        "features_zh": ["持有者分布", "解锁计划", "DEX 交易详情", "转账历史"],
        "requires_credits": True,
        "free_alt": "DEX Screener 基础交易对数据已免费接入",
    },
    {
        "id": "wallet-tracker",
        "name": "Wallet & Whale Intelligence",
        "name_zh": "钱包与鲸鱼情报",
        "icon": "🐋",
        "desc_zh": "钱包余额、DeFi 持仓、交易历史、净值追踪，覆盖 40+ 条链",
        "features_zh": ["钱包余额", "DeFi 持仓", "交易历史", "转账记录", "净值趋势", "批量标签"],
        "requires_credits": True,
    },
    {
        "id": "onchain-data",
        "name": "On-Chain Data Engine",
        "name_zh": "链上数据引擎",
        "icon": "🔗",
        "desc_zh": "Gas 价格、交易查询、区块链 SQL、表结构浏览器",
        "features_zh": ["Gas 价格", "交易详情查询", "区块链 SQL", "表结构浏览"],
        "requires_credits": True,
        "free_alt": "DefiLlama 收益池/跨链桥排名已免费接入",
    },
    {
        "id": "social-sentiment",
        "name": "Social Intelligence",
        "name_zh": "社交情报系统",
        "icon": "🐦",
        "desc_zh": "热度排名、情绪分析、KOL 主页、互动评分、Smart Follower",
        "features_zh": ["热度排名", "情绪分析", "KOL 主页", "互动评分", "粉丝/关注列表"],
        "requires_credits": True,
    },
    {
        "id": "project-analysis",
        "name": "Project Analysis",
        "name_zh": "项目深度分析",
        "icon": "🏗️",
        "desc_zh": "项目聚合详情、脉搏、DeFi 指标、协议排名",
        "features_zh": ["项目详情", "项目脉搏", "DeFi 指标", "DeFi 排名"],
        "requires_credits": True,
    },
    {
        "id": "fund-analysis",
        "name": "Crypto Fund Analysis",
        "name_zh": "加密基金分析",
        "icon": "💼",
        "desc_zh": "基金详情、持仓组合、AUM 排名",
        "features_zh": ["基金详情", "持仓组合", "按 AUM 排名"],
        "requires_credits": True,
    },
    {
        "id": "event-calendar",
        "name": "Crypto Event Calendar",
        "name_zh": "事件日历",
        "icon": "📅",
        "desc_zh": "交易所上币、TGE、公开募资",
        "features_zh": ["交易所上币", "TGE 事件", "公开募资"],
        "requires_credits": True,
        "free_alt": "Desk3 基础事件日历已免费接入",
    },
    {
        "id": "search-engine",
        "name": "Crypto Search Engine",
        "name_zh": "全能搜索引擎",
        "icon": "🔍",
        "desc_zh": "搜索项目、空投、事件、基金、新闻、预测市场、社交用户、钱包",
        "features_zh": ["项目搜索", "空投搜索", "基金搜索", "新闻搜索", "预测市场搜索", "社交搜索", "钱包搜索"],
        "requires_credits": True,
    },
]


SKILLS: list[Skill] = [
    # ═══════════════════════════════════════════════════════════
    # 免费技能（首页独立展示）
    # ═══════════════════════════════════════════════════════════
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
        requires_credits=False,
        features=[
            "Real-time major coin prices with market cap",
            "Global market stats (total market cap, BTC dominance, 24h volume)",
            "Fear & Greed Index with historical comparison",
            "Top trending coins",
            "BTC 4H technical analysis (RSI, MACD, Bollinger, MA)",
            "Top DeFi yield opportunities",
            "Market cycle indicators",
            "Funding rate extremes",
            "News highlights with sentiment tags",
        ],
        features_zh=[
            "主流币实时价格及市值",
            "全球市场统计（总市值、BTC主导率、24h交易量）",
            "恐惧贪婪指数及历史对比",
            "热门趋势币种",
            "BTC 4H 技术分析（RSI、MACD、布林带、均线）",
            "DeFi 最佳收益机会",
            "市场周期指标",
            "资金费率异常",
            "新闻快讯（含情绪标签）",
        ],
        data_sources=["CoinGecko", "Desk3", "Alternative.me", "Binance", "DefiLlama"],
    ),

    Skill(
        id="technical-analysis",
        name="Technical Analysis Engine",
        name_zh="技术分析引擎",
        description="Technical indicators (RSI, MACD, Bollinger Bands, MA) computed from Binance K-line data.",
        description_zh="基于 Binance K 线数据本地计算技术指标（RSI、MACD、布林带、均线交叉）。",
        icon="📈",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/analysis/indicators",
        requires_credits=False,
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
        name="News Intelligence",
        name_zh="新闻情报",
        description="Multi-language news with sentiment classification, importance tagging, full-text search.",
        description_zh="多语言新闻，含情绪分类、重要性标签、全文搜索。",
        icon="📰",
        category="news",
        status="active",
        api_endpoint="/api/v1/news/history?limit=30",
        requires_credits=False,
        features=[
            "Multi-language news (EN/ZH)",
            "Sentiment classification (bullish/bearish/neutral)",
            "Importance tagging",
            "Auto database storage",
        ],
        features_zh=[
            "多语言新闻（中文/英文）",
            "情绪分类（看涨/看跌/中性）",
            "重要性标签",
            "自动入库存储",
        ],
        data_sources=["Desk3"],
    ),

    Skill(
        id="prediction-markets",
        name="Prediction Markets",
        name_zh="预测市场",
        description="Polymarket event odds and market data via free Gamma API.",
        description_zh="通过免费 Gamma API 获取 Polymarket 预测市场事件和赔率数据。",
        icon="🔮",
        category="market",
        status="active",
        api_endpoint="/api/v1/market/prediction/polymarket",
        requires_credits=False,
        features=[
            "Polymarket events & odds",
            "Market detail",
        ],
        features_zh=[
            "Polymarket 热门事件及赔率",
            "市场详情",
        ],
        data_sources=["Polymarket Gamma API"],
    ),

    Skill(
        id="defi-yield-scanner",
        name="DeFi Yield Scanner",
        name_zh="DeFi 收益扫描器",
        description="Scans DeFi protocols across chains for the best yield opportunities.",
        description_zh="跨链扫描 DeFi 协议，寻找最佳收益机会，按 APY、TVL 过滤。",
        icon="🌾",
        category="defi",
        status="active",
        api_endpoint="/api/v1/analysis/defi-yields",
        requires_credits=False,
        features=[
            "Multi-chain yield scanning",
            "APY/TVL filtering and ranking",
        ],
        features_zh=[
            "多链收益扫描",
            "APY/TVL 过滤与排名",
        ],
        data_sources=["DefiLlama"],
    ),

    Skill(
        id="btc-quant-predictor",
        name="BTC Quantitative Short-term Predictor",
        name_zh="BTC 量化短线预测",
        description="Multi-factor quantitative scoring for BTC short-term direction prediction.",
        description_zh="BTC 多因子量化评分系统，输出涨跌方向预测、置信度、止损止盈。",
        icon="🎯",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/analysis/btc-predict",
        requires_credits=False,
        features=[
            "Multi-factor scoring: RSI + MACD + Bollinger + Momentum + Volume",
            "Direction prediction with confidence %",
            "Auto stop-loss and 3-level take-profit",
            "Multi-coin support",
        ],
        features_zh=[
            "多因子评分：RSI + MACD + 布林带 + 动量 + 成交量",
            "方向预测 + 置信度百分比",
            "自动计算止损 + 三级止盈",
            "多币种支持",
        ],
        data_sources=["Binance"],
    ),

    Skill(
        id="oi-signal",
        name="OI Signal Engine",
        name_zh="OI 信号研判系统",
        description="Multi-exchange OI aggregation with multi-timeframe scoring: price-OI quadrant analysis, funding/volume confirmation, orderbook depth imbalance, chip-zone profile, order-flow context, divergence detection, squeeze alerts, and overheating warnings.",
        description_zh="多交易所 OI 聚合 + 多周期量化评分：价格-OI 象限分析、资金费率与成交量确认、盘口深度失衡、筹码分布、订单流上下文、背离检测、挤压预警和过热警报。",
        icon="🎯",
        category="analysis",
        status="active",
        api_endpoint="/oi-signal",
        requires_credits=False,
        features=[
            "Multi-exchange OI aggregation (Binance, OKX, Bybit, Gate.io, Bitget)",
            "Multi-timeframe presets (15m / 1h / 4h / 1d)",
            "4-Quadrant model (Price x OI trend analysis)",
            "Weighted funding rate scoring",
            "Volume vs MA20 analysis with fire/sleep detection",
            "Long/short ratio cross-exchange aggregation",
            "Orderbook depth imbalance and liquidity wall detection",
            "Chip-zone / volume profile distribution",
            "Order-flow context: taker delta, CVD, VWAP, basis, perp/spot ratio",
            "OI-Price divergence detection",
            "Squeeze alerts (low vol + narrow range)",
            "Overheating warnings (extreme OI + funding)",
            "0-100 quantitative score with trading direction",
            "Leverage recommendation engine",
        ],
        features_zh=[
            "五大交易所 OI 聚合（Binance、OKX、Bybit、Gate.io、Bitget）",
            "多周期预设（15m / 1h / 4h / 1d）",
            "四象限模型（价格 × OI 趋势分析）",
            "加权资金费率评分",
            "成交量 vs MA20 分析（活跃/冷淡检测）",
            "多空比跨交易所聚合",
            "盘口深度失衡与流动性墙识别",
            "筹码分布 / Volume Profile",
            "订单流上下文：Taker Delta、CVD、VWAP、基差、合约/现货量比",
            "OI-价格背离检测",
            "挤压预警（低量 + 窄幅）",
            "过热警报（极端 OI + 费率）",
            "0-100 量化评分 + 方向判断",
            "杠杆建议引擎",
        ],
        data_sources=["Binance", "OKX", "Bybit", "Gate.io", "Bitget"],
    ),

    Skill(
        id="open-interest",
        name="Open Interest & Derivatives",
        name_zh="持仓量与衍生品数据",
        description="Multi-exchange open interest aggregated from Binance, OKX, Bybit, Gate.io, and Bitget. Includes long/short ratio, liquidation data, and OI volume history.",
        description_zh="聚合 Binance、OKX、Bybit、Gate.io、Bitget 五大交易所的持仓量（OI）数据，含多空比、清算数据和 OI 成交量历史。",
        icon="📐",
        category="analysis",
        status="active",
        api_endpoint="/api/v1/market/open-interest/BTC",
        requires_credits=False,
        features=[
            "Multi-exchange current OI (Binance, OKX, Bybit, Gate.io, Bitget)",
            "Historical OI + volume trends",
            "Long/short ratio (taker + account)",
            "Liquidation data (long/short USD)",
            "Mark price tracking",
        ],
        features_zh=[
            "五大交易所当前持仓量（Binance、OKX、Bybit、Gate.io、Bitget）",
            "持仓量 + 成交量历史趋势",
            "多空比（吃单 + 账户）",
            "清算数据（多/空 USD）",
            "标记价格追踪",
        ],
        data_sources=["Binance", "OKX", "Bybit", "Gate.io", "Bitget"],
    ),

    # ═══════════════════════════════════════════════════════════
    # Surf 专业工具箱（首页一个入口，内含 15 个子模块）
    # ═══════════════════════════════════════════════════════════
    Skill(
        id="surf-pro",
        name="Surf Professional Data Suite",
        name_zh="Surf 专业数据套件",
        description="80+ professional crypto intelligence tools powered by Surf — exchange depth, ETF flows, options, on-chain indicators, liquidation, social intelligence, wallet tracking, fund analysis, search, and more. Requires Surf credits.",
        description_zh="80+ 专业加密情报工具，涵盖交易所深度、ETF 资金流、期权、链上指标、清算监控、社交情报、钱包追踪、基金分析、全能搜索等。需要 Surf credits。",
        icon="🌊",
        category="pro",
        status="active",
        api_endpoint="/api/v1/skills/surf-pro",
        requires_credits=True,
        features=[
            "Exchange depth, long/short ratio, perpetual snapshots (multi-exchange)",
            "ETF fund flows (BTC/ETH)",
            "Options market data",
            "On-chain indicators (NUPL, SOPR, MVRV, S2F)",
            "Liquidation monitor",
            "Multi-exchange funding rates",
            "Prediction markets advanced (Polymarket + Kalshi full suite)",
            "Token deep analysis (holders, unlocks, DEX trades)",
            "Wallet & whale intelligence (40+ chains)",
            "On-chain data engine (Gas, TX, SQL)",
            "Social intelligence (mindshare, sentiment, KOL)",
            "Project & DeFi analysis",
            "Crypto fund analysis",
            "Event calendar (listings, TGE, public sales)",
            "Universal search engine",
        ],
        features_zh=[
            "交易所深度、多空比、永续快照（多交易所）",
            "ETF 资金流向（BTC/ETH）",
            "期权市场数据",
            "链上指标（NUPL、SOPR、MVRV、S2F）",
            "清算数据监控",
            "多交易所资金费率",
            "预测市场高级版（Polymarket + Kalshi 全套）",
            "代币深度分析（持有者、解锁、DEX 交易）",
            "钱包与鲸鱼情报（40+ 条链）",
            "链上数据引擎（Gas、交易查询、SQL）",
            "社交情报系统（热度、情绪、KOL）",
            "项目与 DeFi 分析",
            "加密基金分析",
            "事件日历（上币、TGE、募资）",
            "全能搜索引擎",
        ],
        data_sources=["Surf"],
    ),
]

SKILL_MAP: dict[str, Skill] = {s.id: s for s in SKILLS}
