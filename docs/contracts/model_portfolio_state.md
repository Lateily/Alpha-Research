# model_portfolio_state.json(草案 v0,待 Junyan 定稿)

大白话:模型基金的当日全景。paper_only 恒为 true;human_shadow 永不出现在此。

data 字段:
- initial_capital 初始资金(1,000,000)
- cash 现金余额 · nav_series 净值数组(date/nav/cash/n_positions/daily_return/cum_return;
  2026-09 起新行另带 period_return / basis_date / sessions_covered / gap_sessions / calendar_source)。
  **daily_return 只在 sessions_covered==1(上一行就是上一个交易日)时有值**;跨多个交易日、中间有
  DATA_BLOCKED 行或日历无法证明时为 null,跨期收益放 period_return。旧行没有这些字段,以
  nav_session_audit 为准。
- nav_latest 最新一行(前端首屏大数字用它,禁止自己算)
- nav_session_audit 交易日连续性审计(2026-09 起):contiguity ∈ CONTIGUOUS / GAPPED / UNVERIFIABLE,
  missing_sessions(没有 NAV 行的交易日)、multi_session_daily_return_dates(旧行的 daily_return
  实为跨多日收益)、calendar_sources / calendar_caveat。非 CONTIGUOUS ⇒ 顶层 data_quality=PARTIAL,
  degraded_sources 带 why=NAV_SESSION_GAP 或 NAV_SESSION_CALENDAR_UNAVAILABLE。账本不改写,只披露。
- open_positions / closed_trades 持仓与已平仓订单原样(entry/stop/target/qty…)
- closed_trades_n 已平仓笔数 · win_rate_note 胜率免谈提示(n<30 时前端必须原样展示)

前端四问(章程):读本文件;字段缺失显示 DATA_BLOCKED;generated_at 必须上屏;
数字必须与 nav_history.json 末行一致(验收标准)。
