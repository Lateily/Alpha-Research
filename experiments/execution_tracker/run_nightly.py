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
    # ── 前端契约导出(引擎写、前端读的唯一通道)──
    # 设计决定(审查F4/F5):export 无前置依赖、永远运行 —— 跳过导出只会让磁盘上
    # 留着更旧的契约;诚实性由 export 内部的逐源新鲜度/内部状态戳保证。
    ("export_contracts", ["python3", "export_contracts.py"], False, []),
]

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


def run_steps(runner=None, require_live=True):
    runner = runner or _subprocess_runner
    results, status_by = [], {}

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
        status_by[name] = status
        results.append({"step": name, "status": status, "exit_code": code,
                        "elapsed_sec": round(time.time() - t0, 2), "tail": out[-1200:]})

    non_ok = [r for r in results if r["status"] != "OK"]
    report = "COMPLETE" if not non_ok else "INCOMPLETE"
    return {"generated_at": time.strftime("%Y%m%d %H:%M"),
            "orchestrator": "nightly_v2",
            "report": report,
            "non_ok_steps": [{"step": r["step"], "status": r["status"]} for r in non_ok],
            "steps": results,
            "note": "nightly v2;review/paper 产出;上游失败下游必跳。不是买卖指令。"}


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
    # 6) 关键契约 freshness:缺文件 FAIL;mtime 超 36h 仅 WARN 列出,不阻断
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


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--preflight" in sys.argv or "--preflight-only" in sys.argv:
        pf = preflight()
        _print_preflight(pf)
        sys.exit(0 if pf["pass"] else 1)
    # ── P0-B 硬闸:正式运行路径 preflight 自动前置,FAIL ⇒ 任何引擎不得启动 ──
    pf = preflight()
    _print_preflight(pf)
    if not pf["pass"]:
        res = {"generated_at": time.strftime("%Y%m%d %H:%M"),
               "orchestrator": "nightly_v2",
               "report": "INCOMPLETE",
               "preflight": {"pass": False, "failures": pf["failures"],
                             "warns": pf["warns"]},
               "non_ok_steps": [{"step": "preflight", "status": "FAILED"}],
               "steps": [],
               "note": "preflight FAIL ⇒ 硬闸:未启动任何引擎。不是买卖指令;研究信号,human executes."}
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print(f"[report] INCOMPLETE(preflight FAIL,引擎未启动) [written] {OUT}")
        print("不是买卖指令;研究信号,human executes.")
        _alarm(res)
        sys.exit(1)
    require_live = "--allow-data-blocked" not in sys.argv
    res = run_steps(require_live=require_live)
    res["preflight"] = {"pass": True, "warns": pf["warns"]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    for s in res["steps"]:
        print(f"{s['step']}: {s['status']}")
    print(f"[report] {res['report']}  [written] {OUT}")
    print("不是买卖指令;研究信号,human executes.")
    _alarm(res)
    if any(s["status"] == "FAILED" for s in res["steps"]):
        sys.exit(1)
    if res["report"] != "COMPLETE":
        sys.exit(2)


if __name__ == "__main__":
    main()
