# 数据契约层(public/data/v2/)字段说明

规则(章程 §0):前端只读这里的文件;每份契约必有 `schema_version / generated_at /
sources / status / blocked_why / data / disclaimer` 七个外层字段。
`status=DATA_BLOCKED` 时 `data` 可能为 null,前端必须显式展示 `blocked_why`,
永不伪装有数。改契约必须先改本目录文档再改代码(接口先行)。

| 契约文件 | 一句话 | 上游 |
|---|---|---|
| model_portfolio_state.json | 基金今天怎么样(NAV/现金/持仓/已平仓) | model_fund/* |
| trade_cards.json | 每笔交易病历卡(按周分组字段 week) | orders + decision_log |
| premarket_frame.json | 盘前帧(隔夜锚+前兆灯+观察名单) | overnight_anchor 等 |
| rotation_panel.json | 钱在往哪搬(板块连续性) | rotation_panel |
| red_flags.json | 观察名单的负面E1红旗 | red_flag_gate |
| battery.json | 观察名单六维体检 | full_battery |
| position_review.json | 每晚持仓纪律复审 | position_review |
| meta.json | 本次导出的总状态(COMPLETE/PARTIAL) | export_contracts |

生产者:experiments/execution_tracker/export_contracts.py(夜链末步)。
状态为草案 v0,字段规格的最终解释权 = Junyan(章程接口:研究契约)。
