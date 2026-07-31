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

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nightly_run.json")
ALARM_FLAG = "/tmp/ar-nightly-incomplete"

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

    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"run_nightly v2 selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def preflight():
    """首跑前体检:真实读取账本与引擎文件,校验 schema 与依赖,不联网不写盘。"""
    checks = []
    # 1) 信号账本可解析 + 每条 returns 为 dict/缺失 + 时间戳可解析
    try:
        log = json.load(open(os.path.join(HERE, "paper_signal_log.json")))
        sigs = log if isinstance(log, list) else log.get("signals", [])
        checks.append((f"信号账本可解析(n={len(sigs)})", True))
        bad_ret = [x.get("signal_id") for x in sigs
                   if "returns" in x and x["returns"] is not None and not isinstance(x["returns"], dict)]
        checks.append(("returns 类型合法(dict/null)", bad_ret == []))
        if bad_ret: print(f"  ✗ 异型 returns: {bad_ret[:5]}")
        import re as _re
        bad_tk = [x.get("signal_id") for x in sigs
                  if not _re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(x.get("ticker",""))) 
                  and not str(x.get("scoring") or "") == "NOT_SCORABLE"]
        checks.append(("非标资产均已声明 NOT_SCORABLE", bad_tk == []))
        if bad_tk: print(f"  ✗ 非标 ticker 未声明: {bad_tk[:5]}")
        bad_ts = [x.get("signal_id") for x in sigs
                  if not _re.match(r"20\d{6}", str(x.get("timestamp","")))]
        checks.append(("时间戳可解析", bad_ts == []))
        if bad_ts: print(f"  ✗ 坏时间戳: {bad_ts[:5]}")
    except Exception as e:
        checks.append((f"信号账本解析: {e}", False))
    # 2) 基金账本三件可解析
    for f in ("model_fund/fund.json", "model_fund/nav_history.json", "model_fund/orders.json"):
        try:
            json.load(open(os.path.join(HERE, f))); checks.append((f"{f} 可解析", True))
        except Exception as e:
            checks.append((f"{f}: {e}", False))
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
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + str(name))
    good = all(ok for _, ok in checks)
    print(f"preflight: {'PASS' if good else 'FAIL'}(零网络零写入)")
    return good


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if "--preflight" in sys.argv:
        sys.exit(0 if preflight() else 1)
    require_live = "--allow-data-blocked" not in sys.argv
    res = run_steps(require_live=require_live)
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
