# BitInfo 项目进度 Checkpoint

**更新时间**: 2026-04-16

## 项目概述
BitInfo 加密货币交易情报平台，FastAPI 后端 + Jinja2/HTML 前端。

## 服务器信息
- **IP**: 45.77.175.55
- **域名**: bbcoin.io（已配置 HTTPS）
- **SSH**: root / g9,Ktzj@7,7e$VWb
- **项目目录**: /opt/bitinfo
- **虚拟环境**: /opt/bitinfo/.venv
- **服务**: systemctl (bitinfo.service)
- **Nginx**: /etc/nginx/sites-available/bbcoin (域名) + crypto-data-core (/bi/ 路径)
- **访问方式**: https://bbcoin.io 或 http://45.77.175.55/bi/
- **HTTPS**: Let's Encrypt，到期 2026-07-15，自动续期
- **代理**: PROXY_URL 环境变量（SOCKS5），用于访问 Binance/OKX/Bybit 等受限 API

## 已完成的免费技能 (首页展示)
1. **market-briefing** — 加密货币市场实时简报（CoinGecko + Desk3 + Binance + DefiLlama）
2. **technical-analysis** — 技术分析引擎（RSI, MACD, 布林带, 均线）
3. **news-sentiment** — 新闻情报（多语言，情绪分类）
4. **prediction-markets** — 预测市场（Polymarket Gamma API）
5. **defi-yield-scanner** — DeFi 收益扫描器（DefiLlama）
6. **btc-quant-predictor** — BTC 量化短线预测（多因子评分）
7. **oi-signal** — OI 信号研判系统（五大交易所 OI 聚合 + 四象限评分）★ 新增
8. **open-interest** — 持仓量与衍生品原始数据
9. **surf-pro** — Surf 专业数据套件（需 credits，15 个子模块）

## OI 信号研判系统（最新完成）
- **后端**: `app/analysis/oi_signal.py` — 多交易所数据获取 + 历史追踪 + 四象限评分引擎
- **API**: `/api/v1/market/oi-signal/{symbol}` (GET)，支持 BTC/ETH/SOL
- **前端**: `app/static/oi-signal.html` — 仪表盘 + 象限图 + 信号检测 + 交易所明细
- **路由**: `/oi-signal` 页面路由在 `app/main.py`
- **首页跳转**: `index.html` 中 oi-signal 技能卡直接进入专属页面
- **功能**: 0-100 评分、方向判断、杠杆建议、背离检测、挤压预警、过热警报
- **数据源**: Binance, OKX, Bybit, Gate.io, Bitget

## 关键文件结构
```
app/
├── main.py                    # FastAPI 入口 + 页面路由
├── config.py                  # Pydantic Settings
├── common/
│   ├── skills.py              # 技能注册表
│   ├── cache.py               # Redis 缓存装饰器
│   ├── http_client.py         # httpx + SOCKS5 代理
│   └── database.py            # SQLAlchemy (可选，无 DB 也能运行)
├── market/
│   ├── router.py              # 市场数据 API 路由（含 /oi-signal）
│   └── sources/               # 各交易所数据源
│       ├── binance.py
│       ├── okx.py
│       ├── bybit.py
│       ├── gateio.py
│       ├── bitget.py
│       ├── coingecko.py
│       ├── defi_llama.py
│       ├── desk3.py
│       └── surf.py
├── analysis/
│   ├── oi_signal.py           # OI 信号引擎 ★
│   ├── router.py
│   └── ...
├── news/
├── briefing/
└── static/
    ├── index.html             # 首页
    ├── skill.html             # 通用技能详情页
    ├── daily.html             # 日报页
    ├── briefing.html          # 简报页
    └── oi-signal.html         # OI 信号研判页 ★
```

## 部署流程
```bash
# 1. 同步代码
sshpass -p 'g9,Ktzj@7,7e$VWb' rsync -avz -e 'ssh -o StrictHostKeyChecking=no' \
  --exclude '.git' --exclude '__pycache__' --exclude '.venv' --exclude '.cursor' --exclude '.env' \
  /Users/wrok/bitinfo/ root@45.77.175.55:/opt/bitinfo/

# 2. 重启服务
sshpass -p 'g9,Ktzj@7,7e$VWb' ssh root@45.77.175.55 'systemctl restart bitinfo'
```

## 注意事项
- 服务器无 PostgreSQL，所有 DB 操作通过 `db_available()` 检查自动跳过
- 前端 API 路径通过 `BASE` 变量动态适配（支持 /bi/ 前缀和根路径）
- `.env` 文件在服务器上，不要覆盖（含 PROXY_URL 等配置）
- funding_rate 和 get_futures_ticker 内部会追加 "USDT"，传入 symbol 应为 "BTC" 非 "BTCUSDT"

## 待办 / 可扩展
- [ ] 前端页面美化（响应式优化、暗色主题微调）
- [ ] 更多币种支持（目前 BTC/ETH/SOL）
- [ ] OI 历史持久化（当前内存中，服务重启清空）
- [ ] 定时任务自动收集 OI 快照（每 5 分钟）
- [ ] WebSocket 实时推送
