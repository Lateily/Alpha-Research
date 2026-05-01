# DATA SOURCES CHECKLIST — 接入操作手册

> **目标读者：** Junyan 亲自执行（明天）。每条都包含**去哪里申请、怎么注册、
> 怎么获取 key、放哪、注意事项**。Claude 之后接你给的 key 写 fetcher。
>
> **优先级：** P0 = 立刻接入；P1 = 一周内；P2 = 看 USP 节奏；P3 = 之后。

---

## 优先级总览

| # | 数据源 | 优先级 | 用途 | 你需要做的 |
|---|---|---|---|---|
| 1 | **Tushare Pro** | P0 | A 股全维度行情/财务/资金流 | 购买 + 拿 token |
| 2 | **巨潮资讯网** | P0 | A 股年报/季报/公告 PDF | 无需注册（公开抓取）|
| 3 | **财联社/东方财富新闻** | P0 | 实时新闻 + catalyst 识别 | 评估爬取 vs 第三方 API |
| 4 | **SEC EDGAR** | P1 | 美股 10-K/10-Q/8-K | 无需注册 |
| 5 | **HKEx Disclosure** | P1 | HK 个股公告 | 无需注册 |
| 6 | **雪球评论 + 东财股吧** | P2 | 国内叙事追踪（USP 核心） | 反爬有难度，评估 |
| 7 | **Choice 金融终端** | P3 | Wind 替代品 | 看预算 |

---

## 1. Tushare Pro (P0 — A 股最重要数据源)

### 申请流程

1. **注册账户：** https://tushare.pro/register
2. **完成基本任务获取积分：** 注册 100 分；填写资料 +20；新手任务 +20
3. **购买高级账户：** https://tushare.pro/document/1?doc_id=290
   - **个人开发者：500 积分** 可解锁多数高频接口（行情 + 财务）
   - 如果要实时分钟级 + Level-2 数据，需要 **企业账户（约 ¥3000-8000/年）**
   - **建议：先买 500 积分账户跑试用，~ ¥200**
4. **获取 token：** 登录后在 https://tushare.pro/user/token 右上角
5. **测试连接：** Python 安装 `pip install tushare`，然后：
   ```python
   import tushare as ts
   pro = ts.pro_api('YOUR_TOKEN')
   df = pro.daily(ts_code='000001.SZ', start_date='20260101')
   print(df.head())
   ```

### Token 放哪

```bash
# 1. 本地开发：~/.zshrc 或 ~/.bashrc 加：
export TUSHARE_TOKEN='你的token'
source ~/.zshrc

# 2. GitHub Actions：
# 仓库 Settings → Secrets and variables → Actions →
# New repository secret →
#   Name: TUSHARE_TOKEN
#   Value: 你的token
```

### 接入后我会做

- 写 `scripts/fetch_tushare.py` 替代部分 yfinance 调用（A 股）
- A 股 daily/weekly/monthly 全部覆盖
- 财务三张表（利润/资产负债/现金流）实时拉取
- 北向资金流入流出（每日级）
- 龙虎榜 / 大宗交易（如积分够）

### 注意事项

- 接口频率限制：500 积分账户 100 次/分钟
- 历史回溯：500 积分通常给 5 年；更早需要企业账户
- 港股美股**不在 Tushare 主接口内**（用 yfinance/EDGAR 走另路）

### 完成 checklist
- [ ] 注册账户
- [ ] 充值积分 / 升级账户
- [ ] 拿到 token
- [ ] 本地 `~/.zshrc` 加环境变量
- [ ] GitHub Secrets 加 `TUSHARE_TOKEN`
- [ ] 跑一次 sanity check 测试

---

## 2. 巨潮资讯网（P0 — A 股年报/季报 PDF）

### 为什么需要

A 股年报/季报/重大事项公告的官方权威来源。Tushare 提供财务数字但不提供
原文 PDF。我们需要 PDF 来：
- LLM 直接读管理层讨论 (MD&A)
- 提取业绩说明会 Q&A
- 分析风险因素章节

### 接入方式

**无需注册** — 公开抓取。

**入口：** http://www.cninfo.com.cn/new/disclosure/stock?stockCode=300308

**API（非官方但稳定，社区在用）：**
```python
# 巨潮的 announcement 列表 API
import requests
url = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
params = {
    'stock': '300308',
    'tabName': 'fulltext',
    'pageSize': 30,
    'pageNum': 1,
    'category': 'category_ndbg_szsh',  # 年度报告
}
resp = requests.post(url, data=params)
announcements = resp.json()['announcements']
# 每条有 'adjunctUrl' 字段，拼上 'http://static.cninfo.com.cn/' 就是 PDF 直链
```

### 注意事项

- 无 rate limit 文档但建议 ≥1s/请求避免被封
- PDF 文件大（年报常 5-20MB），存储 + OCR/解析有成本
- 类目代码：`category_ndbg_szsh`(年报), `category_yjdbg_szsh`(一季报),
  `category_bndbg_szsh`(半年报), `category_sjdbg_szsh`(三季报)

### 接入后我会做

- 写 `scripts/fetch_cninfo.py` 自动下载年报 PDF
- 集成 LLM PDF reader（用 Claude/Gemini 长文档能力）
- 抽取 MD&A + 风险因素 + 业绩说明会 Q&A
- 存到 `public/data/filings_<ticker>_<year>.json`

### 完成 checklist
- [ ] **不需要你做任何事** — 我直接接（明天接入 Tushare 后）

---

## 3. 财联社 + 东方财富新闻（P0 — Catalyst 识别 + 国内叙事追踪）

### 为什么需要

Catalyst 识别要求**实时**捕捉公告 + 行业事件 + 政策风向。新闻流是这些
catalyst 的最早出现地。

**关键作用：**
- THESIS_PROTOCOL Step 1 (CATALYST) 的输入源
- Layer D 国内叙事追踪（USP 核心）

### 选项对比

| 选项 | 成本 | 稳定性 | 实时性 | 推荐度 |
|---|---|---|---|---|
| 财联社官方 API | ¥3000+/月（机构版） | 高 | 秒级 | 不推荐（贵） |
| 财联社电报爬取 | 0 | 中（反爬） | 分钟级 | ⭐⭐⭐ |
| 东方财富新闻爬取 | 0 | 中 | 分钟级 | ⭐⭐⭐ |
| 同花顺新闻爬取 | 0 | 中 | 分钟级 | ⭐⭐ |
| 第三方聚合（聚合数据等） | ¥几百/月 | 中 | 分钟级 | ⭐⭐ |
| **推荐方案：东财 + 财联社双爬取互补** | 0 | 中 | 分钟级 | ⭐⭐⭐⭐ |

### 接入方式

**财联社电报：**
```python
# 财联社电报每日新闻流（公开 endpoint）
url = 'https://www.cls.cn/nodeapi/updateTelegraphList'
# 每分钟新增电报，含分类 tag
```

**东方财富股吧（按股票）：**
```python
# 东财每只股票的新闻 + 公告
# https://so.eastmoney.com/news/s?keyword=300308
# https://emrnweb.eastmoney.com/api/v1/stock/{code}/notices
```

### 注意事项

- 反爬可能升级（添加 User-Agent / 代理 / 频率限制）
- 文本质量：财联社电报偏简短（适合 catalyst flag），东财评论偏散户口吻
  （适合叙事追踪）
- 处理：先简单 keyword filter（预定义 catalyst keywords），再 LLM
  深度分类

### 完成 checklist
- [ ] **不需要你做任何事** — 我直接接

---

## 4. SEC EDGAR（P1 — 美股 10-K/10-Q/8-K）

### 为什么需要

美股关键股票（NVDA, MSFT, GOOGL, AMZN, META, TSLA 等）的财务报告 +
8-K 即时公告。Innolight 的 thesis 需要追踪 NVDA Blackwell 量产节奏 →
EDGAR 是 NVDA 8-K 的官方源。

### 接入方式

**无需注册（公开 API）。**

**API：** https://www.sec.gov/edgar/sec-api-documentation

```python
# 例：拉 NVDA 最近 10 条 filing
import requests
headers = {'User-Agent': 'YourEmail@domain.com'}  # SEC 要求 UA 含 email
url = 'https://data.sec.gov/submissions/CIK0001045810.json'  # NVDA
resp = requests.get(url, headers=headers)
recent = resp.json()['filings']['recent']
# 每条 filing 的 8-K 内容: https://www.sec.gov/Archives/edgar/data/{cik}/{accessionNo}.txt
```

### 完成 checklist
- [ ] **不需要你做任何事**（无需注册，但需要给我**你的邮箱**作为 SEC
      User-Agent 要求）
- [ ] 你提供：邮箱地址 (一次性，用来加 SEC API User-Agent)

---

## 5. HKEx Disclosure（P1 — HK 公告）

### 为什么需要

700.HK Tencent / 9999.HK NetEase / 6160.HK BeOne 三只 HK 股票的公告
官方源。

### 接入方式

**无需注册。**

**API：** https://www.hkexnews.hk/index.htm
- HKEx Disclosure 提供 RSS feed + JSON endpoint
- 大多数 PDF 公告免费下载

```python
# 按股票代码搜索公告
# https://www1.hkexnews.hk/search/titleSearchServlet.do?stockCode=00700
```

### 完成 checklist
- [ ] **不需要你做任何事** — 我直接接

---

## 6. 雪球评论 + 东财股吧（P2 — USP 核心数据源）

### 为什么需要 — **这是 USP 核心**

Layer D 国内叙事追踪 = 我们差异化的核心数据源。雪球 + 东财股吧 是
**中国散户 + 部分专业投资者公开讨论的最大场所**。

数据用途：
- 国内叙事 vs 国际定价 gap 分析
- 散户买入热度（先于龙虎榜出现的 leading signal）
- 题材轮动节奏识别

### 接入难度（重要！）

| 项 | 难度 | 说明 |
|---|---|---|
| 反爬升级 | 高 | 雪球有较严反爬，需代理 IP 池 |
| 评论质量信噪比 | 中 | 大量水军 + 噪音 |
| 法律合规 | 中 | 公开数据但条款限制 |
| 推荐路径 | — | 先小批量试点，再决定是否投入 |

### 推荐三种接入方式（按成本递增）

**方式 A — 个股精选爬取（小流量）**
- 只爬 watchlist 5 只股票的雪球讨论 + 东财股吧
- 每 30 分钟一次，每次 30 条
- 成本：低；反爬风险：可控

**方式 B — 第三方数据服务（如 Datayes / 同花顺 Level-2）**
- 部分服务整理过 + 已合规
- 成本：¥几百-几千/月
- 反爬风险：无

**方式 C — 自建爬虫 + 代理池**
- 全市场覆盖
- 成本：高（代理 IP 费用 + 维护）

**建议：先 A 跑 4 周观察数据质量，再决定 B/C。**

### 完成 checklist
- [ ] 你决定先走方式 A 还是直接评估方式 B
- [ ] 如果方式 A：我直接接，不需要你做事
- [ ] 如果方式 B：你提供 token

---

## 7. Choice 金融终端（P3 — Wind 替代品）

### 适用场景

如果发现 Tushare 的财务数据/分析师评级覆盖不够，Choice 是 Wind 的
便宜替代品（约 ¥1500-3000/年个人版，Wind 个人版要 ¥10000+）。

### 申请流程

- 网址：https://choice.eastmoney.com/
- 个人版：联系销售
- 校园版：在校大学生有时有优惠

**目前不急 — 等 Tushare 真的不够再上。**

### 完成 checklist
- [ ] **暂不操作** — 等 Tushare 跑 4 周后评估

---

## 你明天的最小执行清单（按时间顺序）

```
☐ 0. 决定 Tushare 账户层级（500 积分 ¥200 vs 企业版 ¥3000+）
☐ 1. 上 Tushare Pro 注册 + 充值 + 拿 token (~30 min)
☐ 2. ~/.zshrc 加 export TUSHARE_TOKEN='...'
☐ 3. GitHub Secrets 加 TUSHARE_TOKEN
☐ 4. 给 Claude 你的邮箱（用来填 SEC EDGAR User-Agent）
☐ 5. 决定雪球/东财评论接入方式（A 试点 / B 第三方 / 暂缓）
☐ 6. （optional）跑一次 Tushare sanity check（python 一行测试）
```

完成后告诉 Claude，**我接管所有 fetcher 实现 + GitHub Actions 集成**。

---

## 我接入后会做的（不需要你管）

- Tushare：替代 A 股 yfinance 调用 + 增加财务三表 + 北向资金
- 巨潮：年报/季报 PDF 抓取 + LLM MD&A 抽取
- 财联社/东财新闻：实时爬取 + catalyst keyword 预筛 + LLM 分类
- SEC EDGAR：美股 8-K 实时 + LLM 重要性评级
- HKEx：HK 公告抓取
- 雪球/东财评论（如果走方式 A）：5 股 watchlist 试点

每接入一个数据源都会：
1. 写 `scripts/fetch_<source>.py`
2. 加进 `.github/workflows/fetch-data.yml` 流水线
3. 输出到 `public/data/<source>_<ticker>.json`
4. 更新 `STATUS.md` Bridge 2 进度
5. 在 watchlist 5 只股票上跑 calibration anchor 验证
