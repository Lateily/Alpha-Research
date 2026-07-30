# trade_cards.json(草案 v0,待 Junyan 定稿)

大白话:每笔交易一张病历卡,按 week 字段(YYYYMM 周)分组展示,不堆总表。

每张卡:ticker/name/status(filled|closed|cancelled)/fill_date/entry/qty/
stop(灾难线)/target/exit_date/exit_price/realized_r/
reasoning_trail(最近≤6条决策日志,含两票与复核记录)/week(分组键)。

展示要求:closed 卡必须显示 realized_r;filled 卡必须显示距 stop 百分比
(由前端用最新价计算,最新价来源 = model_portfolio_state 的 nav 定盘口径,
不许调外部行情)。免责句常显。
