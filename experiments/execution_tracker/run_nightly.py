#!/usr/bin/env python3
"""
run_nightly.py — Nightly v4:同日快照、事务账本与 staging 发布流水线。

v4 根修复:
  1. official_sample 唯一确定 target_trade_date,所有步骤共享同一 run_id/目标日;
  2. 注册与判分分别走可恢复 WAL,恢复完成后才允许 preflight 放行;
  3. 全部引擎在隔离 staging 运行,只有 COMPLETE 才按发布日志原子替换别名;
  4. 步骤状态由退出码、结构化产物、日期、run_id 与内部 DATA_BLOCKED 共同判定;
  5. 崩溃后恢复未完成事务/发布,不留下半新半旧的可见流水线状态。

编排只做 review/paper 产出,不创建、不成交、不修改任何基金订单。
不是买卖指令;研究信号,human executes。
"""

import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nightly_run.json")
ALARM_FLAG = "/tmp/ar-nightly-incomplete"

# 关键契约新鲜度(P0-B):缺文件 = FAIL;mtime 超时 = WARN 列出但不阻断
FRESHNESS_FILES = ("watch_dynamic.json", "rotation_panel.json")
FRESH_WARN_H = 36

# (name, cmd, needs_token, depends_on)
# depends_on 里任一步非 OK ⇒ 本步 SKIPPED_STALE_INPUT
STEPS = [
    # ── 结算主干(闭环根修复:定盘并入夜链,消灭手工补账)──
    ("official_sample", ["python3", "run_official_sample.py"], True, []),
    # ── 全市场研究数据支线:R-032 是 R-008/R-036 的唯一 universe 事实源 ──
    ("security_registry",
     ["python3", "../research_funnel/security_registry.py", "--allow-partial-exit-zero"],
     True, ["official_sample"]),
    ("feature_store", ["python3", "../research_funnel/feature_store.py"], True,
     ["security_registry"]),
    ("e1_event_layer",
     ["python3", "../research_funnel/e1_event_layer.py", "--allow-partial-exit-zero"],
     True, ["security_registry"]),
    ("fwd_backfill", ["python3", "run_post_close_report.py", "--backfill-only"], True,
     ["official_sample"]),
    # NAV 每日结算:update_nav 此前定义了却无 CLI 入口,从不被调用 ——
    # nav_history 停在 0731 正是因此,并把 model_portfolio_state 拖成 STALE_INPUT。
    ("fund_daily_mark", ["python3", "model_paper_fund.py", "--daily"], True,
     ["official_sample"]),  # F8:正式样本每天只生成一次(official_sample 步),此处仅回填
    # ── 轮动/发现链 ──
    ("rotation_panel", ["python3", "rotation_panel.py"], True, []),
    ("momentum_prefilter", ["python3", "momentum_prefilter.py"], True, []),
    ("rotation_stats", ["python3", "rotation_stats.py"], False,
     ["rotation_panel", "momentum_prefilter"]),
    ("rotation_validation", ["python3", "rotation_validation.py", "--append"], True,
     ["rotation_stats"]),
    ("lead_precursor", ["python3", "lead_precursor.py"], False, ["rotation_validation"]),
    ("overnight_anchor_frame", ["python3", "overnight_anchor.py"], False, []),
    # ── 名单与持仓 ──
    ("court_wakeup", ["python3", "court_wakeup.py"], True, []),
    ("watch_dynamic", ["python3", "watch_dynamic.py"], False,
     ["court_wakeup", "momentum_prefilter"]),
    ("position_review", ["python3", "position_review.py"], True, ["official_sample"]),
    # ── 强制质检层(2026-07-27/28 事故驱动)──
    ("red_flag_gate", ["python3", "red_flag_gate.py", "--from-watchlist"], True,
     ["watch_dynamic"]),
    ("full_battery", ["python3", "full_battery.py", "--from-watchlist"], True,
     ["watch_dynamic"]),
    # 晋级必须在质检之后(审计F4:亏损预告票不得先READY后亮旗)+ 轮动面板硬依赖(F5)
    ("setup_promoter", ["python3", "setup_promoter.py"], True,
     ["watch_dynamic", "official_sample", "red_flag_gate", "full_battery",
      "rotation_panel"]),
    # 法庭在质检与晋级**之后**(B5:court_10d 读 red_flags/battery/promotion 产物,
    # 排在前面就是拿昨天的证据开今天的庭)
    ("court_10d", ["python3", "court_10d.py"], False,
     ["official_sample", "position_review", "red_flag_gate", "full_battery",
      "setup_promoter"]),
    # ── 前端契约导出(引擎写、前端读的唯一通道)──
    # 设计决定(审查F4/F5):export 无前置依赖、永远运行 —— 跳过导出只会让磁盘上
    # 留着更旧的契约;诚实性由 export 内部的逐源新鲜度/内部状态戳保证。
    ("export_contracts", ["python3", "export_contracts.py"], False, []),
    # ── Macro OS M1-C:同轮 M0-B3→M1-A→M1-B,只发布校准标签/风险预算语境 ──
    # 宏观缺数是 data_quality,不是执行失败。有效的降级产物必须携带哈希清单;
    # 结构失败则仅隔离本轮 Macro 派生物,不得冻结 NAV/账本等无关发布。
    # 组合输入来自本轮 export_contracts,但不依赖整个 export 步必须 COMPLETE:
    # 其他无关契约 PARTIAL 不应卡死 Macro。M1-C 自己强校验组合 run_id/date,
    # 因此 export 若没产出本轮组合,Macro 会 fail-closed,不会读取旧契约冒充。
    ("macro_m1c", ["python3", "../macro_os/m1c.py"], False, []),
    # ── 研究漏斗 U1→U4:观察期,隔离接入 ──
    # 全新代码首次进生产。给它阻断发布的权力,等于让一个未经生产验证的模块能停掉
    # 整条夜链,所以先隔离:失败记 DATA_BLOCKED,不否决 NAV/账本/其余研究。
    # 产物分工见 nightly_funnel.py —— 30MB 级 bundle 落 untracked 的 data_history
    # 观察区(不入库、不进发布清单),发布树只收一个 1KB 的 funnel_health.json。
    # 依赖显式声明:漏斗读 registry/feature/e1 与 rotation/battery 的**本轮**产物,
    # 排在它们后面才不会拿昨天的证据算今天的候选池。
    # 三段子 DAG(Junyan 批准的方案 C 变体):网络副作用只在中段,两头纯计算可复现。
    #   funnel_candidates  纯计算 U0/U1/U2 → 不可变候选清单
    #   candidate_battery  唯一网络步:绑候选 hash 逐票六维电池,整体失败也逐票 DATA_BLOCKED
    #   funnel_finalize    纯计算:校验电池覆盖集合==候选清单,再生成 U3/U4 与 health
    # 三段同 as_of/run_id/bundle,后段读前段的 stage manifest 并核 hash。任一段挂,
    # 三段整体隔离(不否决发布)。full_battery --from-watchlist 保留给 court/promoter。
    ("funnel_candidates", ["python3", "../research_funnel/funnel_dag.py", "candidates"], False,
     ["security_registry", "feature_store", "e1_event_layer", "rotation_panel"]),
    # governance-mutation: FUNNEL_DAG_TOKENLESS_DEGRADATION
    # This step is network-capable, but the token is deliberately optional: when it is
    # absent the runner must still execute and emit one explicit DATA_BLOCKED row per
    # candidate.  Marking it token-required here would let the generic preflight skip
    # the process before that evidence can be materialized.
    ("candidate_battery", ["python3", "../research_funnel/funnel_dag.py", "battery"], False,
     ["funnel_candidates"]),
    ("funnel_finalize", ["python3", "../research_funnel/funnel_dag.py", "finalize"], False,
     ["funnel_candidates", "candidate_battery"]),
]

# ── 产物契约(B2/B3/B4):步骤状态由**产物实物**判定,不再猜 stdout ──
# (path, date_key, fresh_required):date_key 非空 ⇒ 该字段前 8 位必须 == target;
# fresh_required ⇒ 本轮必须重写(mtime >= run_start)。
# 正式步骤必须以日期字段、run_id 与 target_trade_date 绑定本轮上下文。
ARTIFACTS = {
    "official_sample":       [("run_target.json", "trade_date", True),
                               (os.path.join("samples", "{target}.json"),
                                "target_trade_date", False)],
    "security_registry":     [(os.path.join("..", "..", "public", "data", "v2",
                                             "security_registry.json"), "as_of", True)],
    "feature_store":         [(os.path.join("..", "..", "public", "data", "v2",
                                             "feature_store_health.json"), "as_of", True)],
    "e1_event_layer":        [(os.path.join("..", "..", "public", "data", "v2",
                                             "e1_event_layer.json"), "as_of", True)],
    "fwd_backfill":          [(os.path.join("reports", "{target}.json"),
                                "target_trade_date", True)],
    # NAV 每日结算的产物契约。加步骤时漏了这条 —— 没有产物契约的步骤等于没被验过,
    # 它可以静默失败而整轮照报 COMPLETE(由 RuleCompletenessTest 抓出)。
    "fund_daily_mark":       [(os.path.join("model_fund", "nav_history.json"),
                                None, True)],
    "rotation_panel":        [("rotation_panel.json", "as_of", True)],
    "momentum_prefilter":    [("momentum_prefilter.json", "as_of", True)],
    "rotation_stats":        [("rotation_stats.json", "as_of", True)],
    "rotation_validation":   [("rotation_validation.json", "as_of", True)],
    "lead_precursor":        [("lead_precursor.json", "as_of", True)],
    "overnight_anchor_frame": [("overnight_anchor.json", "as_of", True)],
    "court_wakeup":          [("court_wakeup.json", "as_of", True)],
    "watch_dynamic":         [("watch_dynamic.json", "generated_at", True)],
    "position_review":       [("position_review.json", "as_of", True)],
    "court_10d":             [("court_10d.json", "checked_at", True)],
    "red_flag_gate":         [("red_flags.json", "checked_at", True)],
    "full_battery":          [("battery.json", "checked_at", True)],
    "setup_promoter":        [("promotion_queue.json", "as_of", True)],
    "export_contracts":      [(os.path.join("..", "..", "public", "data", "v2", "meta.json"),
                               None, True)],
    "macro_m1c":             [(os.path.join("..", "..", "public", "data", "v2", "macro",
                                             "m1c_run_manifest.json"),
                                "target_trade_date", True)],
    # 漏斗的可验证产物是 health 摘要,不是 30MB 的 bundle 本身 —— bundle 在
    # untracked 观察区,不入发布清单。health 携带 run_id/target_trade_date,
    # 因此本轮绑定与新鲜度都由通用契约校验,漏斗拿不到"自证"的余地。
    # governance-mutation: FUNNEL_NIGHTLY_ARTIFACT_FRESHNESS
    # 前两段的实物在 untracked 观察区,发布树只收 ~300B 的 stage receipt(转述
    # stage_hash,不含研究内容);finalize 写 health 并把三份 receipt 的 hash 链起来核。
    "funnel_candidates":     [(os.path.join("..", "..", "public", "data", "v2",
                                             "funnel_stage_candidates.json"),
                                "as_of", True)],
    "candidate_battery":     [(os.path.join("..", "..", "public", "data", "v2",
                                             "funnel_stage_battery.json"),
                                "as_of", True)],
    "funnel_finalize":       [(os.path.join("..", "..", "public", "data", "v2",
                                             "funnel_health.json"),
                                "as_of", True)],
}

# 状态精度(越大越糟);步骤终态 = max(进程判定, 各产物判定)
_SEVERITY = {"OK": 0, "PARTIAL": 1, "DATA_BLOCKED": 2, "STALE_OUTPUT": 3,
             "DATE_MISMATCH": 4, "FAILED": 5}
RESEARCH_DATA_STEPS = {"security_registry", "feature_store", "e1_event_layer"}
MACRO_DATA_STEPS = {"macro_m1c"}
FUNNEL_DATA_STEPS = {"funnel_finalize"}
FUNNEL_STAGE_STEPS = {"funnel_candidates", "candidate_battery"}
# Per-ticket evidence may be incomplete without the generator itself failing.
# Downstream gates consume the explicit blocked rows; one blocked ticket must
# not veto unrelated NAV, Macro, Funnel, or publication work.
PER_TICKER_EVIDENCE_STEPS = {"full_battery", "setup_promoter"}
ISOLATED_CALIBRATION_STEPS = frozenset({
    "macro_m1c", "funnel_candidates", "candidate_battery", "funnel_finalize",
})
RUN_CONTEXT_EXTERNAL_STEPS = set(RESEARCH_DATA_STEPS)


def _validate_isolated_calibration_steps():
    """Keep advisory failure isolation narrower than the business pipeline.

    这份名单是夜链唯一的 fail-closed 豁免通道,所以用精确相等而不是包含判断:
    往里加成员必须改这个字面量,并且改动会被 mutation gate 逐条钉住。
    research_funnel 在观察期内隔离 —— 见 STEPS 里的说明。
    """
    if ISOLATED_CALIBRATION_STEPS != frozenset({
        "macro_m1c", "funnel_candidates", "candidate_battery", "funnel_finalize",
    }):
        raise RuntimeError(
            "isolated calibration allowlist may contain only macro_m1c and the "
            "three funnel DAG stages"
        )


def _research_quality(step, data):
    """Keep process completion separate from evidence completeness.

    The generators validate their own contracts before writing. A valid PARTIAL
    contract is publishable evidence with an explicit quality gap, not a process
    failure. Total E1 coverage loss is promoted to DATA_BLOCKED.
    """
    # 漏斗的 PARTIAL 必须上浮到顶层 research_data_quality —— 不上浮的话,真实数据下
    # 已经在报 PARTIAL 的漏斗会被顶层的 COMPLETE 盖掉,那正是 pipeline_status ⊥
    # data_quality 这条要防的混淆。承重的只有这个集合:漏斗的 status 字段与研究步
    # 同形,下面的通用尾部本来就能正确转述,不需要再写一个分支。
    # governance-mutation: FUNNEL_NIGHTLY_QUALITY_ROLLUP
    # governance-mutation: NIGHTLY_PER_TICKER_EVIDENCE_QUALITY
    if (step not in RESEARCH_DATA_STEPS | MACRO_DATA_STEPS | FUNNEL_DATA_STEPS
            | PER_TICKER_EVIDENCE_STEPS
            or not isinstance(data, dict)):
        return None
    if step == "full_battery":
        rows = data.get("results")
        if not isinstance(rows, list):
            return "UNKNOWN"
        return (
            "PARTIAL"
            if any((row.get("completeness") or {}).get("verdict") != "COMPLETE"
                   for row in rows if isinstance(row, dict))
            else "COMPLETE"
        )
    if step == "setup_promoter":
        return "PARTIAL" if data.get("data_blocked") else "COMPLETE"
    if step in MACRO_DATA_STEPS:
        return _normalize_data_quality(data.get("data_quality"))
    status = str(data.get("status") or "UNKNOWN").upper()
    if step == "e1_event_layer":
        coverage = data.get("coverage") or {}
        if coverage.get("rows") and coverage.get("data_blocked") == coverage.get("rows"):
            return "DATA_BLOCKED"
    return status


def _validate_research_contract(step, data):
    research_dir = os.path.abspath(os.path.join(HERE, "..", "research_funnel"))
    if research_dir not in sys.path:
        sys.path.insert(0, research_dir)
    if step == "security_registry":
        from security_registry import validate_registry
        validate_registry(data)
    elif step == "feature_store":
        from feature_store import validate_health
        validate_health(data)
    elif step == "e1_event_layer":
        from e1_event_layer import validate_event_layer
        validate_event_layer(data)


def _validate_macro_contract(path):
    macro_dir = os.path.abspath(os.path.join(HERE, "..", "macro_os"))
    if macro_dir not in sys.path:
        sys.path.insert(0, macro_dir)
    import m1c
    m1c.validate_run(os.path.dirname(path))


def _discard_failed_macro_outputs(base):
    """Remove partial/current Macro derivatives after an isolated failure."""
    import nightly_publish

    stage_public = os.path.abspath(
        os.path.join(base, "..", "..", "public", "data", "v2")
    )
    return nightly_publish.reset_staged_macro_outputs(stage_public)


FUNNEL_HEALTH_SCHEMA = "ar.research_funnel_health"


def _validate_funnel_health(data, artifact_path=None):
    _validate_funnel_health_shape(data)
    _verify_funnel_bundle(data, REPO_ROOT, artifact_path)


def _validate_funnel_health_shape(data):
    """漏斗 health 的内容必须被校验,不能只看文件在不在。

    复审打出来的洞:原来三个字段的极简 JSON 就能通过产物契约 —— 只要日期与
    run_id 对得上,内容爱写什么写什么。health 是这一步唯一的可验证产物,它自己
    不被校验,等于这一步没被校验。
    """
    if not isinstance(data, dict):
        raise ValueError("health 必须是对象")
    if data.get("schema") != FUNNEL_HEALTH_SCHEMA:
        raise ValueError(f"schema 非法: {data.get('schema')!r}")
    # governance-mutation: FUNNEL_NIGHTLY_HEALTH_DATE_SHAPE
    # as_of 会被拼进 bundle 路径。不校验形状的话,"20260813/../../elsewhere" 既能
    # 满足 location 的字面比对,又能通过夜链只看前 8 位的日期校验 —— 于是 verifier
    # 会去读观察区之外的目录。日期字段必须是 8 位数字,且两个字段必须一致。
    for key in ("as_of", "target_trade_date"):
        value = str(data.get(key) or "")
        if not (len(value) == 8 and value.isdigit()):
            raise ValueError(f"{key} 必须是 8 位日期: {value!r}")
    if data["as_of"] != data["target_trade_date"]:
        raise ValueError(
            f"as_of={data['as_of']!r} 与 target_trade_date={data['target_trade_date']!r} 不一致"
        )
    run_id = str(data.get("run_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError(f"run_id 不能安全地作为路径组件: {run_id!r}")
    status = str(data.get("status") or "").upper()
    if status not in ("COMPLETE", "PARTIAL", "DATA_BLOCKED"):
        raise ValueError(f"status 非法: {status!r}")
    bundle = data.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("缺少 bundle 段")
    if bundle.get("published") is not False:
        raise ValueError("观察期产物不得声称已发布")
    if bundle.get("immutable") is not True:
        raise ValueError("观察期 bundle 必须使用不可覆盖的运行级地址")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("bundle.artifacts 缺失")
    for name, digest in artifacts.items():
        if not (isinstance(digest, str) and len(digest) == 64 and
                all(c in "0123456789abcdef" for c in digest)):
            raise ValueError(f"产物摘要不是 sha256: {name}")
    counts = data.get("counts")
    if not isinstance(counts, dict) or not all(
        isinstance(counts.get(k), int) for k in
        ("scan_rows", "candidate_rows", "deep_queue_rows")
    ):
        raise ValueError("counts 缺失或非整数")
    policy = data.get("policy") or {}
    if policy.get("nightly_mode") != "OBSERVATION_ONLY_NOT_PUBLISHED":
        raise ValueError("观察期 nightly_mode 被改写")
    # 声称与实测必须自洽:说队列是空的,行数就得是 0
    if policy.get("u4_queue_empty_by_construction") is not (
        counts["deep_queue_rows"] == 0
    ):
        raise ValueError(
            "u4_queue_empty_by_construction 与 deep_queue_rows 矛盾"
        )
    if policy.get("u4_selection_supplied") is not False:
        raise ValueError("观察期不得携带人工选票")
    if policy.get("macro_input_wired") is not False:
        raise ValueError("观察期不得声称已接入宏观输入")
    _refuse_funnel_action_keys(data)


def _refuse_funnel_action_keys(data):
    """health 里不得出现任何交易动作或阻断权限字段。

    终审复核打出来的:形状层逐字段校验得很细,却从没问过"有没有多出不该有的
    字段"。观察期产物混进 trade_action=BUY 或 formal_blocking_authority=true,
    照样能通过 —— 而这两样正是整个平台的红线。复用 #267 漏斗自己的禁字集合,
    两边不会各写一份而漂移。
    """
    research_dir = os.path.abspath(os.path.join(HERE, "..", "research_funnel"))
    if research_dir not in sys.path:
        sys.path.insert(0, research_dir)
    import funnel_pipeline as fp

    # governance-mutation: FUNNEL_NIGHTLY_HEALTH_NO_TRADE
    offending = fp.FORBIDDEN_ACTION_KEYS.intersection(fp._walk_keys(data))
    if offending:
        raise ValueError(f"health 携带交易或阻断权限字段: {sorted(offending)}")


def _verify_funnel_bundle(data, repo_root, artifact_path=None):
    """正式 verifier 必须去验持久 bundle,不能只看 health 自己说了什么。

    复审第二轮的 BLOCKER:格式完整但全自报的 health —— bundle 根本不存在 ——
    照样通过 verify_step_artifacts;生成之后删改 bundle 也发现不了。上一轮我把
    **生成时**的推导补上了,但生成时的诚实不构成验证:验证方必须自己去看实物。
    """
    research_dir = os.path.abspath(os.path.join(HERE, "..", "research_funnel"))
    if research_dir not in sys.path:
        sys.path.insert(0, research_dir)
    import nightly_funnel

    as_of = str(data.get("as_of") or "")
    run_id = str(data.get("run_id") or "")
    bundle = data.get("bundle") or {}
    location = str(bundle.get("location") or "")
    # location 必须逐字等于约定位置:否则可以指向任意目录来"找一个能对上的 bundle"
    if location != f"data_history/funnel/{as_of}/{run_id}":
        raise ValueError(f"bundle.location 非法: {location!r}")
    funnel_root = os.path.join(repo_root, "data_history", "funnel")
    date_dir = os.path.join(funnel_root, as_of)
    bundle_dir = os.path.join(date_dir, run_id)
    # os.path.isdir 会跟随符号链接:观察区里种一个指向区外的链接,verifier 就会
    # 拿别处的 bundle 给本轮 health 背书。用与生成侧同一套容器化判据。
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_SYMLINK
    if (os.path.islink(funnel_root) or os.path.islink(date_dir) or
            os.path.islink(bundle_dir) or
            os.path.realpath(bundle_dir) != os.path.join(
                os.path.realpath(funnel_root), as_of, run_id
            )
    ):
        raise ValueError(f"bundle 目录越界或为符号链接: {os.path.realpath(bundle_dir)}")
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_EXISTS
    if not os.path.isdir(bundle_dir):
        raise ValueError(f"health 声称的 bundle 不存在: {location}")

    from pathlib import Path as _Path

    # read_bundle 自己会核 manifest 的 as_of/schema/版本/逐产物哈希/bundle_hash 自洽
    manifest, measured, payloads = nightly_funnel.read_bundle(_Path(bundle_dir), as_of)
    if bundle.get("artifacts") != measured:
        raise ValueError("health 登记的产物摘要与磁盘实物不符")
    if bundle.get("bundle_hash") != manifest.get("bundle_hash"):
        raise ValueError("health 的 bundle_hash 与 manifest 不符")
    # A DAG health receipt cannot be downgraded to the legacy four-file bundle.
    # Legacy production receipts have no battery_coverage field, so they remain readable.
    # governance-mutation: FUNNEL_DAG_NO_LEGACY_DOWNGRADE
    if "battery_coverage" in data and "candidate_battery.json" not in payloads:
        raise ValueError("health 声称 candidate battery coverage,但持久 bundle 缺少 DAG evidence")
    if "candidate_battery.json" in payloads:
        candidate_battery = payloads["candidate_battery.json"]
        measured_battery = nightly_funnel.validate_candidate_battery(
            candidate_battery, payloads["candidate_manifest.json"]
        )
        measured_battery["provider_state"] = candidate_battery.get("provider_state")
        # governance-mutation: FUNNEL_DAG_HEALTH_COVERAGE_RECOMPUTED
        if data.get("battery_coverage") != measured_battery:
            raise ValueError(
                f"health 的 battery_coverage 与实物不符: "
                f"{data.get('battery_coverage')} != {measured_battery}"
            )

    # status 与 counts 由实物重算,health 只是转述,不是权威
    scan = payloads["all_market_scan.json"]
    candidates = payloads["candidate_review.json"]
    measured_counts = {
        "scan_rows": nightly_funnel._row_count(scan),
        "candidate_rows": nightly_funnel._row_count(candidates),
        "deep_queue_rows": nightly_funnel._row_count(
            payloads["deep_research_queue.json"]
        ),
    }
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_COUNTS
    if data.get("counts") != measured_counts:
        raise ValueError(
            f"health 的 counts 与实物不符: {data.get('counts')} != {measured_counts}"
        )
    measured_degraded = dict(
        (scan.get("coverage") or {}).get("blocked_by_channel") or {}
    )
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_DEGRADED
    if data.get("degraded_channels") != measured_degraded:
        raise ValueError(
            f"health 的 degraded_channels 与实物不符: "
            f"{data.get('degraded_channels')} != {measured_degraded}"
        )
    measured_status = nightly_funnel._worst(
        str(scan.get("data_status") or scan.get("status") or "").upper(),
        str(candidates.get("status") or "").upper(),
    )
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_STATUS
    if str(data.get("status") or "").upper() != measured_status:
        raise ValueError(
            f"health 的 status={data.get('status')!r} 与实物推导 {measured_status} 不符"
        )

    # 哈希只证明字节没被改,证明不了内容仍然合规:生成之后换一个"自洽但不合契约"
    # 的 bundle,单靠哈希绑定是发现不了的。所以验证侧也要跑一遍 #267 的四份契约。
    # registry 取本轮**暂存树**里的那一份 —— 就是生成侧用的那一份;取 live 的会
    # 在发布前读到昨天的,造成假失败。
    registry = None
    if artifact_path:
        candidate = os.path.join(
            os.path.dirname(os.path.abspath(artifact_path)), "security_registry.json"
        )
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as fh:
                registry = json.load(fh)
    # governance-mutation: FUNNEL_NIGHTLY_VERIFIER_CONTRACTS
    if registry is None:
        raise ValueError("找不到本轮 registry,无法在验证侧复核 bundle 契约")
    nightly_funnel.validate_bundle_contracts(
        payloads, registry, "all_market_scan.json"
    )


def _discard_failed_funnel_outputs(base):
    """漏斗隔离失败后,移除本轮暂存的 health 摘要。

    staging 是 live 发布树的副本,所以昨天的 funnel_health.json 会躺在里面。
    不删掉它,本轮发布清单就会收录昨天的摘要并把它当作今天的输出 —— 隔离机制
    要防的正是这件事。删的是 staging 副本,live 文件不动;它只是不出现在本轮
    发布清单里,除非漏斗自己重新产出。
    30MB 的 bundle 不在这里处理:它落在 untracked 观察区、本就不进发布清单,
    而且 run_pipeline 是 staging+os.replace 原子落地,不会留下半成品。
    """
    public_v2 = os.path.abspath(os.path.join(base, "..", "..", "public", "data", "v2"))
    removed = []
    # 三段任一挂,三份都清:昨天的 health 和两份 stage receipt 一起躺在 staging 里,
    # 留任何一份都会被本轮发布清单当成今天的输出。
    for name in ("funnel_health.json", "funnel_stage_candidates.json",
                 "funnel_stage_battery.json"):
        stage_file = os.path.join(public_v2, name)
        # governance-mutation: FUNNEL_NIGHTLY_DISCARD
        if not os.path.isfile(stage_file):
            continue
        os.remove(stage_file)
        removed.append(f"public/data/v2/{name}")
    return removed


# 每个隔离步骤都必须声明自己的产物销毁方式。隔离 = 失败照样记账、暂存产物照样
# 销毁,只是不牵连别人;缺了销毁,隔离就退化成"失败被无视,昨天的产物冒充今天"。
_ISOLATED_DISCARD = {
    "macro_m1c": _discard_failed_macro_outputs,
    # governance-mutation: FUNNEL_NIGHTLY_DISCARD_DISPATCH
    "funnel_candidates": _discard_failed_funnel_outputs,
    "candidate_battery": _discard_failed_funnel_outputs,
    "funnel_finalize": _discard_failed_funnel_outputs,
}


def _discard_failed_isolated_outputs(step, base):
    discard = _ISOLATED_DISCARD.get(step)
    # governance-mutation: FUNNEL_NIGHTLY_DISCARD_POLICY_REQUIRED
    if discard is None:
        raise RuntimeError(
            f"isolated step {step} has no declared output discard policy"
        )
    return discard(base)


def _normalize_data_quality(value):
    quality = str(value or "UNKNOWN").upper()
    if quality == "BLOCKED":
        return "DATA_BLOCKED"
    if quality not in ("COMPLETE", "PARTIAL", "DATA_BLOCKED", "UNKNOWN"):
        return "UNKNOWN"
    return quality


def _expected_export_contracts():
    import export_contracts
    return {name for name, _builder in export_contracts.BUILDERS}


def _export_contract_status(data):
    """Validate export process state without treating data quality as execution state."""
    if not isinstance(data, dict):
        return "FAILED", "export meta 不是 JSON object"
    report = str(data.get("report") or "").upper()
    contracts = data.get("contracts")
    if report not in ("COMPLETE", "PARTIAL"):
        return "FAILED", f"export report 非法或缺失: {report or '缺失'}"
    if not isinstance(contracts, dict) or not contracts:
        return "FAILED", "export contracts 为空或结构非法"

    expected_names = _expected_export_contracts()
    actual_names = set(contracts)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        return "FAILED", f"export 契约集合不一致: missing={missing}, extra={extra}"
    count = data.get("business_contract_count")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(contracts):
        return "FAILED", f"business_contract_count={count!r} ≠ {len(contracts)}"

    pipeline = {}
    for name, item in contracts.items():
        if not isinstance(item, dict):
            return "FAILED", f"export contract {name} 结构非法"
        status = str(item.get("pipeline_status") or "").upper()
        if status not in ("OK", "STALE_INPUT", "DATA_BLOCKED"):
            return "FAILED", f"export contract {name} pipeline_status 非法: {status or '缺失'}"
        alias = str(item.get("status") or "").upper()
        if alias != status:
            return "FAILED", f"export contract {name} status={alias or '缺失'} ≠ pipeline_status={status}"
        pipeline[name] = status

    expected = "COMPLETE" if all(status == "OK" for status in pipeline.values()) else "PARTIAL"
    if report != expected:
        return "FAILED", f"export report={report} 与逐契约 pipeline_status 推导值 {expected} 不一致"
    if report != "COMPLETE":
        bad = [name for name, status in pipeline.items() if status != "OK"]
        return "PARTIAL", f"export 流水线非完整: {bad[:3]}"
    return "OK", ""


def _artifact_status_scan(step, data, artifact_path=None):
    """个别产物的内部状态字段(仅对语义明确的两个,避免把逐票 DATA_BLOCKED
    的诚实条目误判成整步失败 —— 误报的下场是闸门被人关掉)。"""
    if step == "full_battery":
        rows = data.get("results")
        if not isinstance(rows, list) or not rows:
            return "FAILED", "电池 results 为空或结构非法"
        expected_dims = {"行情", "资金", "基本面", "技术面", "消息面", "估值"}
        for row in rows:
            if not isinstance(row, dict) or not row.get("ts_code"):
                return "FAILED", "电池存在无 ts_code 的非法行"
            if set((row.get("dims") or {})) != expected_dims:
                return "FAILED", f"{row.get('ts_code')} 六维集合不完整"
            verdict = (row.get("completeness") or {}).get("verdict")
            if verdict not in ("COMPLETE", "PARTIAL"):
                return "FAILED", f"{row.get('ts_code')} completeness verdict 非法"
        # governance-mutation: NIGHTLY_FULL_BATTERY_PARTIAL_PUBLISHABLE
        return "OK", ""
    if step == "setup_promoter":
        if not isinstance(data.get("queue"), list):
            return "FAILED", "promotion queue 结构非法"
        if not isinstance(data.get("data_blocked", []), list):
            return "FAILED", "promotion data_blocked 结构非法"
        # governance-mutation: NIGHTLY_PROMOTER_PARTIAL_PUBLISHABLE
        return "OK", ""
    if step in RESEARCH_DATA_STEPS:
        try:
            _validate_research_contract(step, data)
        except Exception as exc:
            return "FAILED", f"研究数据契约校验失败: {exc}"
        quality = _research_quality(step, data)
        if quality not in ("COMPLETE", "PARTIAL", "DATA_BLOCKED"):
            return "FAILED", f"研究数据契约状态非法: {quality}"
        return "OK", ""
    if step in MACRO_DATA_STEPS:
        if not artifact_path:
            return "FAILED", "Macro M1-C 产物路径缺失"
        try:
            _validate_macro_contract(artifact_path)
        except Exception as exc:
            return "FAILED", f"Macro M1-C 契约校验失败: {exc}"
        quality = _research_quality(step, data)
        if quality not in ("COMPLETE", "PARTIAL", "DATA_BLOCKED"):
            return "FAILED", f"Macro M1-C data_quality 非法: {quality}"
        return "OK", ""
    if step in FUNNEL_DATA_STEPS:
        # governance-mutation: FUNNEL_NIGHTLY_HEALTH_CONTRACT
        try:
            _validate_funnel_health(data, artifact_path)
        except Exception as exc:
            return "FAILED", f"漏斗 health 契约校验失败: {exc}"
        return "OK", ""
    if step == "export_contracts":
        return _export_contract_status(data)
    if step == "court_10d":
        status = str(data.get("status") or "").upper()
        if status in ("DATA_BLOCKED", "BLOCKED"):
            return "DATA_BLOCKED", f"法庭内部状态={status}"
        if status in ("PARTIAL", "INCOMPLETE"):
            return "PARTIAL", f"法庭内部状态={status}"
    if step == "overnight_anchor_frame":
        if str(data.get("bias") or "").upper() == "DATA_BLOCKED":
            return "DATA_BLOCKED", "隔夜锚无足够可用数据"
    if step == "red_flag_gate":
        verdicts = [str(r.get("verdict") or "").upper()
                    for r in (data.get("results") or [])]
        blocked = [v for v in verdicts if v == "DATA_BLOCKED"]
        if verdicts and len(blocked) == len(verdicts):
            return "DATA_BLOCKED", "红旗扫描全部对象 DATA_BLOCKED"
        if blocked:
            return "PARTIAL", f"红旗扫描部分 DATA_BLOCKED(n={len(blocked)})"
    if step == "position_review" and data.get("data_blocked"):
        return "PARTIAL", f"仓位复审缺证据 n={len(data['data_blocked'])}"
    if step == "court_wakeup" and data.get("data_blocked"):
        return "PARTIAL", f"研究法庭唤醒缺行情 n={len(data['data_blocked'])}"
    if step == "rotation_validation":
        blocked = []
        for key, value in data.items():
            if isinstance(value, dict) and str(value.get("status") or "").upper().startswith("DATA_BLOCKED"):
                blocked.append(key)
            elif isinstance(value, list) and any(
                isinstance(item, dict)
                and str(item.get("status") or "").upper().startswith("DATA_BLOCKED")
                for item in value
            ):
                blocked.append(key)
        if blocked:
            return "PARTIAL", f"轮动检验部分 DATA_BLOCKED: {','.join(blocked[:3])}"
    if step == "rotation_stats" and data.get("data_blocked"):
        return "PARTIAL", f"内部 DATA_BLOCKED n={len(data['data_blocked'])}"
    return "OK", ""


def verify_step_artifacts(step, target, run_start, base=None, run_id=None):
    """产物实物校验:存在 → 可解析 → 本轮已重写 → 日期==target → 内部状态。
    返回 (最重状态, [逐产物明细])。这是 B2 的核心:COMPLETE 必须由实物背书。"""
    base = base or HERE
    worst, details = "OK", []
    for rel_template, date_key, fresh_required in ARTIFACTS.get(step, []):
        rel = rel_template.format(target=target or "")
        path = os.path.join(base, rel)
        d = {"artifact": rel, "verdict": "OK", "why": ""}
        if not os.path.exists(path):
            d.update(verdict="FAILED", why="产物不存在")
        else:
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError) as e:
                data = None
                d.update(verdict="FAILED", why=f"不可解析: {e}")
            if data is not None:
                if fresh_required and os.path.getmtime(path) < run_start:
                    d.update(verdict="STALE_OUTPUT", why="本轮未重写(mtime 早于本轮开始)")
                elif date_key and target:
                    v = str((data.get(date_key) if isinstance(data, dict) else "") or "")[:8]
                    if v != target:
                        d.update(verdict="DATE_MISMATCH",
                                 why=f"{date_key}={v or '缺失'} ≠ target {target}")
                # 不可变历史输入(sample)允许跨 run 复用;本轮活性由同一步的
                # fresh run_target.json 背书。所有 fresh 产物必须绑定当前 run_id。
                if (d["verdict"] == "OK" and fresh_required
                        and run_id and isinstance(data, dict)
                        and step not in RUN_CONTEXT_EXTERNAL_STEPS):
                    artifact_run = str(data.get("run_id") or "")
                    artifact_target = str(data.get("target_trade_date") or "")[:8]
                    if artifact_run != run_id:
                        d.update(verdict="STALE_OUTPUT",
                                 why=f"run_id={artifact_run or '缺失'} ≠ {run_id}")
                    elif target and artifact_target != target:
                        d.update(verdict="DATE_MISMATCH",
                                 why=f"target_trade_date={artifact_target or '缺失'} ≠ {target}")
                if d["verdict"] == "OK" and isinstance(data, dict):
                    quality = _research_quality(step, data)
                    if quality:
                        d["quality_status"] = quality
                    sv, swhy = _artifact_status_scan(step, data, path)
                    if sv != "OK":
                        d.update(verdict=sv, why=swhy)
        details.append(d)
        if _SEVERITY[d["verdict"]] > _SEVERITY[worst]:
            worst = d["verdict"]
    return worst, details


def read_run_target(base=None, run_start=None, run_id=None):
    """本轮 target_trade_date:由 official_sample 写的 run_target.json 提供,
    且必须是本轮写的(mtime 校验)—— 不接受上一轮残留。"""
    p = os.path.join(base or HERE, "run_target.json")
    if not os.path.exists(p):
        return None
    if run_start and os.path.getmtime(p) < run_start:
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if run_id and data.get("run_id") != run_id:
            return None
        return str(data.get("trade_date") or "")[:8] or None
    except (json.JSONDecodeError, OSError):
        return None


_BLOCK_MARKERS = ("DATA_BLOCKED", "DATA-BLOCKED")


def _classify(code, out):
    """状态协议(审查F3/F16):
    - 退出非0:输出含 blocked 标记 ⇒ DATA_BLOCKED(如 official_sample 的
      SystemExit("DATA_BLOCKED: ...")),否则 FAILED;
    - 退出0:仅当 stdout 最后一个非空行以 DATA_BLOCKED 开头才算整步 blocked ——
      中途的逐项提示(⛔ xx: DATA_BLOCKED)/矩阵token 不再误伤整步。"""
    if code != 0:
        return "DATA_BLOCKED" if any(m in out for m in _BLOCK_MARKERS) else "FAILED"
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    if last.startswith("DATA_BLOCKED") or last.startswith("STEP_STATUS=DATA_BLOCKED"):
        return "DATA_BLOCKED"
    return "OK"


def run_steps(
    runner=None,
    require_live=True,
    verify=False,
    base=None,
    run_id=None,
    persistent_feature_db=None,
    persistent_macro_db=None,
    persistent_funnel_root=None,
):
    """verify=True(正式路径):步骤终态 = max(进程判定, 产物实物判定)。
    COMPLETE 从此必须由实物背书 —— 进程退 0 + 免责声明不再等于成功(B2/B3)。"""
    # governance-mutation: MACRO_M1C_ISOLATION_ALLOWLIST
    _validate_isolated_calibration_steps()
    base = base or HERE
    run_start = time.time()
    results, status_by = [], {}
    target = None

    for name, cmd, needs_token, deps in STEPS:
        bad = [d for d in deps if status_by.get(d) != "OK"]
        if bad:
            entry = {"step": name, "status": "SKIPPED_STALE_INPUT",
                     "why": f"上游非OK: {','.join(bad)}"}
            # governance-mutation: FUNNEL_DAG_SKIP_STAYS_ISOLATED
            if name in ISOLATED_CALIBRATION_STEPS:
                # 隔离步依赖隔离步:上游隔离了,下游被跳过时也必须隔离。否则段 1
                # 不否决发布,段 2/3 却因"上游非 OK"从后门否决 —— 隔离形同虚设。
                # 三段的 staging 产物统一由段 1 的 discard 清理,这里不重复。
                entry["isolated_status"] = "SKIPPED_STALE_INPUT"
                entry["blocks_publication"] = False
                entry["status"] = "DATA_BLOCKED"
                entry["why"] = f"CALIBRATION_COMPONENT_SKIPPED_ISOLATED: 上游非OK {','.join(bad)}"
                status_by[name] = "DATA_BLOCKED"
            else:
                status_by[name] = "SKIPPED_STALE_INPUT"
            results.append(entry)
            continue
        if needs_token and require_live and not os.environ.get("TUSHARE_TOKEN", "").strip():
            status_by[name] = "DATA_BLOCKED"
            results.append({"step": name, "status": "DATA_BLOCKED", "why": "NO TUSHARE_TOKEN"})
            continue
        t0 = time.time()
        if runner is None:
            env = dict(os.environ)
            env["AR_RUN_ID"] = str(run_id or "STANDALONE")
            env["AR_NIGHTLY_STEP"] = name
            env["AR_NIGHTLY_STAGING"] = "1" if os.path.realpath(base) != os.path.realpath(HERE) else "0"
            if persistent_feature_db:
                env["AR_FEATURE_STORE_DB"] = persistent_feature_db
            if persistent_macro_db:
                env["AR_MACRO_DB"] = persistent_macro_db
            if persistent_funnel_root:
                # 引擎跑在 staging 里,staging 拆了产物就没了。漏斗的 30MB bundle
                # 必须落在 live 观察区才留得住 —— 和 feature store DB 同一模式。
                env["AR_FUNNEL_OUTPUT_ROOT"] = persistent_funnel_root
            if target:
                env["AR_TARGET_TRADE_DATE"] = target
            else:
                env.pop("AR_TARGET_TRADE_DATE", None)
            code, out = _subprocess_runner(cmd, cwd=base, env=env)
        else:
            code, out = runner(cmd)
        status = _classify(code, out)
        entry = {"step": name, "status": status, "exit_code": code,
                 "elapsed_sec": round(time.time() - t0, 2), "tail": out[-1200:]}
        if verify:
            if name == "official_sample" and status == "OK":
                target = read_run_target(base, run_start, run_id)
                if not target:
                    status = "FAILED"
                    entry["why"] = "official_sample 未产出本轮 run_target.json —— 无法钉死 target_trade_date"
            av, adet = verify_step_artifacts(name, target, run_start, base, run_id)
            entry["artifacts"] = adet
            if _SEVERITY.get(av, 5) > _SEVERITY.get(status, 5):
                status = av
            entry["status"] = status
        entry["blocks_publication"] = True
        # governance-mutation: MACRO_M1C_FAILURE_ISOLATION
        # governance-mutation: FUNNEL_NIGHTLY_ISOLATION
        if name in ISOLATED_CALIBRATION_STEPS and status != "OK":
            # A calibration module may fail closed on its own evidence, but it
            # cannot veto unrelated NAV, ledger, or research publication.  The
            # staging layer removes prior Macro derivatives first, so isolation
            # cannot silently republish yesterday's panel as current output.
            entry["isolated_status"] = status
            entry["blocks_publication"] = False
            entry["why"] = entry.get("why") or "CALIBRATION_COMPONENT_FAILED_ISOLATED"
            entry["discarded_artifacts"] = (
                _discard_failed_isolated_outputs(name, base) if verify else []
            )
            status = "DATA_BLOCKED"
            entry["status"] = status
        status_by[name] = status
        results.append(entry)
    non_ok = [
        r for r in results
        if r["status"] != "OK" and r.get("blocks_publication", True)
    ]
    isolated = [
        r for r in results
        if r["status"] != "OK" and not r.get("blocks_publication", True)
    ]
    if verify and run_id:
        status_dir = os.path.join(base, "step_status")
        os.makedirs(status_dir, exist_ok=True)
        for entry in results:
            _atomic_write(os.path.join(status_dir, f"{entry['step']}.json"), {
                "schema": "nightly_step_status/v1",
                "run_id": run_id,
                "target_trade_date": target,
                "step": entry["step"],
                "status": entry["status"],
                "exit_code": entry.get("exit_code"),
                "elapsed_sec": entry.get("elapsed_sec"),
                "why": entry.get("why"),
                "blocks_publication": entry.get("blocks_publication", True),
                "isolated_status": entry.get("isolated_status"),
                "artifacts": entry.get("artifacts", []),
            })
    report = "COMPLETE" if not non_ok else "INCOMPLETE"
    research_quality = []
    for entry in results:
        # governance-mutation: FUNNEL_NIGHTLY_QUALITY_PROPAGATION
        for artifact in entry.get("artifacts", []):
            quality = artifact.get("quality_status")
            if quality and quality != "COMPLETE":
                research_quality.append({
                    "step": entry["step"],
                    "quality": quality,
                    "artifact": artifact.get("artifact"),
                })
        # governance-mutation: MACRO_M1C_FAILURE_VISIBILITY
        if not entry.get("blocks_publication", True):
            research_quality.append({
                "step": entry["step"],
                "quality": "DATA_BLOCKED",
                "artifact": None,
            })
    return {"generated_at": time.strftime("%Y%m%d %H:%M"),
            "orchestrator": "nightly_v4" if verify else "nightly_v2",
            "run_id": run_id,
            "target_trade_date": target,
            "report": report,
            "non_ok_steps": [{"step": r["step"], "status": r["status"]} for r in non_ok],
            "isolated_steps": [
                {
                    "step": r["step"],
                    "status": r["status"],
                    "original_status": r.get("isolated_status"),
                }
                for r in isolated
            ],
            "research_data_quality": (
                "DATA_BLOCKED" if any(item["quality"] == "DATA_BLOCKED" for item in research_quality)
                else "PARTIAL" if research_quality else "COMPLETE"
            ),
            "research_data_gaps": research_quality,
            "steps": results,
            "note": "nightly v4;COMPLETE 由结构化状态、实物、run_id 与统一交易日共同背书。不是买卖指令。"}


def _subprocess_runner(cmd, cwd=None, env=None):
    try:
        p = subprocess.run(cmd, cwd=cwd or HERE, env=env, text=True,
                           capture_output=True, timeout=600)
    except subprocess.TimeoutExpired as e:
        # 审查F2:挂死的步必须变成 FAILED 并继续走完报警,绝不让编排器整体崩掉
        out = ((e.stdout or "") if isinstance(e.stdout, str) else "") +               ((e.stderr or "") if isinstance(e.stderr, str) else "")
        return 124, out + f"\nTIMEOUT after 600s: {' '.join(cmd)}"
    return p.returncode, (p.stdout + p.stderr)


def _alarm(res):
    """终态非 COMPLETE 或存在隔离降级:落旗 + 桌面通知。

    隔离步骤失败时 report 仍是 COMPLETE、退出码仍是 0 —— 这是隔离的本意,不能改。
    但原来这里会因 report==COMPLETE 直接清旗返回,于是隔离失败在运维层完全无声:
    没有旗、没有通知、退出 0,而 isolated_steps 只存在于 JSON 里没人看。
    隔离的意思是"不牵连别人",不是"没人知道"。所以隔离降级照样报警,只是用不同
    的标题区分,且**不改变退出码**。
    """
    try:
        isolated = res.get("isolated_steps") or []
        # governance-mutation: FUNNEL_NIGHTLY_ISOLATED_ALARM
        if res["report"] == "COMPLETE" and not isolated:
            if os.path.exists(ALARM_FLAG):
                os.remove(ALARM_FLAG)
            return
        degraded_only = res["report"] == "COMPLETE" and bool(isolated)
        with open(ALARM_FLAG, "w", encoding="utf-8") as fh:
            json.dump({"at": res["generated_at"], "non_ok": res["non_ok_steps"],
                       "isolated": isolated, "degraded_only": degraded_only}, fh,
                      ensure_ascii=False)
        if degraded_only:
            title = "AR 夜链 COMPLETE(隔离降级)"
            bad = ",".join(f"{s['step']}={s['status']}" for s in isolated[:4])
        else:
            title = "AR 夜链 INCOMPLETE"
            bad = ",".join(f"{s['step']}={s['status']}" for s in res["non_ok_steps"][:4])
        subprocess.run(["osascript", "-e",
                        f'display notification "{bad}" with title "{title}"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def _print_terminal_report(res, output_path=OUT):
    """Emit one run-scoped log segment for launchd acceptance.

    launchd appends to the same stdout file.  The run marker therefore has to
    precede every step line; an acceptance reader can ignore an older funnel OK
    instead of treating it as evidence for the latest run.
    """
    # governance-mutation: NIGHTLY_ACCEPTANCE_RUN_CONTEXT_LOG
    print(
        f"[run] run_id={res.get('run_id')} "
        f"target_trade_date={res.get('target_trade_date')}"
    )
    for step in res["steps"]:
        print(f"{step['step']}: {step['status']}")
    print(
        f"[report] {res['report']}  data_quality={res.get('data_quality')}  "
        f"run_id={res.get('run_id')}  target={res.get('target_trade_date')}  "
        f"[written] {output_path}"
    )
    if res.get("degraded_sources"):
        print(f"  degraded: {res['degraded_sources']}")
    print("不是买卖指令;研究信号,human executes.")


def selftest():
    checks = []

    # 1) 全 OK 路径:顺序正确、终态 COMPLETE
    calls = []
    res = run_steps(lambda c: (calls.append(c[1]) or (0, "ok")), require_live=False)
    checks.append(("依赖序执行全部步骤", calls == [c[1] for _, c, _, _ in STEPS]))
    checks.append(("全OK ⇒ COMPLETE", res["report"] == "COMPLETE"))

    # 2) 根失败传染:official_sample FAILED ⇒ 回填/仓位复审/晋级必跳,轮动链不受影响,
    #    export 照常运行(诚实性在逐源戳里,跳过只会留更旧的契约)
    def fail_root(cmd):
        return (1, "boom") if cmd[1] == "run_official_sample.py" else (0, "ok")
    res2 = run_steps(fail_root, require_live=False)
    st = {r["step"]: r["status"] for r in res2["steps"]}
    checks.append(("根失败 ⇒ FAILED", st["official_sample"] == "FAILED"))
    checks.append(("回填被跳", st["fwd_backfill"] == "SKIPPED_STALE_INPUT"))
    checks.append(("仓位复审被跳", st["position_review"] == "SKIPPED_STALE_INPUT"))
    checks.append(("晋级被跳(F4新边)", st["setup_promoter"] == "SKIPPED_STALE_INPUT"))
    checks.append(("导出仍运行(设计决定)", st["export_contracts"] == "OK"))
    checks.append(("轮动链不受影响", st["rotation_panel"] == "OK"))
    checks.append(("终态 INCOMPLETE", res2["report"] == "INCOMPLETE"))

    # 3) 状态协议(F3/F16)
    def blocked_final_line(cmd):
        if cmd[1] == "watch_dynamic.py":
            return (0, "工作正常\nDATA_BLOCKED: 名单为空")
        return (0, "ok")
    res3 = run_steps(blocked_final_line, require_live=False)
    st3 = {r["step"]: r["status"] for r in res3["steps"]}
    checks.append(("尾行blocked ⇒ DATA_BLOCKED", st3["watch_dynamic"] == "DATA_BLOCKED"))
    checks.append(("其下游(闸门/电池/晋级)被跳", st3["red_flag_gate"] == "SKIPPED_STALE_INPUT"
                   and st3["full_battery"] == "SKIPPED_STALE_INPUT"
                   and st3["setup_promoter"] == "SKIPPED_STALE_INPUT"))

    def mid_note_ok(cmd):
        if cmd[1] == "court_wakeup.py":
            return (0, "⛔ 某票: DATA_BLOCKED: 20日行情缺失\n完成,其余7票正常\n不是买卖指令")
        return (0, "ok")
    res4 = run_steps(mid_note_ok, require_live=False)
    st4 = {r["step"]: r["status"] for r in res4["steps"]}
    checks.append(("逐项提示不误伤整步(F3)", st4["court_wakeup"] == "OK"))

    def blocked_nonzero(cmd):
        if cmd[1] == "run_official_sample.py":
            return (1, "DATA_BLOCKED: settlement-date mismatch")
        return (0, "ok")
    res5 = run_steps(blocked_nonzero, require_live=False)
    st5 = {r["step"]: r["status"] for r in res5["steps"]}
    checks.append(("非零+blocked ⇒ DATA_BLOCKED非FAILED(F16)",
                   st5["official_sample"] == "DATA_BLOCKED"))
    checks.append(("免责句在", "不是买卖指令" in res5["note"]))

    # 4) preflight 反例(P0-B):临时目录注入假账本,绝不触碰真账本
    import tempfile

    def _fixture(tmp, sigs, fund_cash=100.0, nav_cash=100.0, n_pos=0, orders=(),
                 skip=()):
        os.makedirs(os.path.join(tmp, "model_fund"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "samples"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "reports"), exist_ok=True)

        def w(rel, obj):
            with open(os.path.join(tmp, rel), "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False)
        w("paper_signal_log.json", sigs)
        w("model_fund/fund.json", {"initial_capital": 100.0, "cash": fund_cash})
        w("model_fund/nav_history.json",
          [{"date": "20260730", "nav": 100.0, "cash": nav_cash, "n_positions": n_pos}])
        w("model_fund/orders.json", list(orders))
        w("samples/20260730.json", {"timestamp": "20260730 close"})
        w("reports/20260730.json", {"report_date": "20260730"})
        for fn in FRESHNESS_FILES:
            if fn not in skip:
                w(fn, {})
        return tmp

    good_sig = {"signal_id": "s1", "ticker": "600000.SH",
                "timestamp": "20260730 close", "returns": None, "horizon": ["1d", "3d"]}
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight 好账本 ⇒ PASS(夹具自证非永假)",
                       preflight(base=_fixture(tmp, [good_sig]))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        bad = dict(good_sig, timestamp="20269999 close")
        checks.append(("preflight 假日期20269999 ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [bad]))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight 重复signal_id ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [good_sig, dict(good_sig)]))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight 坏horizon(非t+N非列表形) ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [dict(good_sig, horizon="随缘")]))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight horizon='t+5' ⇒ PASS",
                       preflight(base=_fixture(tmp, [dict(good_sig, horizon="t+5")]))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight nav末行cash≠fund.cash ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [good_sig], nav_cash=50.0))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight filled数≠n_positions ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [good_sig], n_pos=2))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("preflight 缺watch_dynamic ⇒ FAIL",
                       not preflight(base=_fixture(tmp, [good_sig],
                                                   skip=("watch_dynamic.json",)))["pass"]))
    with tempfile.TemporaryDirectory() as tmp:
        base = _fixture(tmp, [good_sig])
        old = time.time() - 40 * 3600
        os.utime(os.path.join(base, "watch_dynamic.json"), (old, old))
        pf = preflight(base=base)
        checks.append(("preflight 契约mtime>36h ⇒ WARN不阻断", pf["pass"] and pf["warns"] != []))

    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"run_nightly v4 selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def _valid_ts8(ts):
    """真实日期校验(P0-B):timestamp 前8位必须能被 datetime 严格解析。
    20269999 这类"位数对但不是日期"的时间戳必须失败(旧正则 20\\d{6} 放行了它)。"""
    try:
        datetime.datetime.strptime(str(ts)[:8], "%Y%m%d")
        return True
    except ValueError:
        return False


def _valid_horizon(h):
    """horizon 字段若存在必须形态合法:
    - 字符串:形如 t+数字(如 "t+5");
    - 列表(现实账本 117 条全为此形,严格拒列表会永久 FAIL 整条夜链):
      每个元素必须是 intraday / N d / t+N 之一。其余形态一律 FAIL。"""
    if isinstance(h, str):
        return re.fullmatch(r"t\+\d+", h) is not None
    if isinstance(h, list) and h:
        return all(isinstance(x, str) and re.fullmatch(r"(intraday|\d+d|t\+\d+)", x)
                   for x in h)
    return False


def preflight(base=None, now=None):
    """首跑前体检:真实读取账本与引擎文件,校验 schema 与依赖,不联网不写盘。
    base 仅注入账本/契约文件位置(供 selftest 用临时目录造反例,不碰真账本);
    STEPS 依赖图与脚本存在性永远查 HERE(那是代码布局,不是数据)。
    返回 {"pass": bool, "checks": [(name, ok)], "failures": [...], "warns": [...]}。"""
    base = base or HERE
    now = time.time() if now is None else now
    checks, warns = [], []
    # 0) R-014/R-015 三方一致性:intent / commit / projection 必须对得上。
    #    悬空 intent、孤立 commit、双终态、投影哈希不符 —— 任何一条都表示上一次
    #    夜链中途崩溃或账本被动过,不得在这种状态上继续跑引擎。
    try:
        sys.path.insert(0, HERE)
        import registry as _reg
        _lp = _reg.ledger_path_for(os.path.join(base, "paper_signal_log.json"))
        if os.path.exists(_lp):
            _evs = _reg.read_events(_lp)
            _intents, _C, _A = _reg._terminal_states(_evs)   # intents 是 dict
            _I = set(_intents)
            _rows = _reg.load_signal_log_strict(os.path.join(base, "paper_signal_log.json"))
            dangling = sorted(_I - _C - _A)
            orphan = sorted(_C - _I)
            _ei, _ec, _ea = _reg._evaluation_states(_evs)
            eval_dangling = sorted(set(_ei) - set(_ec) - _ea)
            eval_orphan = sorted(set(_ec) - set(_ei))
            bijection_errors = _reg.audit_projection_bijection(_rows, _evs)
            checks.append((f"注册/判分 WAL 与已提交投影三方一致(双向,异常 n={len(bijection_errors)})",
                           not bijection_errors))
            if bijection_errors:
                print(f"  ✗ WAL/投影不一致: {bijection_errors[:5]}")
            checks.append((f"判分事务无悬空 intent(n={len(eval_dangling)})",
                           not eval_dangling))
            checks.append((f"判分事务无孤立 commit(n={len(eval_orphan)})",
                           not eval_orphan))
            # ── B10 abort 行残留:被中止事务的投影必须已隔离,不得留在账本 ──
            leftover = [r.get("signal_id") for r in _rows
                        if r.get("registry_txn_id") in _A]
            checks.append((f"无 abort 残留投影(n={len(leftover)})", not leftover))
            if leftover:
                print(f"  ✗ 已中止事务的投影仍在账本: {leftover[:5]} —— 应在隔离区")
            checks.append((f"事务无悬空 intent(n={len(dangling)})", not dangling))
            checks.append((f"事务无孤立 commit(n={len(orphan)})", not orphan))
            if dangling: print(f"  ✗ 悬空 intent: {dangling[:5]} —— 先跑 registry.recover_pending")
            if orphan:   print(f"  ✗ 孤立 commit: {orphan[:5]}")
            if eval_dangling: print(f"  ✗ 悬空 evaluation intent: {eval_dangling[:5]}")
            if eval_orphan: print(f"  ✗ 孤立 evaluation commit: {eval_orphan[:5]}")
        else:
            warns.append("事件账本尚未建立(R-015 未接线)—— 三方一致性未检")
    except Exception as e:                       # noqa: BLE001 — fail-closed
        checks.append((f"事务一致性检查可执行({type(e).__name__})", False))
        print(f"  ✗ 事务一致性检查失败: {e}")
    # 1) 信号账本:可解析 + returns 类型 + NOT_SCORABLE 声明 + 真实日期 + horizon + id 唯一
    try:
        with open(os.path.join(base, "paper_signal_log.json"), encoding="utf-8") as fh:
            log = json.load(fh)
        sigs = log if isinstance(log, list) else log.get("signals", [])
        checks.append((f"信号账本可解析(n={len(sigs)})", True))
        bad_ret = [x.get("signal_id") for x in sigs
                   if "returns" in x and x["returns"] is not None and not isinstance(x["returns"], dict)]
        checks.append(("returns 类型合法(dict/null)", bad_ret == []))
        if bad_ret: print(f"  ✗ 异型 returns: {bad_ret[:5]}")
        bad_tk = [x.get("signal_id") for x in sigs
                  if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(x.get("ticker","")))
                  and not str(x.get("scoring") or "") == "NOT_SCORABLE"]
        checks.append(("非标资产均已声明 NOT_SCORABLE", bad_tk == []))
        if bad_tk: print(f"  ✗ 非标 ticker 未声明: {bad_tk[:5]}")
        bad_ts = [x.get("signal_id") for x in sigs if not _valid_ts8(x.get("timestamp", ""))]
        checks.append(("时间戳前8位为真实日期(datetime严格解析)", bad_ts == []))
        if bad_ts: print(f"  ✗ 坏时间戳: {bad_ts[:5]}")
        bad_hz = [x.get("signal_id") for x in sigs
                  if "horizon" in x and not _valid_horizon(x["horizon"])]
        checks.append(("horizon 形态合法(t+N 或既有列表形)", bad_hz == []))
        if bad_hz: print(f"  ✗ 坏 horizon: {bad_hz[:5]}")
        ids = [x.get("signal_id") for x in sigs]
        dup = sorted({i for i in ids if i is not None and ids.count(i) > 1})
        id_ok = dup == [] and None not in ids
        checks.append(("signal_id 全局唯一且非空", id_ok))
        if not id_ok: print(f"  ✗ 重复signal_id: {dup[:5]}" + (" +存在null id" if None in ids else ""))
    except Exception as e:
        checks.append((f"信号账本解析: {e}", False))
    # 2) 基金账本三件可解析 + 三账一致性(P0-B)
    fund = navh = orders = None
    for f in ("model_fund/fund.json", "model_fund/nav_history.json", "model_fund/orders.json"):
        try:
            with open(os.path.join(base, f), encoding="utf-8") as fh:
                data = json.load(fh)
            checks.append((f"{f} 可解析", True))
            if f.endswith("fund.json"): fund = data
            elif f.endswith("nav_history.json"): navh = data
            else: orders = data
        except Exception as e:
            checks.append((f"{f}: {e}", False))
    if fund is not None and navh is not None and orders is not None:
        try:
            last = navh[-1]  # nav 为空 ⇒ IndexError ⇒ fail-closed(无末行无法对账)
            cash_ok = abs(float(last["cash"]) - float(fund["cash"])) <= 1.0
            checks.append(("三账一致:nav末行cash==fund.cash(±1元)", cash_ok))
            if not cash_ok:
                print(f"  ✗ cash不一致: nav末行{last['cash']} vs fund {fund['cash']}")
            filled = sum(1 for o in orders if o.get("status") == "filled")
            pos_ok = filled == int(last["n_positions"])
            checks.append(("三账一致:orders filled数==nav末行n_positions", pos_ok))
            if not pos_ok:
                print(f"  ✗ 持仓数不一致: filled={filled} vs n_positions={last['n_positions']}")
        except Exception as e:
            checks.append((f"三账一致性无法判定(缺数据≠通过): {e}", False))
    # 3) STEPS 依赖闭合(引用的依赖都是已定义步骤,且无前向引用)
    seen, dep_ok = set(), True
    for name, _, _, deps in STEPS:
        if any(d not in seen for d in deps):
            dep_ok = False; print(f"  ✗ {name} 依赖了未定义/后置步骤: {deps}")
        seen.add(name)
    checks.append(("依赖图闭合无前向引用", dep_ok))
    # 4) 各步骤脚本文件存在
    miss = [c[1] for _, c, _, _ in STEPS if not os.path.exists(os.path.join(HERE, c[1]))]
    checks.append((f"全部步骤脚本存在({len(STEPS)}步)", not miss))
    if miss: print(f"  ✗ 缺脚本: {miss}")
    # 5) 依赖语义干跑(fake runner)
    res = run_steps(lambda c: (0, "ok"), require_live=False)
    checks.append(("干跑全通 ⇒ COMPLETE", res["report"] == "COMPLETE"))
    # 6) 跨层事实一致性(审计:半程迁移 + 本身曾 fail-open,现为 fail-closed)
    try:
        from consistency import scan_dirs as _scan
        cons = _scan(base)
        checks.append(("跨层事实一致性(近5日样本/报告;损坏与缺失均阻断)", not cons))
        for c in cons[:8]:
            print(f"  ✗ {c}")
    except Exception as e:
        checks.append((f"跨层一致性检查执行失败: {e}", False))

    # 7) 关键契约 freshness:缺文件 FAIL;mtime 超 36h 仅 WARN 列出,不阻断
    for fn in FRESHNESS_FILES:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            checks.append((f"关键契约存在: {fn}", False))
            continue
        checks.append((f"关键契约存在: {fn}", True))
        age_h = (now - os.path.getmtime(p)) / 3600.0
        if age_h > FRESH_WARN_H:
            warns.append(f"{fn} mtime {age_h:.1f}h > {FRESH_WARN_H}h(WARN,不阻断)")
    failures = [str(n) for n, ok in checks if not ok]
    return {"pass": not failures, "checks": checks, "failures": failures, "warns": warns}


def _print_preflight(pf):
    for name, ok in pf["checks"]:
        print(("  ✓ " if ok else "  ✗ ") + str(name))
    for w in pf["warns"]:
        print("  ⚠ " + w)
    print(f"preflight: {'PASS' if pf['pass'] else 'FAIL'}(零网络零写入)")


def _recover_phase(base=None):
    """恢复阶段:必须在 preflight 硬闸**之前**跑。

    上一版把 recover_pending 放在 official_sample 步内 —— 而 preflight 遇到
    悬空 intent 会先 FAIL 整条夜链,官方样本步永远执行不到:
    真实崩溃后,夜链永远走不到自己的恢复器。恢复是给硬闸清路的,不能站在硬闸后面。
    恢复自身失败(链损坏/双终态)不吞:打印后交给 preflight 判死,fail-closed。"""
    try:
        base = base or HERE
        sys.path.insert(0, HERE)
        import registry as _reg
        _log = os.path.join(base, "paper_signal_log.json")
        _lp = _reg.ledger_path_for(_log)
        if not os.path.exists(_lp):
            return None
        r = _reg.recover_pending(_lp, _log)
        er = _reg.recover_evaluations(_lp, _log)
        if r["pending_examined"]:
            print(f"[recover] 悬空事务处理: 前滚 {len(r['rolled_forward'])} · "
                  f"重建 {len(r['rebuilt'])} · 作废 {len(r['aborted'])} · 不符 {len(r['mismatch'])}")
        if er["pending_examined"]:
            print(f"[recover] 悬空判分处理: 检查 {er['pending_examined']} · "
                  f"前滚 {er['rolled_forward']}")
        return {"registration": r, "evaluation": er}
    except Exception as e:                       # noqa: BLE001
        print(f"[recover] 恢复阶段失败: {e} —— fail-closed,本轮判 INCOMPLETE,引擎不得启动")
        return False


RUNS_DIR = os.path.join(HERE, "runs")
RUN_STATE = os.path.join(HERE, "run_state.json")
NIGHTLY_LOCK = os.path.join(HERE, "nightly.lock")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PUBLICATION_STATE = os.path.join(HERE, "publication_state.json")
# 回滚只覆盖**可再生的派生产物**;事务态(信号账本/WAL/锚点/隔离区)绝不回滚 ——
# WAL 是 append-only 的,回滚它就是删记录;账本一致性由 R-014 事务 + recover 保证。
ROLLBACK_EXCLUDE = {"paper_signal_log.json"}


def _declared_artifacts():
    out = []
    for arts in ARTIFACTS.values():
        for rel, _, _ in arts:
            if os.path.basename(rel) not in ROLLBACK_EXCLUDE:
                out.append(rel)
    return sorted(set(out))


def _snapshot_before(run_id):
    """开跑前把全部派生产物拷进 runs/<run_id>/before/ —— 崩溃回滚的物质基础。"""
    import shutil
    bdir = os.path.join(RUNS_DIR, run_id, "before")
    os.makedirs(bdir, exist_ok=True)
    existed = []
    for rel in _declared_artifacts():
        src = os.path.join(HERE, rel)
        if os.path.exists(src):
            existed.append(rel)
            dst = os.path.join(bdir, rel.replace(os.sep, "__"))
            shutil.copy2(src, dst)
    _atomic_write(os.path.join(bdir, "snapshot.json"), {"existed": existed})
    return bdir


def _rollback_from(run_id):
    """把派生产物恢复到某轮开跑前的状态(B6:不留半新半旧的混合态)。"""
    import shutil
    bdir = os.path.join(RUNS_DIR, run_id, "before")
    if not os.path.isdir(bdir):
        return 0
    state_path = os.path.join(bdir, "snapshot.json")
    if not os.path.exists(state_path):
        raise RuntimeError("回滚快照缺 snapshot.json —— fail-closed,不得猜哪些文件原先存在")
    with open(state_path, encoding="utf-8") as fh:
        existed = set(json.load(fh).get("existed") or [])
    n = 0
    for rel in _declared_artifacts():
        dst = os.path.join(HERE, rel)
        src = os.path.join(bdir, rel.replace(os.sep, "__"))
        if rel in existed:
            if not os.path.exists(src):
                raise RuntimeError(f"回滚快照声明存在却缺副本: {rel}")
            os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
            shutil.copy2(src, dst); n += 1
        elif os.path.exists(dst):
            os.remove(dst); n += 1
    return n


def _crash_check_and_rollback():
    """上一轮留下 run_state 标记 = 中途崩溃:派生产物是混合态,先回滚再开新轮。"""
    import nightly_publish as _np
    publish_recovery = _np.recover_interrupted_publish(
        PUBLICATION_STATE, HERE, REPO_ROOT)
    if not os.path.exists(RUN_STATE):
        return ({"publication": publish_recovery} if publish_recovery else None)
    try:
        with open(RUN_STATE, encoding="utf-8") as fh:
            prev = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"run_state 不可解析 —— fail-closed: {exc}") from exc
    if prev.get("orchestrator") == "nightly_v4":
        # v4 引擎只写 staging。若 commit marker 已落,保留已提交发布;
        # 若崩在发布中,上面的 publication journal 已回滚。
        if ((publish_recovery or {}).get("status") == "COMMITTED_VERIFIED"
                and (publish_recovery or {}).get("run_id") == prev.get("run_id")):
            os.remove(RUN_STATE)
            print(f"[crash-recovery] 上一轮 {prev.get('run_id')} 已提交发布,"
                  "仅终态报告未完成;已验证 commit marker 并保留产物")
            return {
                "committed_run_recovered": prev.get("run_id"),
                "restored": 0,
                "publication": publish_recovery,
            }
        n = (publish_recovery or {}).get("restored", 0)
    else:
        n = _rollback_from(prev.get("run_id", ""))
    os.remove(RUN_STATE)
    print(f"[crash-recovery] 上一轮 {prev.get('run_id')} 中途崩溃,已回滚 {n} 个派生产物"
          f"(事务态不回滚,由 WAL recover 保证)")
    return {"rolled_back_run": prev.get("run_id"), "restored": n,
            "publication": publish_recovery}


def _prune_runs(keep=14):
    try:
        runs = sorted(os.listdir(RUNS_DIR))
        for r in runs[:-keep]:
            import shutil
            shutil.rmtree(os.path.join(RUNS_DIR, r), ignore_errors=True)
    except FileNotFoundError:
        pass


def _atomic_write(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)
    parent_fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _clear_run_state_if_terminal(run_id, terminal_written, state_path=None):
    """Ordinary exceptions must leave the marker for next-run recovery."""
    state_path = state_path or RUN_STATE
    if not terminal_written or not os.path.exists(state_path):
        return False
    try:
        with open(state_path, encoding="utf-8") as fh:
            current = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return False
    if current.get("run_id") != run_id:
        return False
    os.remove(state_path)
    return True


def _collect_data_quality(base=None):
    """把 export 层已算好的**信息完整度**提到夜链顶层。

    `report` 与 `data_quality` 是两个正交维度:前者说流水线有没有跑完,
    后者说这轮拿到的数据全不全。只报 report=COMPLETE 会让「隔夜锚缺
    NVDA/SOX/TSM」这类降级在顶层消失。取不到 meta ⇒ UNKNOWN,
    **不假装 COMPLETE**(缺数据 ≠ 通过)。
    """
    meta_path = os.path.join(base or HERE, "..", "..", "public", "data", "v2", "meta.json")
    try:
        with open(os.path.abspath(meta_path), encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        return {"data_quality": "UNKNOWN", "degraded_sources": [],
                "business_contract_count": None}
    if not isinstance(meta, dict):
        return {"data_quality": "UNKNOWN", "degraded_sources": [],
                "business_contract_count": None}
    return {
        "data_quality": _normalize_data_quality(meta.get("data_quality")),
        "degraded_sources": list(meta.get("degraded_sources") or []),
        "business_contract_count": meta.get("business_contract_count"),
    }


def _merge_data_quality(contract_quality, research_quality):
    order = {"COMPLETE": 0, "PARTIAL": 1, "DATA_BLOCKED": 2, "UNKNOWN": 3}
    left = _normalize_data_quality(contract_quality)
    right = _normalize_data_quality(research_quality)
    return left if order.get(left, 3) >= order.get(right, 3) else right


def _execute_nightly():
    """在已持有全局锁时执行一轮。普通异常不清 run_state,交给下一轮恢复。"""
    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}_{uuid.uuid4().hex[:8]}"
    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    terminal_written = False
    crash_info = _crash_check_and_rollback()
    _atomic_write(RUN_STATE, {
        "schema": "nightly_run_state/v1",
        "orchestrator": "nightly_v4",
        "run_id": run_id,
        "phase": "PREPARING",
        "run_dir": run_dir,
        "started_at": time.strftime("%Y%m%d %H:%M:%S"),
    })

    try:
        # ── 恢复阶段(写路径,只在正式运行做)→ P0-B 硬闸 ──
        recover_ok = _recover_phase()
        pf = preflight()
        _print_preflight(pf)
        if recover_ok is False or not pf["pass"]:
            res = {"generated_at": time.strftime("%Y%m%d %H:%M"),
                   "orchestrator": "nightly_v4", "run_id": run_id,
                   "report": "INCOMPLETE",
                   "published": False,
                   "crash_recovery": crash_info,
                   "preflight": {"pass": bool(pf["pass"]), "failures": pf["failures"],
                                 "warns": pf["warns"],
                                 "recover_failed": recover_ok is False},
                   "non_ok_steps": [{"step": "preflight", "status": "FAILED"}],
                   "steps": [],
                   "note": "preflight/恢复 FAIL ⇒ 硬闸:未启动任何引擎。不是买卖指令;研究信号,human executes."}
            _atomic_write(OUT, res)
            _atomic_write(os.path.join(run_dir, "result.json"), res)
            print(f"[report] INCOMPLETE(硬闸,引擎未启动) [written] {OUT}")
            print("不是买卖指令;研究信号,human executes.")
            _alarm(res)
            terminal_written = True
            return 1

        import nightly_publish as _np
        stage = _np.prepare_stage(HERE, REPO_ROOT, run_dir)
        _atomic_write(RUN_STATE, {
            "schema": "nightly_run_state/v1", "orchestrator": "nightly_v4",
            "run_id": run_id, "phase": "RUNNING_STAGING", "run_dir": run_dir,
            "stage_et": stage["et"], "started_at": time.strftime("%Y%m%d %H:%M:%S"),
        })
        require_live = "--allow-data-blocked" not in sys.argv
        res = run_steps(
            require_live=require_live,
            verify=True,
            base=stage["et"],
            run_id=run_id,
            persistent_feature_db=os.path.join(
                REPO_ROOT, "data_history", "feature_store.sqlite3"
            ),
            persistent_macro_db=os.path.join(
                REPO_ROOT, "data_history", "macro_os.sqlite3"
            ),
            persistent_funnel_root=os.path.join(
                REPO_ROOT, "data_history", "funnel"
            ),
        )
        res["preflight"] = {"pass": True, "warns": pf["warns"]}
        # ── 状态聚合:data_quality 必须上到夜链顶层 ──
        # report=COMPLETE 只说明流水线成功;若宏观等来源是 PARTIAL,
        # 只读 nightly_run.report 的消费方会误以为信息完整。两个维度都要在顶层可见。
        contract_quality = _collect_data_quality(stage["et"])
        res["contract_data_quality"] = contract_quality["data_quality"]
        res["data_quality"] = _merge_data_quality(
            contract_quality["data_quality"], res.get("research_data_quality")
        )
        res["degraded_sources"] = list(contract_quality["degraded_sources"])
        for gap in res.get("research_data_gaps", []):
            source = f"{gap['step']}:{gap['quality']}"
            if source not in res["degraded_sources"]:
                res["degraded_sources"].append(source)
        res["business_contract_count"] = contract_quality["business_contract_count"]
        res["crash_recovery"] = crash_info

        if res["report"] == "COMPLETE":
            stage_pf = preflight(base=stage["et"])
            res["staging_preflight"] = {
                "pass": stage_pf["pass"], "failures": stage_pf["failures"],
                "warns": stage_pf["warns"],
            }
            if not stage_pf["pass"]:
                res["report"] = "INCOMPLETE"
                res["non_ok_steps"].append({"step": "staging_preflight", "status": "FAILED"})

        if res["report"] == "COMPLETE":
            _atomic_write(RUN_STATE, {
                "schema": "nightly_run_state/v1", "orchestrator": "nightly_v4",
                "run_id": run_id, "phase": "PUBLISHING", "run_dir": run_dir,
                "target_trade_date": res.get("target_trade_date"),
            })
            try:
                manifest = _np.publish_stage(
                    run_id, res.get("target_trade_date"), stage,
                    HERE, REPO_ROOT, run_dir, PUBLICATION_STATE)
                res["published"] = True
                res["publication_manifest"] = manifest
            except Exception as exc:
                res["report"] = "INCOMPLETE"
                res["published"] = False
                res["non_ok_steps"].append({"step": "publication", "status": "FAILED"})
                res["publication_error"] = f"{type(exc).__name__}: {exc}"
        else:
            res["published"] = False

        _atomic_write(OUT, res)
        _atomic_write(os.path.join(run_dir, "result.json"), res)
        _print_terminal_report(res)
        _alarm(res)
        _prune_runs()
        terminal_written = True
        if any(s["status"] == "FAILED" for s in res["steps"]):
            return 1
        if res["report"] != "COMPLETE":
            return 2
        return 0
    finally:
        # 只有明确写出终态报告才清标记。普通 Python 异常与 SIGKILL 都保留,
        # 下一轮依据 staging/publication journal 恢复。旧版 finally 会误清普通异常。
        _clear_run_state_if_terminal(run_id, terminal_written)


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    if "--preflight" in sys.argv or "--preflight-only" in sys.argv:
        # --preflight 是**只读**检查:不做恢复、不写任何文件 ——
        # 上一版在这里跑 recover(会写 WAL)却自称"零写入",CI 也把它当只读。
        pf = preflight()
        _print_preflight(pf)
        return 0 if pf["pass"] else 1

    # 锁的关闭由 with 保证,包括 crash recovery / preflight 自身抛错的路径。
    import fcntl
    with open(NIGHTLY_LOCK, "w") as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("REFUSED: 另一轮夜链正在运行(nightly.lock 被持有)—— 不并发跑两轮")
            return 1
        try:
            return _execute_nightly()
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


if __name__ == "__main__":
    sys.exit(main() or 0)
