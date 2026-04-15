"""News sentiment classification and importance scoring.

Rule-based classifier for fast tagging. Can be extended with AI later.
"""

from __future__ import annotations

BULLISH_KEYWORDS_EN = [
    "rally", "surge", "soar", "bullish", "breakout", "all-time high", "ath",
    "approval", "approved", "etf approved", "adoption", "partnership", "listing",
    "institutional", "inflow", "accumulation", "buy signal", "upgrade",
    "recovery", "rebound", "green", "gains", "pump", "moon", "record high",
    "bitcoin halving", "rate cut", "dovish", "stimulus",
]
BEARISH_KEYWORDS_EN = [
    "crash", "plunge", "dump", "bearish", "selloff", "sell-off", "hack",
    "exploit", "rug pull", "scam", "fraud", "ban", "crackdown", "lawsuit",
    "sec charges", "bankruptcy", "liquidation", "outflow", "fear",
    "capitulation", "decline", "drop", "loss", "red", "correction",
    "rate hike", "hawkish", "inflation", "recession",
]
BULLISH_KEYWORDS_ZH = [
    "上涨", "暴涨", "看涨", "突破", "新高", "历史新高", "利好", "批准",
    "通过", "采用", "合作", "上线", "机构", "流入", "买入", "反弹",
    "恢复", "减半", "降息", "刺激", "增长", "牛市", "看多",
]
BEARISH_KEYWORDS_ZH = [
    "下跌", "暴跌", "看跌", "崩盘", "抛售", "黑客", "攻击", "漏洞",
    "骗局", "欺诈", "禁止", "打击", "诉讼", "破产", "清算", "流出",
    "恐惧", "恐慌", "下降", "亏损", "回调", "加息", "鹰派", "通胀",
    "衰退", "熊市", "看空", "做空",
]
IMPORTANT_KEYWORDS_EN = [
    "bitcoin", "btc", "ethereum", "eth", "sec", "fed", "federal reserve",
    "etf", "regulation", "breaking", "urgent", "hack", "exploit",
    "billion", "trillion", "record", "halving", "rate decision",
    "trump", "congress", "ban", "approval", "institutional",
]
IMPORTANT_KEYWORDS_ZH = [
    "比特币", "以太坊", "SEC", "美联储", "ETF", "监管", "突发", "紧急",
    "黑客", "漏洞", "十亿", "万亿", "记录", "减半", "利率",
    "特朗普", "国会", "禁止", "批准", "机构", "央行",
]


def classify_sentiment(title: str, content: str | None = None) -> str:
    """Returns 'bullish', 'bearish', or 'neutral'."""
    text = f"{title} {content or ''}".lower()

    bull_score = sum(1 for kw in BULLISH_KEYWORDS_EN if kw in text)
    bear_score = sum(1 for kw in BEARISH_KEYWORDS_EN if kw in text)
    bull_score += sum(1 for kw in BULLISH_KEYWORDS_ZH if kw in text)
    bear_score += sum(1 for kw in BEARISH_KEYWORDS_ZH if kw in text)

    if bull_score > bear_score and bull_score >= 1:
        return "bullish"
    if bear_score > bull_score and bear_score >= 1:
        return "bearish"
    return "neutral"


def classify_importance(title: str, content: str | None = None) -> str:
    """Returns 'important' or 'normal'."""
    text = f"{title} {content or ''}".lower()

    score = sum(1 for kw in IMPORTANT_KEYWORDS_EN if kw in text)
    score += sum(1 for kw in IMPORTANT_KEYWORDS_ZH if kw in text)

    return "important" if score >= 2 else "normal"


def tag_news(item: dict) -> dict:
    """Add sentiment and importance tags to a news item."""
    title = item.get("title", "")
    content = item.get("description") or item.get("content", "")
    item["sentiment"] = classify_sentiment(title, content)
    item["importance"] = classify_importance(title, content)
    return item
