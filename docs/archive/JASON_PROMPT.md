# AR Platform — UI Engineer Onboarding Prompt

将以下内容完整粘贴给 Claude，然后让 Claude 帮你改 Dashboard.jsx。

---

## 项目背景

你正在帮助改善一个 **AI 驱动的股票研究平台（AR Platform）** 的前端 UI。这是一个个人量化研究工具，用于追踪 A 股和港股的 5 只核心股票：中际旭创、腾讯、网易、百济神州、比亚迪。

平台有一套完整的后端 Python 数据管道（GitHub Actions 每天自动运行），前端只需要读取 JSON 文件展示数据。**你只需要改 `src/Dashboard.jsx`，不要动任何其他文件。**

---

## 技术栈

- **框架**：React（Vite 构建）
- **样式**：100% 内联样式（inline styles），没有 CSS 文件，没有 Tailwind，没有任何 UI 库
- **图表**：Recharts（已安装）
- **图标**：Lucide React（已安装）
- **部署**：GitHub Pages，push 到 main 自动部署
- **数据来源**：`public/data/*.json`（静态 JSON，每天由 GitHub Actions 更新）

---

## 文件结构

```
src/Dashboard.jsx          ← 唯一需要改的文件（约 7300 行）
public/data/
  market_data.json         ← 实时价格、技术指标、基本面
  vp_snapshot.json         ← VP 评分（5维度 0-100 分）
  confluence.json          ← 多信号综合评分
  daily_decision.json      ← 今日交易决策（BUY_WATCH / HOLD / EXIT等）
  position_sizing.json     ← 仓位建议
  profit_scissors.json     ← 利润剪刀差分析（NI/Rev 比率）
  rdcf_*.json              ← 逆向 DCF 估值（每只股票一个文件）
  signals_*.json           ← 技术信号（每只股票一个文件）
  fin_*.json               ← 财务报表数据
  ohlc_*.json              ← K 线 OHLCV 数据
  backtest_results.json    ← 回测结果
  trades.json              ← 模拟交易记录
  positions.json           ← 当前持仓
  signal_quality.json      ← 信号质量统计
  vp_history.json          ← VP 分数历史
  watchlist.json           ← 股票列表配置（source of truth）
```

---

## 颜色系统（重要）

Dashboard 有深色/浅色两套主题，通过 `C` 对象传递给每个组件：

```js
// 深色主题（darkMode=true）
const DARK = {
  bg:      '#0f1117',   // 页面背景
  card:    '#1a1f2e',   // 卡片背景
  border:  '#2a3050',   // 边框
  text:    '#e2e8f0',   // 主文字
  sub:     '#8892a4',   // 次要文字
  green:   '#22c55e',
  red:     '#ef4444',
  yellow:  '#f59e0b',
  blue:    '#3b82f6',
  accent:  '#6366f1',
}
// 浅色主题（darkMode=false）
const LIGHT = { ... }
```

所有组件接收 `C` 作为 prop，用 `C.bg`、`C.text` 等引用颜色，**不要硬编码颜色值**。

---

## 主要组件结构

```
Dashboard (主入口)
├── 顶部导航栏（深/浅色切换、中/英切换、数据同步状态）
├── Scanner        — 市场总览（VP评分、价格、信号、宏观压力测试）
├── Screener       — 全市场选股（A股/港股约10000只）
├── Research       — 个股深度研究
│   ├── ProfitScissors   — 利润剪刀差（NI/Rev 5年分析）
│   ├── ReverseDCF       — 逆向 DCF 估值
│   ├── SwingSignal      — 技术摆动信号
│   ├── ConsensusPanel   — 分析师共识
│   ├── TechnicalAnalysis — 技术指标
│   ├── FinancialStatements — 财务报表
│   └── FlowPanel        — 资金流向
├── TradingDesk    — 交易台（仓位建议、wrongIf监控、信号质量）
│   └── PaperTrading     — 模拟交易记录
├── MorningReport  — AI 晨报
├── News           — 宏观/组合新闻
├── Backtest       — 策略回测
└── DeepResearch   — AI 深度研究（UBS框架）
```

---

## 你需要完成的 UI 改进任务

### 优先级 1 — 导航与整体布局

**1.1 侧边栏导航**
当前是顶部 tab 切换，改为左侧固定侧边栏：
- 图标 + 文字（中文）
- 当前选中 tab 高亮
- 折叠/展开功能（collapsed 时只显示图标）
- 侧边栏宽度展开 200px，折叠 56px

**1.2 页面宽度**
当前内容区域过窄，改为充分利用屏幕宽度：
- 主内容区 `max-width` 从固定值改为 `calc(100vw - 侧边栏宽度 - 32px)`
- 卡片采用 CSS Grid 自适应列数

---

### 优先级 2 — Scanner 页面

**2.1 股票卡片重设计**
当前 5 只股票竖排展示，改为 **2列 Grid 卡片布局**：
- 每张卡片显示：股票名称、VP Ring 评分圆环、当日涨跌幅、信号标签
- 卡片点击跳转到该股票的 Research 页

**2.2 VP Ring 优化**
`VPRing` 组件（第 458 行）：
- 增加内圈文字显示分数变化（Δ+3 绿色 / Δ-2 红色）
- Ring 颜色根据分数：70+ 绿，50-69 黄，<50 红

---

### 优先级 3 — Research 页面

**3.1 标签页内导航**
Research 页内容很多（估值/财务/技术/资金流），加一个内部 tab 栏：
- 概览 / 估值 / 财务 / 技术 / 资金
- 切换时只渲染对应部分，减少首屏渲染量

**3.2 ProfitScissors 表格样式**
`ProfitScissors` 组件（第 5694 行）：
- NI/Rev ratio 列：≥1.5× 绿色背景，1.0-1.5 黄色，<1.0 红色
- 表头固定，数据行交替色
- 在表格下方加一个迷你趋势折线图（用 Recharts LineChart）

---

### 优先级 4 — TradingDesk 页面

**4.1 仓位建议卡片**
`position_sizing.json` 里有每只股票的仓位建议，改为可视化展示：
- 横向进度条显示建议仓位比例
- 颜色区分：AGGRESSIVE（绿）/ MODERATE（黄）/ CONSERVATIVE（红）

**4.2 信号质量表**
`signal_quality.json` 里有每类信号的胜率统计，加一个表格：
- 列：信号名称 / 触发次数 / 胜率 / 平均盈亏
- 胜率色阶：>60% 绿 / 40-60% 黄 / <40% 红

---

### 优先级 5 — 全局细节

**5.1 加载骨架屏**
当前数据加载时直接显示空白，改为骨架屏（灰色脉冲动画占位）

**5.2 空数据状态**
当 JSON 文件数据缺失时，显示友好的空状态提示，而不是报错或空白

**5.3 数字格式化**
统一数字展示：
- 价格：保留 2 位小数
- 百分比：带 `+/-` 符号，1 位小数
- 大数字（市值）：自动换算为"亿"单位

---

## 工作方式建议

1. 每次只改一个组件，改完本地 `npm run dev` 验证效果
2. 用 `// Jason: ` 注释标记你改过的地方，方便 review
3. 改完 commit：`git add src/Dashboard.jsx && git commit -m "ui: 描述" && git push origin main`
4. push 后约 2 分钟 GitHub Pages 自动部署，在线地址可以验证效果

## 绝对不要碰的文件
- `scripts/` 下所有 Python 文件
- `.github/workflows/` 
- `public/data/` 下的 JSON 文件
- `vite.config.js`、`package.json`
