# Macro OS M0-B 数据可信层

> 状态:`DELIVERED_UNWIRED / CALIBRATING`。代码和离线验收已具备;尚未接入夜链、盘前帧或生产调度,也没有直接阻断权。

## 1. 本批解决的问题

M0-A 规定了谁是官方来源、谁只是镜像,但没有证明一次具体抓取真的来自那个上游,也没有保存修订前的历史版本。M0-B 第一批增加四件实物:

1. `storage.py`:SQLite 历史仓,原始响应、观测值、抓取尝试和来源身份全部只追加。
2. `collectors.py`:BLS、BEA、Cboe 与 FRED/ALFRED 适配器。
3. 来源绑定:provider、`independence_group`、E 级和角色只从经 M0-A 校验的注册表读取;采集器无权自报。
4. `source_health.json`:每项数据同时报告观测日期、最近检查时间、两种新鲜度、快照数、vintage 数和修订期数。

这一层只回答“数据是什么、什么时候可见、来自哪里、是否过期”。它不生成 `macro_state`、MRG 结论或交易动作。

## 2. 历史仓

默认位置:`data_history/macro_os.sqlite3`。该目录不进 Git。

| 表 | 保存内容 | 覆盖规则 |
|---|---|---|
| `source_identities` | 注册表哈希、provider、独立供应商分组、E 级、角色 | 同一来源定义变化时产生新 identity |
| `raw_snapshots` | HTTPS 原始响应字节、最终来源主机、内容哈希、采集器版本 | 内容与来源身份联合寻址;相同正文不重复覆盖 |
| `observations` | 规范 series、原生 series、观测期、vintage、原始值文本、数值和单位 | 新 vintage 追加;旧值不更新 |
| `fetch_attempts` | 成功、阻断、源故障或解析失败及检查时间 | 每次运行单独留痕 |

四张表均有 `UPDATE`/`DELETE` 拒绝触发器。记录哈希覆盖来源元数据、快照元数据、观测内容和抓取结果;`verify_integrity()` 会重算。SQLite 文件与代码在同一台机器上时仍不构成外部公证,因此这里提高可审计性,不声称对拥有整个文件写权限的本机攻击者绝对防篡改。

完整历史文件每次都保存原始快照和抓取尝试;规范观测只在首次出现或数值/属性发生变化时追加。这避免 Cboe/FRED 每天返回完整历史时,把数千条未变记录重复投影进 SQLite。

本批的版本历史从每个来源首次成功抓取时开始。它会保留此后看到的修订,但未批量回灌 ALFRED/BLS/BEA 在平台上线前的全部发布时点;源注册表的 `vintage_support` 表示上游能力,不表示本地历史已经回填完整。

## 3. 首批采集覆盖

| 来源 | 当前用途 | 证据边界 | 密钥 |
|---|---|---|---|
| BLS Public Data API | 非农、失业率、时薪、CPI、PPI、JOLTS | 官方 E1 | 可匿名;`BLS_API_KEY` 可选 |
| BEA Public API | 实际 GDP、核心 PCE 价格指数 | 官方 E1 | `BEA_API_KEY` 必需 |
| Cboe VIX history | VIX 日收盘 | 官方 E1 | 无 |
| FRED/ALFRED | 2Y、10Y、10Y 实际利率、IG/HY OAS | E2 镜像/市场序列,不得冒充 BLS/财政部原发布 | `FRED_API_KEY` 必需 |

参考实现只使用来源机构文档:[BLS API v2](https://www.bls.gov/developers/api_signature_v2.htm)、[BEA API](https://apps.bea.gov/api/signup/)、[FRED observations](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)、[Cboe VIX](https://www.cboe.com/tradable_products/vix/vix_historical_data/)。

中国国家统计局、人民银行、ISM 和 Census 仍未进入本批生产适配器。Tushare 宏观接口继续作为 E2 镜像原料,不被本批自动升级成官方 E1。市场共识双源也仍为 `DATA_BLOCKED`。

## 4. 新鲜度与版本

健康表同时检查:

- `observation_age_seconds`:数据所代表时期距现在多久;
- `fetch_age_seconds`:平台距上次真实检查多久;
- `max_observation_age_seconds`:按日/月/季频率设置的首版保守阈值;
- `max_fetch_age_seconds`:采集本身允许的最长空窗;
- `version_stats`:快照、vintage、观测期和发生修订的时期数量。

源返回 2xx 但结构错误时,原始正文仍进入历史仓,抓取状态必须是 `DATA_INVALID`;错误正文不得产生观测值。缺密钥为 `DATA_BLOCKED`,网络或 HTTP 故障为 `SOURCE_DOWN`,两者都不能伪装成空数据成功。

来源定义发生变化后,旧观测保留它入库时的 provider、独立性分组和 E 级;健康表同时显示当前注册表期望值,`source_identity_current=false` 时强制标为 `STALE`,必须按新身份重抓。

2026-08-07 真实源冒烟结果:Cboe 官方 CSV 成功入库 9,245 个历史观测,同一正文第二次检查时观测行数保持 9,245、抓取尝试增加为 2;BLS 官方 API 在当前出口返回 HTTP 403,按 `SOURCE_DOWN` 留痕。BEA/FRED 密钥源本轮未做在线冒烟,缺密钥路径已离线验证为 `DATA_BLOCKED`。

## 5. 运行

只跑无需密钥的首批官方源:

```bash
python3 experiments/macro_os/collectors.py \
  --source bls_public_api \
  --source cboe_vix
```

指定本地数据库和健康输出:

```bash
python3 experiments/macro_os/collectors.py \
  --db data_history/macro_os.sqlite3 \
  --health-out public/data/v2/macro/source_health.json
```

退出码:

- `0`:本次请求全部健康;
- `2`:健康文件已写,但存在 `STALE`、`DATA_BLOCKED` 或源故障;
- `1`:契约、数据库或运行配置本身不合法,本轮拒绝。

离线验收:

```bash
AR_OFFLINE=1 python3 tests/test_macro_m0b_offline.py
```

## 6. 校准期边界

`source_health.json` 固定携带:

```json
{
  "mode": "CALIBRATING",
  "policy": {
    "formal_blocking_authority": false,
    "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
    "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"]
  }
}
```

这不是说明文字,而是后续消费者必须检查的机器字段。M0-B 未接夜链,当前还没有消费者可以依据本文件改变晋级、下单或持仓状态。

## 7. 后续工程

1. M0-B2:正式接入 Census、国家统计局、人民银行、ISM;双源市场共识与 release calendar。
2. M0-B3:自适应调度、重大数据发布延迟监控、append-only 预期登记时间戳。
3. M1-A:在校准规则下生成 GLOBAL/US 与 CHINA 两套 `macro_state` 及 MRG 原料。
4. M1-B:组合与行业消费者只读状态和 freshness;校准期只改标签和风险预算上下文。

不是买卖指令;研究信号,human executes。
