# BitInfo 项目进度检查点

> 生成时间：2026-04-16 02:30（Asia/Shanghai）
> 工作区：/Users/wrok/bitinfo
> Git：main 分支，2 commits，76 文件

---

## 项目简介

BitInfo 是一个数字货币智能分析平台，融合多个 AI 技能帮助用户发现有潜力的数字货币和收益机会。

**技术栈：** Python FastAPI + Jinja2/HTML 前端 + 多数据源（Binance, CoinGecko, DefiLlama, Desk3, Alternative.me）

---

## 启动命令

```bash
cd /Users/wrok/bitinfo
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8899 --reload
```

- 首页：http://localhost:8899/
- 日报：http://localhost:8899/daily
- 技能详情：http://localhost:8899/skill?id=<skill-id>
- API 文档：http://localhost:8899/docs

---

## 已完成功能

### 1. 基础架构
- FastAPI 应用（`app/main.py`）
- 统一配置（`app/config.py`）
- 安全 HTTP 客户端 + 出站白名单（`app/common/http_client.py`, `app/common/endpoints.py`）
- 技能注册中心（`app/common/skills.py`）
- Redis 缓存层（`app/common/cache.py`）
- PostgreSQL + SQLAlchemy 异步 ORM（`app/common/database.py`）
- APScheduler 定时任务（`app/common/scheduler.py`）

### 2. 已集成技能（5个上线）
| 技能 ID | 名称 | API 端点 | 状态 |
|---|---|---|---|
| `market-briefing` | 市场综合简报 | `/api/v1/briefing/live` | ✅ 上线 |
| `btc-quant-predictor` | BTC 量化短线预测 | `/api/v1/analysis/btc-predict` | ✅ 上线 |
| `news-sentiment` | 新闻情绪分析 | `/api/v1/news/history` | ✅ 上线 |
| `defi-yield-scanner` | DeFi 收益扫描 | `/api/v1/analysis/defi-yields` | ✅ 上线 |
| `funding-rate-monitor` | 资金费率监控 | `/api/v1/analysis/funding-rates` | ✅ 上线 |

### 3. 前端页面
| 页面 | 文件 | 路由 | 功能 |
|---|---|---|---|
| 首页 | `app/static/index.html` | `/` | 技能列表卡片 + 日报入口 |
| 日报 | `app/static/daily.html` | `/daily` | 独立日报（聚合所有板块） |
| 技能详情 | `app/static/skill.html` | `/skill?id=...` | 每个技能的完整可视化报告 |
| 简报 | `app/static/briefing.html` | `/briefing` | 旧版简报页 |

### 4. 日报板块（`daily.html`）
1. 💰 核心价格（BTC/ETH/SOL）
2. 😱 市场情绪（恐惧贪婪仪表盘 + 历史对比网格）
3. 🌍 全球市场（总市值、BTC/ETH 市占率）
4. 🔥 趋势币种
5. 📈 BTC 技术分析 4H（RSI/MACD/布林带/均线/金叉/趋势）
6. 🎯 BTC 15分钟量化预测（方向仪表 + 置信度条 + 牛熊比 + 信号表 + 止损止盈卡片）
7. 💰 资金费率异常
8. 🌾 DeFi 收益机会
9. 📰 新闻摘要
10. 🔄 BTC 周期综合分析
11. 📋 30 项周期指标详细表
12. 🪙 山寨季指数（数字 + 表格 + 总市值）
13. 📌 综合研判（周期 + Puell + 恐惧贪婪 + BTC 市占率 + 技术面 + 15分钟预测 + 操作建议）
14. ⚠️ 风险提示

---

## 项目结构

```
/Users/wrok/bitinfo/
├── app/
│   ├── main.py              # FastAPI 入口 + 路由注册
│   ├── config.py             # 配置
│   ├── api/v1/router.py      # API 路由聚合
│   ├── common/               # 公共模块（HTTP、缓存、DB、技能注册）
│   ├── market/               # 行情数据（Binance、CoinGecko、DefiLlama、Desk3）
│   ├── analysis/             # 分析模块（技术指标、BTC预测、资金费率、DeFi收益）
│   ├── briefing/             # 简报生成器（聚合所有数据源）
│   ├── news/                 # 新闻抓取 + 情绪分析
│   ├── onchain/              # 链上数据（交易所流入流出、鲸鱼追踪）
│   ├── trading/              # 交易执行（Binance/OKX 交易所）
│   ├── ai/                   # AI 推理（云端 + 本地模型）
│   └── static/               # 前端 HTML 页面
├── tests/
├── venv/                     # Python 虚拟环境
├── requirements.txt
├── docker-compose.yml
└── CHECKPOINT.md             # 本文件
```

---

## 已知问题 / 注意事项

1. **浏览器缓存** — 改前端后需要 `Cmd+Shift+R` 强刷
2. **上下文丢失** — 对话总结后可能导致代码覆盖回退，已通过 git 解决
3. **数据源限流** — CoinGecko 免费 API 有请求频率限制
4. **Desk3 数据** — BTC 周期指标来自 Desk3 API，可能偶尔不可用

---

## 下一步可做的事

- [ ] 集成更多 OpenClaw 技能（如鲸鱼追踪、交易所流入流出等）
- [ ] 日报定时生成 + 推送通知
- [ ] 用户自定义看板（选择关注的板块）
- [ ] 移动端适配优化
- [ ] 部署到云服务器

---

## 新对话恢复指引

在 Cursor 新对话中说：
> "请读取 /Users/wrok/bitinfo/CHECKPOINT.md 了解项目当前进度，然后继续工作"
