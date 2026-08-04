#!/usr/bin/env python3
"""
run_nightly.py — Nightly v2:post-close 强制流水线(2026-07-29 审查驱动重构)。

v2 变化(相对 v1 平铺十步):
  1. 补齐闭环:官方定盘结算 → 收益回填 → 红旗闸门 → 六维电池 → 契约导出;
  2. 依赖语义:上游 FAILED/DATA_BLOCKED 时,下游标 SKIPPED_STALE_INPUT,绝不读旧数据装新;
  3. 终态诚实:任何非 OK ⇒ report=INCOMPLETE,退出码 FAILED=1 / INCOMPLETE=2,
     并落 /tmp/ar-nightly-incomplete 报警旗(桌面通知 best-effort);
  4. DATA_BLOCKED 不再伪装成功(v1 第 94 行问题)。

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
    ("fwd_backfill", ["python3", "run_post_close_report.py", "--backfill-only"], True,
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
]

# ── 产物契约(B2/B3/B4):步骤状态由**产物实物**判定,不再猜 stdout ──
# (path, date_key, fresh_required):date_key 非空 ⇒ 该字段前 8 位必须 == target;
# fresh_required ⇒ 本轮必须重写(mtime >= run_start)。
# rotation_panel / rotation_validation / promotion_queue 顶层无日期戳(工程债 R-043:
# 引擎补 as_of),暂只能验 mtime —— 在此明记,不假装验过日期。
ARTIFACTS = {
    "official_sample":       [("run_target.json", "trade_date", True)],
    "fwd_backfill":          [("paper_signal_log.json", None, False)],
    "rotation_panel":        [("rotation_panel.json", None, True)],
    "momentum_prefilter":    [("momentum_prefilter.json", "as_of", True)],
    "rotation_stats":        [("rotation_stats.json", "as_of", True)],
    "rotation_validation":   [("rotation_validation.json", None, True)],
    "lead_precursor":        [("lead_precursor.json", "as_of", True)],
    "overnight_anchor_frame": [("overnight_anchor.json", "as_of", True)],
    "court_wakeup":          [("court_wakeup.json", "as_of", True)],
    "watch_dynamic":         [("watch_dynamic.json", "generated_at", True)],
    "position_review":       [("position_review.json", "as_of", True)],
    "court_10d":             [("court_10d.json", None, True)],
    "red_flag_gate":         [("red_flags.json", "checked_at", True)],
    "full_battery":          [("battery.json", "checked_at", True)],
    "setup_promoter":        [("promotion_queue.json", None, True)],
    "export_contracts":      [(os.path.join("..", "..", "public", "data", "v2", "meta.json"),
                               None, True)],
}

# 状态精度(越大越糟);步骤终态 = max(进程判定, 各产物判定)
_SEVERITY = {"OK": 0, "PARTIAL": 1, "DATA_BLOCKED": 2, "STALE_OUTPUT": 3,
             "DATE_MISMATCH": 4, "FAILED": 5}


def _artifact_status_scan(step, data):
    """个别产物的内部状态字段(仅对语义明确的两个,避免把逐票 DATA_BLOCKED
    的诚实条目误判成整步失败 —— 误报的下场是闸门被人关掉)。"""
    if step == "full_battery":
        bad = [r.get("ts_code") for r in (data.get("results") or [])
               if (r.get("completeness") or {}).get("verdict") not in (None, "COMPLETE")]
        return ("PARTIAL", f"电池非完整: {bad[:3]}") if bad else ("OK", "")
    if step == "export_contracts":
        txt = json.dumps(data, ensure_ascii=False)
        if "STALE_INPUT" in txt or '"PARTIAL"' in txt:
            return "PARTIAL", "契约含 STALE_INPUT/PARTIAL 标记"
    return "OK", ""


def verify_step_artifacts(step, target, run_start, base=None):
    """产物实物校验:存在 → 可解析 → 本轮已重写 → 日期==target → 内部状态。
    返回 (最重状态, [逐产物明细])。这是 B2 的核心:COMPLETE 必须由实物背书。"""
    base = base or HERE
    worst, details = "OK", []
    for rel, date_key, fresh_required in ARTIFACTS.get(step, []):
        path = os.path.join(base, rel)
        d = {"artifact": rel, "verdict": "OK", "why": ""}
        if not os.path.exists(path):
            d.update(verdict="FAILED", why="产物不存在")
        else:
            try:
                data = json.load(open(path, encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                data = None
                d.update(verdict="FAILED", why=f"不可解析: {e}")
            if data is not None:
                if fresh_required and os.path.getmtime(path) < run_start - 2:
                    d.update(verdict="STALE_OUTPUT", why="本轮未重写(mtime 早于本轮开始)")
                elif date_key and target:
                    v = str((data.get(date_key) if isinstance(data, dict) else "") or "")[:8]
                    if v != target:
                        d.update(verdict="DATE_MISMATCH",
                                 why=f"{date_key}={v or '缺失'} ≠ target {target}")
                if d["verdict"] == "OK" and isinstance(data, dict):
                    sv, swhy = _artifact_status_scan(step, data)
                    if sv != "OK":
                        d.update(verdict=sv, why=swhy)
        details.append(d)
        if _SEVERITY[d["verdict"]] > _SEVERITY[worst]:
            worst = d["verdict"]
    return worst, details


def read_run_target(base=None, run_start=None):
    """本轮 target_trade_date:由 official_sample 写的 run_target.json 提供,
    且必须是本轮写的(mtime 校验)—— 不接受上一轮残留。"""
    p = os.path.join(base or HERE, "run_target.json")
    if not os.path.exists(p):
        return None
    if run_start and os.path.getmtime(p) < run_start - 2:
        return None
    try:
        return str(json.load(open(p, encoding="utf-8")).get("trade_date") or "")[:8] or None
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


def run_steps(runner=None, require_live=True, verify=False, base=None, run_id=None):
    """verify=True(正式路径):步骤终态 = max(进程判定, 产物实物判定)。
    COMPLETE 从此必须由实物背书 —— 进程退 0 + 免责声明不再等于成功(B2/B3)。"""
    runner = runner or _subprocess_runner
    base = base or HERE
    run_start = time.time()
    results, status_by = [], {}
    target = None

    for name, cmd, needs_token, deps in STEPS:
        bad = [d for d in deps if status_by.get(d) != "OK"]
        if bad:
            status_by[name] = "SKIPPED_STALE_INPUT"
            results.append({"step": name, "status": "SKIPPED_STALE_INPUT",
                            "why": f"上游非OK: {','.join(bad)}"})
            continue
        if needs_token and require_live and not os.environ.get("TUSHARE_TOKEN", "").strip():
            status_by[name] = "DATA_BLOCKED"
            results.append({"step": name, "status": "DATA_BLOCKED", "why": "NO TUSHARE_TOKEN"})
            continue
        t0 = time.time()
        code, out = runner(cmd)
        status = _classify(code, out)
        entry = {"step": name, "status": status, "exit_code": code,
                 "elapsed_sec": round(time.time() - t0, 2), "tail": out[-1200:]}
        if verify:
            if name == "official_sample" and status == "OK":
                target = read_run_target(base, run_start)
                if not target:
                    status = "FAILED"
                    entry["why"] = "official_sample 未产出本轮 run_target.json —— 无法钉死 target_trade_date"
            av, adet = verify_step_artifacts(name, target, run_start, base)
            entry["artifacts"] = adet
            if _SEVERITY.get(av, 5) > _SEVERITY.get(status, 5):
                status = av
            entry["status"] = status
        status_by[name] = status
        results.append(entry)

    non_ok = [r for r in results if r["status"] != "OK"]
    report = "COMPLETE" if not non_ok else "INCOMPLETE"
    return {"generated_at": time.strftime("%Y%m%d %H:%M"),
            "orchestrator": "nightly_v3" if verify else "nightly_v2",
            "run_id": run_id,
            "target_trade_date": target,
            "report": report,
            "non_ok_steps": [{"step": r["step"], "status": r["status"]} for r in non_ok],
            "steps": results,
            "note": "nightly v3;COMPLETE 由产物实物背书(存在/可解析/本轮重写/日期==target)。不是买卖指令。"}


def _subprocess_runner(cmd):
    try:
        p = subprocess.run(cmd, cwd=HERE, text=True, capture_output=True, timeout=600)
    except subprocess.TimeoutExpired as e:
        # 审查F2:挂死的步必须变成 FAILED 并继续走完报警,绝不让编排器整体崩掉
        out = ((e.stdout or "") if isinstance(e.stdout, str) else "") +               ((e.stderr or "") if isinstance(e.stderr, str) else "")
        return 124, out + f"\nTIMEOUT after 600s: {' '.join(cmd)}"
    return p.returncode, (p.stdout + p.stderr)


def _alarm(res):
    """终态非 COMPLETE:落旗 + 桌面通知(best-effort,失败不影响退出码)。"""
    try:
        if res["report"] == "COMPLETE":
            if os.path.exists(ALARM_FLAG):
                os.remove(ALARM_FLAG)
            return
        with open(ALARM_FLAG, "w", encoding="utf-8") as fh:
            json.dump({"at": res["generated_at"], "non_ok": res["non_ok_steps"]}, fh,
                      ensure_ascii=False)
        bad = ",".join(f"{s['step']}={s['status']}" for s in res["non_ok_steps"][:4])
        subprocess.run(["osascript", "-e",
                        f'display notification "{bad}" with title "AR 夜链 INCOMPLETE"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


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

        def w(rel, obj):
            with open(os.path.join(tmp, rel), "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False)
        w("paper_signal_log.json", sigs)
        w("model_fund/fund.json", {"initial_capital": 100.0, "cash": fund_cash})
        w("model_fund/nav_history.json",
          [{"date": "20260730", "nav": 100.0, "cash": nav_cash, "n_positions": n_pos}])
        w("model_fund/orders.json", list(orders))
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
    print(f"run_nightly v2 selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
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
            _by = {r.get("signal_id"): r for r in _rows}
            dangling = sorted(_I - _C - _A)
            orphan = sorted(_C - _I)
            bad_proj = []
            _cps = {e["id"]: (e.get("payload") or {}) for e in _evs
                    if e.get("kind") == "register_commit"}
            for _txn in sorted(_C):
                _pl = _intents.get(_txn)
                if not _pl:
                    continue          # 无 intent 的 commit 已由「孤立 commit」检查抓
                _sid = _pl.get("signal_id")
                # 四方强制:投影必须存在、commit payload 必须完整 ——
                # 上一版 commit_payload 传 None、投影缺失也放行,
                # 「intent 在、commit 空、投影不存在」被判为一致。
                _ok, _why = _reg.validate_transaction_projection(
                    _txn, _pl, _by.get(_sid), _cps.get(_txn),
                    require_projection=True, require_commit=True)
                if not _ok:
                    bad_proj.append((_txn, _why[:1]))
            # ── B9 判分交叉核对:v2 注册行的每个 returns 档必须有对应 evaluation 事件 ──
            _evmap = {e["id"]: (e.get("payload") or {}).get("value") for e in _evs
                      if e.get("kind") == "evaluation"}
            bad_eval = []
            for _r in _rows:
                if not _r.get("registry_schema"):
                    continue          # 遗留行:returns 无 WAL,豁免(它们也不进指纹校验)
                for _h, _v in (_r.get("returns") or {}).items():
                    if not isinstance(_v, (int, float)):
                        continue
                    _k = f"{_r.get('signal_id')}:{_h}"
                    if _k not in _evmap or _evmap[_k] != _v:
                        bad_eval.append((_k, _v, _evmap.get(_k)))
            checks.append((f"判分与 WAL 一致(异常 n={len(bad_eval)})", not bad_eval))
            if bad_eval:
                print(f"  ✗ returns 无 WAL 背书或值不符: {bad_eval[:3]} —— 判分被无痕修改")
            # ── B10 abort 行残留:被中止事务的投影必须已隔离,不得留在账本 ──
            leftover = [r.get("signal_id") for r in _rows
                        if r.get("registry_txn_id") in _A]
            checks.append((f"无 abort 残留投影(n={len(leftover)})", not leftover))
            if leftover:
                print(f"  ✗ 已中止事务的投影仍在账本: {leftover[:5]} —— 应在隔离区")
            checks.append((f"事务无悬空 intent(n={len(dangling)})", not dangling))
            checks.append((f"事务无孤立 commit(n={len(orphan)})", not orphan))
            checks.append((f"已提交投影三方一致(异常 n={len(bad_proj)})", not bad_proj))
            if dangling: print(f"  ✗ 悬空 intent: {dangling[:5]} —— 先跑 registry.recover_pending")
            if orphan:   print(f"  ✗ 孤立 commit: {orphan[:5]}")
            if bad_proj: print(f"  ✗ 投影不一致: {bad_proj[:3]}")
        else:
            warns.append("事件账本尚未建立(R-015 未接线)—— 三方一致性未检")
    except Exception as e:                       # noqa: BLE001 — fail-closed
        checks.append((f"事务一致性检查可执行({type(e).__name__})", False))
        print(f"  ✗ 事务一致性检查失败: {e}")
    # 1) 信号账本:可解析 + returns 类型 + NOT_SCORABLE 声明 + 真实日期 + horizon + id 唯一
    try:
        log = json.load(open(os.path.join(base, "paper_signal_log.json")))
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
            data = json.load(open(os.path.join(base, f)))
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
        cons = _scan(HERE)
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


def _recover_phase():
    """恢复阶段:必须在 preflight 硬闸**之前**跑。

    上一版把 recover_pending 放在 official_sample 步内 —— 而 preflight 遇到
    悬空 intent 会先 FAIL 整条夜链,官方样本步永远执行不到:
    真实崩溃后,夜链永远走不到自己的恢复器。恢复是给硬闸清路的,不能站在硬闸后面。
    恢复自身失败(链损坏/双终态)不吞:打印后交给 preflight 判死,fail-closed。"""
    try:
        sys.path.insert(0, HERE)
        import registry as _reg
        _lp = _reg.ledger_path_for(os.path.join(HERE, "paper_signal_log.json"))
        if not os.path.exists(_lp):
            return None
        r = _reg.recover_pending(_lp, os.path.join(HERE, "paper_signal_log.json"))
        if r["pending_examined"]:
            print(f"[recover] 悬空事务处理: 前滚 {len(r['rolled_forward'])} · "
                  f"重建 {len(r['rebuilt'])} · 作废 {len(r['aborted'])} · 不符 {len(r['mismatch'])}")
        return r
    except Exception as e:                       # noqa: BLE001
        print(f"[recover] 恢复阶段失败: {e} —— fail-closed,本轮判 INCOMPLETE,引擎不得启动")
        return False


RUNS_DIR = os.path.join(HERE, "runs")
RUN_STATE = os.path.join(HERE, "run_state.json")
NIGHTLY_LOCK = os.path.join(HERE, "nightly.lock")
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
    for rel in _declared_artifacts():
        src = os.path.join(HERE, rel)
        if os.path.exists(src):
            dst = os.path.join(bdir, rel.replace(os.sep, "__"))
            shutil.copy2(src, dst)
    return bdir


def _rollback_from(run_id):
    """把派生产物恢复到某轮开跑前的状态(B6:不留半新半旧的混合态)。"""
    import shutil
    bdir = os.path.join(RUNS_DIR, run_id, "before")
    if not os.path.isdir(bdir):
        return 0
    n = 0
    for rel in _declared_artifacts():
        src = os.path.join(bdir, rel.replace(os.sep, "__"))
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(HERE, rel)); n += 1
    return n


def _crash_check_and_rollback():
    """上一轮留下 run_state 标记 = 中途崩溃:派生产物是混合态,先回滚再开新轮。"""
    if not os.path.exists(RUN_STATE):
        return None
    try:
        prev = json.load(open(RUN_STATE, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        prev = {"run_id": "UNKNOWN"}
    n = _rollback_from(prev.get("run_id", ""))
    os.remove(RUN_STATE)
    print(f"[crash-recovery] 上一轮 {prev.get('run_id')} 中途崩溃,已回滚 {n} 个派生产物"
          f"(事务态不回滚,由 WAL recover 保证)")
    return {"rolled_back_run": prev.get("run_id"), "restored": n}


def _write_manifest(run_id, res):
    import hashlib
    man = {"run_id": run_id, "report": res["report"],
           "target_trade_date": res.get("target_trade_date"),
           "artifacts": {}}
    for rel in _declared_artifacts():
        pth = os.path.join(HERE, rel)
        if os.path.exists(pth):
            man["artifacts"][rel] = hashlib.sha256(open(pth, "rb").read()).hexdigest()
    mdir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(mdir, exist_ok=True)
    tmp = os.path.join(mdir, "manifest.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(mdir, "manifest.json"))


def _prune_runs(keep=14):
    try:
        runs = sorted(os.listdir(RUNS_DIR))
        for r in runs[:-keep]:
            import shutil
            shutil.rmtree(os.path.join(RUNS_DIR, r), ignore_errors=True)
    except FileNotFoundError:
        pass


def _atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--preflight" in sys.argv or "--preflight-only" in sys.argv:
        # --preflight 是**只读**检查:不做恢复、不写任何文件 ——
        # 上一版在这里跑 recover(会写 WAL)却自称"零写入",CI 也把它当只读。
        pf = preflight()
        _print_preflight(pf)
        sys.exit(0 if pf["pass"] else 1)

    # ── B6:全局锁(整轮唯一)──
    import fcntl
    lockf = open(NIGHTLY_LOCK, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("REFUSED: 另一轮夜链正在运行(nightly.lock 被持有)—— 不并发跑两轮")
        sys.exit(1)

    run_id = time.strftime("%Y%m%d_%H%M%S")
    crash_info = _crash_check_and_rollback()
    _snapshot_before(run_id)
    _atomic_write(RUN_STATE, {"run_id": run_id, "started_at": time.strftime("%Y%m%d %H:%M:%S")})

    try:
        # ── 恢复阶段(写路径,只在正式运行做)→ P0-B 硬闸 ──
        recover_ok = _recover_phase()
        pf = preflight()
        _print_preflight(pf)
        if recover_ok is False or not pf["pass"]:
            res = {"generated_at": time.strftime("%Y%m%d %H:%M"),
                   "orchestrator": "nightly_v3", "run_id": run_id,
                   "report": "INCOMPLETE",
                   "crash_recovery": crash_info,
                   "preflight": {"pass": bool(pf["pass"]), "failures": pf["failures"],
                                 "warns": pf["warns"],
                                 "recover_failed": recover_ok is False},
                   "non_ok_steps": [{"step": "preflight", "status": "FAILED"}],
                   "steps": [],
                   "note": "preflight/恢复 FAIL ⇒ 硬闸:未启动任何引擎。不是买卖指令;研究信号,human executes."}
            _atomic_write(OUT, res)
            print(f"[report] INCOMPLETE(硬闸,引擎未启动) [written] {OUT}")
            print("不是买卖指令;研究信号,human executes.")
            _alarm(res)
            sys.exit(1)

        require_live = "--allow-data-blocked" not in sys.argv
        res = run_steps(require_live=require_live, verify=True, run_id=run_id)
        res["preflight"] = {"pass": True, "warns": pf["warns"]}
        res["crash_recovery"] = crash_info
        _write_manifest(run_id, res)
        _atomic_write(OUT, res)
        for s in res["steps"]:
            print(f"{s['step']}: {s['status']}")
        print(f"[report] {res['report']}  run_id={run_id}  target={res.get('target_trade_date')}  [written] {OUT}")
        print("不是买卖指令;研究信号,human executes.")
        _alarm(res)
        _prune_runs()
        if any(s["status"] == "FAILED" for s in res["steps"]):
            sys.exit(1)
        if res["report"] != "COMPLETE":
            sys.exit(2)
    finally:
        # 正常走到这里(含 sys.exit)= 本轮有终态报告,清除崩溃标记;
        # 真崩溃(进程被杀/异常穿透)标记留存,下一轮回滚。
        if os.path.exists(RUN_STATE):
            try:
                cur = json.load(open(RUN_STATE, encoding="utf-8"))
                if cur.get("run_id") == run_id:
                    os.remove(RUN_STATE)
            except (json.JSONDecodeError, OSError):
                pass
        fcntl.flock(lockf, fcntl.LOCK_UN)


if __name__ == "__main__":
    main()
