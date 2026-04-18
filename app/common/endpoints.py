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
        "/api/v3/ticker/price    # 现货价格",
        "/api/v3/ticker/24hr     # 24h 行情统计",
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

BINANCE_WEB3 = Endpoint(
    name="Binance Web3 Rankings",
    base_url="https://web3.binance.com",
    description="Binance Web3 公共榜单接口 — 趋势币、热搜、Alpha、社交热度、聪明钱流入、Meme 榜和地址 PnL 榜",
    paths=[
        "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard  # 社交热度榜",
        "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list             # 统一代币榜",
        "/bapi/defi/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query                       # 聪明钱流入榜",
        "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/exclusive/rank/list           # Meme 榜",
        "/bapi/defi/v1/public/wallet-direct/market/leaderboard/query                                     # 地址 PnL 榜",
    ],
)

BINANCE_STATIC = Endpoint(
    name="Binance Static CDN",
    base_url="https://bin.bnbstatic.com",
    description="Binance Web3 图标静态资源 CDN",
    paths=[
        "/static/assets  # 代币 logo 和静态图标",
    ],
)

BINANCE_FUTURES = Endpoint(
    name="Binance Futures (公开)",
    base_url="https://fapi.binance.com",
    description="币安合约公开 API — 合约K线、资金费率",
    paths=[
        "/fapi/v1/klines         # 合约K线",
        "/fapi/v1/depth          # 合约盘口深度",
        "/fapi/v1/openInterest   # 当前持仓量",
        "/fapi/v1/ticker/24hr    # 合约24h行情",
        "/fapi/v1/fundingRate    # 合约资金费率",
        "/fapi/v1/premiumIndex   # 资金费率预测",
        "/futures/data/globalLongShortAccountRatio  # 全市场多空比",
        "/futures/data/topLongShortAccountRatio     # 大户多空比",
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
    name="OKX 交易所",
    base_url="https://www.okx.com",
    description="OKX API — 公开数据(OI/多空比) + 交易操作(需 API Key)",
    data_direction="bidirectional",
    allow_write=True,
    sensitive=True,
    paths=[
        "/api/v5/public/open-interest  # 当前持仓量",
        "/api/v5/public/funding-rate   # 当前资金费率",
        "/api/v5/market/ticker         # 行情快照",
        "/api/v5/market/books-full     # 深度盘口",
        "/api/v5/rubik/stat/contracts/open-interest-volume  # OI + 成交量",
        "/api/v5/rubik/stat/contracts/long-short-account-ratio  # 多空比",
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

DEFI_LLAMA_BRIDGES = Endpoint(
    name="DefiLlama Bridges",
    base_url="https://bridges.llama.fi",
    description="DefiLlama — 跨链桥排行和交易量数据",
    paths=[
        "/bridges               # 跨链桥列表+24h交易量",
    ],
)

# ─── DEX 数据 (只读) ─────────────────────────────────────────
DEXSCREENER = Endpoint(
    name="DEX Screener",
    base_url="https://api.dexscreener.com",
    description="DEX Screener — DEX 交易对和实时交易数据（免费公开）",
    paths=[
        "/latest/dex/tokens/{address}  # 代币 DEX 交易对",
        "/latest/dex/pairs/{chain}/{address}  # 交易对详情",
    ],
)

# ─── 预测市场 (只读) ─────────────────────────────────────────
POLYMARKET_GAMMA = Endpoint(
    name="Polymarket Gamma",
    base_url="https://gamma-api.polymarket.com",
    description="Polymarket — 预测市场事件和赔率数据（免费公开）",
    paths=[
        "/events                # 预测市场事件列表",
        "/markets               # 市场详情",
    ],
)

# ─── 衍生品数据 (只读) ─────────────────────────────────────────
GATEIO_FUTURES = Endpoint(
    name="Gate.io Futures (公开)",
    base_url="https://api.gateio.ws",
    description="Gate.io 合约公开 API — OI、多空比、清算数据（免费，无需 API Key）",
    paths=[
        "/api/v4/futures/usdt/contracts/{contract}  # 合约详情(含 OI)",
        "/api/v4/futures/usdt/contract_stats         # 历史 OI + 多空比 + 清算",
    ],
)

BITGET_FUTURES = Endpoint(
    name="Bitget Futures (公开)",
    base_url="https://api.bitget.com",
    description="Bitget 合约公开 API — 持仓量（免费，无需 API Key）",
    paths=[
        "/api/v2/mix/market/open-interest  # 当前持仓量",
        "/api/v2/mix/market/ticker         # 行情快照",
        "/api/v2/mix/market/current-fund-rate  # 当前资金费率",
    ],
)

BYBIT_FUTURES = Endpoint(
    name="Bybit Futures (公开)",
    base_url="https://api.bybit.com",
    description="Bybit 合约公开 API — 持仓量（免费，需代理）",
    paths=[
        "/v5/market/open-interest  # 持仓量",
        "/v5/market/tickers        # 合约行情",
        "/v5/market/orderbook      # 深度盘口",
        "/v5/market/account-ratio  # 多空比",
    ],
)

COINBASE_EXCHANGE = Endpoint(
    name="Coinbase Exchange (公开)",
    base_url="https://api.coinbase.com",
    description="Coinbase 公开 API — 现货价格",
    paths=[
        "/v2/prices/{pair}/spot   # 现货价格",
        "/v2/exchange-rates       # 汇率",
    ],
)

COINBASE_EXCHANGE_PRO = Endpoint(
    name="Coinbase Exchange Pro (公开)",
    base_url="https://api.exchange.coinbase.com",
    description="Coinbase Exchange 公开 API — 产品统计、订单簿",
    paths=[
        "/products/{pair}/stats   # 24h 统计(开/高/低/收/量)",
        "/products/{pair}/book    # 订单簿",
    ],
)

COINBASE_ADVANCED = Endpoint(
    name="Coinbase Advanced Trade",
    base_url="https://advanced-api.coinbase.com",
    description="Coinbase Advanced Trade API — 合约/衍生品数据",
    paths=[
        "/api/v3/brokerage/products  # 产品列表",
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
    BINANCE_WEB3,
    BINANCE_STATIC,
    BINANCE_FUTURES,
    BINANCE_TRADE,
    BINANCE_TESTNET_SPOT,
    BINANCE_TESTNET_FUTURES,
    OKX_EXCHANGE,
    GATEIO_FUTURES,
    BITGET_FUTURES,
    BYBIT_FUTURES,
    COINBASE_EXCHANGE,
    COINBASE_ADVANCED,
    COINBASE_EXCHANGE_PRO,
    DEFI_LLAMA,
    DEFI_LLAMA_YIELDS,
    DEFI_LLAMA_BRIDGES,
    DEXSCREENER,
    POLYMARKET_GAMMA,
    WHALE_ALERT,
    OPENAI_API,
]

ALLOWED_HOSTS: set[str] = set()
for _ep in ALL_ENDPOINTS:
    from urllib.parse import urlparse
    _parsed = urlparse(_ep.base_url)
    if _parsed.hostname:
        ALLOWED_HOSTS.add(_parsed.hostname)
