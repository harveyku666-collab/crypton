"""
第三方 API 端点统一注册表
========================

所有对外 HTTP 请求的目标地址必须在此文件中声明。
http_client.py 中的出站白名单从这里自动生成。

⚠️ 安全规则:
  1. 所有外部请求只允许 GET（只读获取数据），写操作需在此标注 allow_write=True
  2. 新增接口必须在此注册，否则 http_client 会拦截
  3. 禁止向任何第三方发送用户私钥、账户密码、个人数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str
    description: str
    data_direction: str = "inbound"  # inbound=只获取数据, outbound=会发送数据, bidirectional=双向
    allow_write: bool = False  # True 表示允许 POST/PUT/DELETE
    sensitive: bool = False  # True 表示会携带 API Key
    paths: List[str] = field(default_factory=list)


# ─── 行情数据源 (只读) ───────────────────────────────────────────
DESK3_API = Endpoint(
    name="Desk3",
    base_url="https://api1.desk3.io/v1",
    description="加密货币行情、新闻、市场周期数据聚合平台",
    paths=[
        "/cryptocurrency/market  # 主流币实时价格",
        "/news/list              # 新闻快讯列表",
        "/cryptocurrency/top     # 交易量排行",
        "/cryptocurrency/market-cap  # 市值排行",
        "/cryptocurrency/board   # 行情看板",
    ],
)

DESK3_MCP = Endpoint(
    name="Desk3 MCP",
    base_url="https://mcp.desk3.io/v1",
    description="Desk3 MCP 接口 — 市场周期指标(Puell Multiple, Pi Cycle等)",
    paths=[
        "/market/cycles          # 市场周期指标",
    ],
)

COINGECKO = Endpoint(
    name="CoinGecko",
    base_url="https://api.coingecko.com/api/v3",
    description="CoinGecko 免费 API — 全球市场数据、趋势币种、市值",
    paths=[
        "/simple/price           # 实时价格+市值+交易量",
        "/global                 # 全球市场统计(总市值/BTC主导率)",
        "/search/trending        # 热门趋势币种(含价格/涨跌/市值)",
    ],
)

ALTERNATIVE_ME = Endpoint(
    name="Alternative.me",
    base_url="https://api.alternative.me",
    description="恐惧&贪婪指数",
    paths=[
        "/fng                    # 恐惧贪婪指数(含历史)",
    ],
)

# ─── 交易所公开数据 (只读) ───────────────────────────────────────
BINANCE_SPOT = Endpoint(
    name="Binance Spot (公开)",
    base_url="https://api.binance.com",
    description="币安现货公开 API — K线、资金费率",
    paths=[
        "/api/v3/klines          # K线数据",
        "/fapi/v1/fundingRate    # 资金费率",
    ],
)

BINANCE_SPOT_MIRRORS = Endpoint(
    name="Binance Spot 备用节点",
    base_url="https://api-gcp.binance.com",
    description="币安 GCP 备用节点（同上，故障切换用）",
)

BINANCE_DATA_VISION = Endpoint(
    name="Binance Data Vision",
    base_url="https://data-api.binance.vision",
    description="币安数据节点备用（同上，故障切换用）",
)

BINANCE_FUTURES = Endpoint(
    name="Binance Futures (公开)",
    base_url="https://fapi.binance.com",
    description="币安合约公开 API — 合约K线、资金费率",
    paths=[
        "/fapi/v1/klines         # 合约K线",
        "/fapi/v1/fundingRate    # 合约资金费率",
        "/fapi/v1/premiumIndex   # 资金费率预测",
    ],
)

# ─── 交易所私有交易 (需 API Key, 可写) ──────────────────────────
BINANCE_TRADE = Endpoint(
    name="Binance 交易 (私有)",
    base_url="https://api.binance.com",
    description="币安交易操作 — 下单/撤单/查余额（需 API Key）",
    data_direction="bidirectional",
    allow_write=True,
    sensitive=True,
    paths=[
        "/api/v3/order           # 下单/撤单",
        "/api/v3/account         # 查询余额",
        "/api/v3/openOrders      # 查询挂单",
    ],
)

BINANCE_TESTNET_SPOT = Endpoint(
    name="Binance Testnet Spot",
    base_url="https://testnet.binance.vision",
    description="币安现货测试网（模拟交易）",
    data_direction="bidirectional",
    allow_write=True,
    sensitive=True,
)

BINANCE_TESTNET_FUTURES = Endpoint(
    name="Binance Testnet Futures",
    base_url="https://testnet.binancefuture.com",
    description="币安合约测试网（模拟交易）",
    data_direction="bidirectional",
    allow_write=True,
    sensitive=True,
)

OKX_EXCHANGE = Endpoint(
    name="OKX 交易所 (私有)",
    base_url="https://www.okx.com",
    description="OKX 交易操作 — 下单/撤单/查余额（需 API Key）",
    data_direction="bidirectional",
    allow_write=True,
    sensitive=True,
    paths=[
        "/api/v5/account/balance     # 查询余额",
        "/api/v5/trade/order         # 下单",
        "/api/v5/trade/cancel-order  # 撤单",
        "/api/v5/trade/orders-pending # 查询挂单",
        "/api/v5/account/positions   # 查询持仓",
    ],
)

# ─── DeFi 数据 (只读) ───────────────────────────────────────────
DEFI_LLAMA = Endpoint(
    name="DefiLlama",
    base_url="https://api.llama.fi",
    description="DefiLlama — DeFi 协议 TVL 数据",
    paths=[
        "/protocols              # 所有 DeFi 协议 TVL",
    ],
)

DEFI_LLAMA_YIELDS = Endpoint(
    name="DefiLlama Yields",
    base_url="https://yields.llama.fi",
    description="DefiLlama — DeFi 收益率池数据",
    paths=[
        "/pools                  # 全部收益池(APY/TVL)",
    ],
)

# ─── 链上数据 (只读, 暂未启用) ──────────────────────────────────
WHALE_ALERT = Endpoint(
    name="Whale Alert",
    base_url="https://api.whale-alert.io/v1",
    description="鲸鱼监控 — 大额链上转账（需 API Key，暂未接入）",
    sensitive=True,
    paths=[
        "/transactions           # 大额转账记录",
    ],
)

# ─── AI 服务 (出站, 发送市场数据获取分析) ───────────────────────
OPENAI_API = Endpoint(
    name="OpenAI API",
    base_url="https://api.openai.com/v1",
    description="OpenAI Chat API — 发送市场数据获取 AI 分析/预测",
    data_direction="outbound",
    allow_write=True,
    sensitive=True,
    paths=[
        "/chat/completions       # AI 对话(发送市场数据, 返回分析)",
    ],
)


# ─── 注册表 ─────────────────────────────────────────────────────
ALL_ENDPOINTS: list[Endpoint] = [
    DESK3_API,
    DESK3_MCP,
    COINGECKO,
    ALTERNATIVE_ME,
    BINANCE_SPOT,
    BINANCE_SPOT_MIRRORS,
    BINANCE_DATA_VISION,
    BINANCE_FUTURES,
    BINANCE_TRADE,
    BINANCE_TESTNET_SPOT,
    BINANCE_TESTNET_FUTURES,
    OKX_EXCHANGE,
    DEFI_LLAMA,
    DEFI_LLAMA_YIELDS,
    WHALE_ALERT,
    OPENAI_API,
]

ALLOWED_HOSTS: set[str] = set()
for _ep in ALL_ENDPOINTS:
    from urllib.parse import urlparse
    _parsed = urlparse(_ep.base_url)
    if _parsed.hostname:
        ALLOWED_HOSTS.add(_parsed.hostname)
