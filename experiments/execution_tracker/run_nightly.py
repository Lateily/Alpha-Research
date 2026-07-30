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
    ("fwd_backfill", ["python3", "run_post_close_report.py"], True, ["official_sample"]),
    # ── 轮动/发现链 ──
    ("rotation_panel", ["python3", "rotation_panel.py"], True, []),
    ("momentum_prefilter", ["python3", "momentum_prefilter.py"], True, []),
    ("rotation_stats", ["python3", "rotation_stats.py"], False, ["rotation_panel"]),
    ("rotation_validation", ["python3", "rotation_validation.py", "--append"], True,
     ["rotation_stats"]),
    ("lead_precursor", ["python3", "lead_precursor.py"], False, ["rotation_validation"]),
    ("overnight_anchor_frame", ["python3", "overnight_anchor.py"], False, []),
    # ── 名单与持仓 ──
    ("court_wakeup", ["python3", "court_wakeup.py"], True, []),
    ("watch_dynamic", ["python3", "watch_dynamic.py"], False, ["court_wakeup"]),
    ("position_review", ["python3", "position_review.py"], True, ["official_sample"]),
    ("setup_promoter", ["python3", "setup_promoter.py"], True, ["watch_dynamic"]),
    # ── 强制质检层(2026-07-27/28 事故驱动)──
    ("red_flag_gate", ["python3", "red_flag_gate.py", "--from-watchlist"], True,
     ["watch_dynamic"]),
    ("full_battery", ["python3", "full_battery.py", "--from-watchlist"], True,
     ["watch_dynamic"]),
    # ── 前端契约导出(引擎写、前端读的唯一通道)──
    ("export_contracts", ["python3", "export_contracts.py"], False,
     ["official_sample", "position_review", "red_flag_gate"]),
]

_BLOCK_MARKERS = ("DATA_BLOCKED", "DATA-BLOCKED")


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
        if code == 0 and any(m in out for m in _BLOCK_MARKERS):
            status = "DATA_BLOCKED"  # 引擎自报 blocked 但退出 0 —— 不算成功
        else:
            status = "OK" if code == 0 else "FAILED"
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
    p = subprocess.run(cmd, cwd=HERE, text=True, capture_output=True, timeout=600)
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

    # 2) 根失败传染:official_sample FAILED ⇒ 回填/仓位复审/导出必跳,轮动链不受影响
    def fail_root(cmd):
        return (1, "boom") if cmd[1] == "run_official_sample.py" else (0, "ok")
    res2 = run_steps(fail_root, require_live=False)
    st = {r["step"]: r["status"] for r in res2["steps"]}
    checks.append(("根失败 ⇒ FAILED", st["official_sample"] == "FAILED"))
    checks.append(("回填被跳", st["fwd_backfill"] == "SKIPPED_STALE_INPUT"))
    checks.append(("仓位复审被跳", st["position_review"] == "SKIPPED_STALE_INPUT"))
    checks.append(("契约导出被跳", st["export_contracts"] == "SKIPPED_STALE_INPUT"))
    checks.append(("轮动链不受影响", st["rotation_panel"] == "OK"))
    checks.append(("终态 INCOMPLETE", res2["report"] == "INCOMPLETE"))

    # 3) 引擎自报 DATA_BLOCKED 且退出 0 ⇒ 不算成功(v1 的第94行病)
    def blocked_quiet(cmd):
        return (0, "xx DATA_BLOCKED yy") if cmd[1] == "watch_dynamic.py" else (0, "ok")
    res3 = run_steps(blocked_quiet, require_live=False)
    st3 = {r["step"]: r["status"] for r in res3["steps"]}
    checks.append(("退出0+自报blocked ⇒ DATA_BLOCKED", st3["watch_dynamic"] == "DATA_BLOCKED"))
    checks.append(("其下游(闸门/电池/晋级)被跳", st3["red_flag_gate"] == "SKIPPED_STALE_INPUT"
                   and st3["full_battery"] == "SKIPPED_STALE_INPUT"
                   and st3["setup_promoter"] == "SKIPPED_STALE_INPUT"))
    checks.append(("免责句在", "不是买卖指令" in res3["note"]))

    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"run_nightly v2 selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
    return all(ok for _, ok in checks)


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
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
