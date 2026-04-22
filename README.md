# BitInfo 数字货币交易平台

Full-stack crypto trading platform: market data, technical analysis, AI prediction, automated trading.

## Quick Start

### 1. Infrastructure (PostgreSQL + Redis)

```bash
docker-compose up -d postgres redis
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
# If you need Binance / OKX / Bybit access, also set PROXY_URL
```

### 4. Run Server

```bash
uvicorn app.main:app --reload --port 8000
```

When the app starts it will log whether an outbound proxy is configured. You can also check `GET /health`, which now includes `proxy_configured`.

### 5. Open API Docs

```
http://localhost:8000/docs
```

## Architecture

```
app/
├── main.py                 # FastAPI entry + lifespan
├── config.py               # Settings (Pydantic)
├── common/                 # Shared infrastructure
│   ├── http_client.py      # Connection pool + retry
│   ├── cache.py            # Redis + @cached decorator
│   ├── database.py         # SQLAlchemy async
│   ├── models.py           # ORM models
│   ├── scheduler.py        # APScheduler
│   └── ai_client.py        # OpenAI-compatible client
├── market/                 # Market data (multi-source)
│   ├── sources/
│   │   ├── desk3.py        # Desk3 API
│   │   ├── binance.py      # Binance spot+futures
│   │   ├── coingecko.py    # CoinGecko
│   │   └── defi_llama.py   # DefiLlama yields
│   ├── aggregator.py       # Multi-source fallback
│   ├── jobs.py             # Scheduled collection
│   └── router.py           # /api/v1/market/*
├── analysis/               # Technical analysis
│   ├── indicators.py       # RSI/MACD/Bollinger/Momentum
│   ├── strategy.py         # Scoring framework
│   ├── predictor.py        # Price prediction
│   ├── funding_scan.py     # Funding rate scanner
│   ├── yield_scan.py       # DeFi yield scanner
│   ├── jobs.py             # Scheduled analysis
│   └── router.py           # /api/v1/analysis/*
├── news/                   # News aggregation
│   ├── fetcher.py          # Multi-source fetcher
│   ├── jobs.py             # Scheduled collection
│   └── router.py           # /api/v1/news/*
├── onchain/                # On-chain monitoring
│   ├── whale_tracker.py    # Whale tracking
│   ├── exchange_flow.py    # Exchange in/outflow
│   ├── jobs.py             # Scheduled monitoring
│   └── router.py           # /api/v1/onchain/*
├── ai/                     # AI prediction layer
│   ├── cloud_inference.py  # Cloud LLM predictions
│   ├── local_model.py      # Local model (Phase 3)
│   ├── feature_builder.py  # Feature engineering
│   └── router.py           # /api/v1/ai/*
├── trading/                # Trade execution
│   ├── exchanges/
│   │   ├── base.py         # Abstract interface
│   │   ├── binance.py      # Binance adapter
│   │   └── okx.py          # OKX adapter
│   ├── strategy_runner.py  # Signal -> execution
│   ├── risk_manager.py     # Position sizing + stop-loss
│   └── router.py           # /api/v1/trading/*
└── api/v1/router.py        # Aggregate all routers
```

## API Endpoints

### Market
- `GET /api/v1/market/overview` — Full market overview
- `GET /api/v1/market/price/{symbol}` — Symbol price
- `GET /api/v1/market/briefing` — Market briefing
- `GET /api/v1/market/klines/{symbol}` — K-line data
- `GET /api/v1/market/funding-rates` — Funding rate scan
- `GET /api/v1/market/defi-yields` — DeFi yields
- `GET /api/v1/market/trending` — Trending coins
- `GET /api/v1/market/fear-greed` — Fear & Greed index

### Analysis
- `GET /api/v1/analysis/predict/{symbol}` — Technical prediction
- `GET /api/v1/analysis/funding-scan` — Funding opportunities
- `GET /api/v1/analysis/defi-yields` — DeFi yield scan

### News
- `GET /api/v1/news/` — All news
- `GET /api/v1/news/{category}` — News by category

### On-chain
- `GET /api/v1/onchain/whales` — Whale transactions
- `GET /api/v1/onchain/exchange-flow` — Exchange flow
- `GET /api/v1/onchain/sopr` — SOPR metric

### AI
- `GET /api/v1/ai/predict/{symbol}` — AI-powered prediction
- `GET /api/v1/ai/features/{symbol}` — Feature set

### Trading
- `POST /api/v1/trading/execute` — Execute trade signal
- `GET /api/v1/trading/status` — Trading status

## Data Sources

| Source | API Key | Usage |
|--------|---------|-------|
| Desk3 | Not needed | Market data, news, indicators |
| Binance | Not needed (read) | Klines, funding rates, 24h ticker |
| CoinGecko | Not needed | Prices, trending, market cap |
| DefiLlama | Not needed | DeFi yields, TVL |
| OpenAI | Optional | AI predictions |
| Binance/OKX | For trading | Order execution |

## Environment Variables

```
DATABASE_URL=postgresql+asyncpg://bitinfo:bitinfo@localhost:5432/bitinfo
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=         # Optional: enables AI predictions
OPENAI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```
