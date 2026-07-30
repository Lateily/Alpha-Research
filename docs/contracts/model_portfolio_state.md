# model_portfolio_state.json(草案 v0,待 Junyan 定稿)

大白话:模型基金的当日全景。paper_only 恒为 true;human_shadow 永不出现在此。

data 字段:
- initial_capital 初始资金(1,000,000)
- cash 现金余额 · nav_series 逐日净值数组(date/nav/cash/n_positions/daily_return/cum_return)
- nav_latest 最新一行(前端首屏大数字用它,禁止自己算)
- open_positions / closed_trades 持仓与已平仓订单原样(entry/stop/target/qty…)
- closed_trades_n 已平仓笔数 · win_rate_note 胜率免谈提示(n<30 时前端必须原样展示)

前端四问(章程):读本文件;字段缺失显示 DATA_BLOCKED;generated_at 必须上屏;
数字必须与 nav_history.json 末行一致(验收标准)。
