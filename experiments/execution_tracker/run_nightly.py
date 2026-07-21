#!/usr/bin/env python3
"""
run_nightly.py — post-close orchestration for execution_tracker.

Runs the new discovery/execution engines in dependency order after official
settle data is available. The orchestrator makes the engine chain memorable and
auditable; it does not create, fill, or modify fund orders.

Default order:
  rotation_panel -> momentum_prefilter -> rotation_stats -> rotation_validation ->
  lead_precursor -> overnight_anchor -> court_wakeup -> watch_dynamic ->
  position_review -> setup_promoter

不是买卖指令；研究信号，human executes。
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nightly_run.json")

STEPS = [
    ("rotation_panel", ["python3", "rotation_panel.py"], True),
    ("momentum_prefilter", ["python3", "momentum_prefilter.py"], True),
    ("rotation_stats", ["python3", "rotation_stats.py"], False),
    ("rotation_validation", ["python3", "rotation_validation.py", "--append"], True),
    ("lead_precursor", ["python3", "lead_precursor.py"], False),
    ("overnight_anchor_frame", ["python3", "overnight_anchor.py"], False),
    ("court_wakeup", ["python3", "court_wakeup.py"], True),
    ("watch_dynamic", ["python3", "watch_dynamic.py"], False),
    ("position_review", ["python3", "position_review.py"], True),
    ("setup_promoter", ["python3", "setup_promoter.py"], True),
]


def run_steps(runner=None, require_live=True):
    runner = runner or _subprocess_runner
    results = []
    for name, cmd, needs_token in STEPS:
        if needs_token and require_live and not os.environ.get("TUSHARE_TOKEN", "").strip():
            results.append({"step": name, "status": "DATA_BLOCKED", "why": "NO TUSHARE_TOKEN"})
            continue
        t0 = time.time()
        code, out = runner(cmd)
        results.append({"step": name,
                        "status": "OK" if code == 0 else "FAILED",
                        "exit_code": code,
                        "elapsed_sec": round(time.time() - t0, 2),
                        "tail": out[-1200:]})
    return {"generated_at": time.strftime("%Y%m%d %H:%M"),
            "steps": results,
            "note": "nightly orchestrator; review/paper outputs only. 不是买卖指令。"}


def _subprocess_runner(cmd):
    p = subprocess.run(cmd, cwd=HERE, text=True, capture_output=True, timeout=180)
    return p.returncode, (p.stdout + p.stderr)


def selftest():
    calls = []

    def fake(cmd):
        calls.append(cmd[1])
        return 0, "ok"

    res = run_steps(fake, require_live=False)
    order_ok = calls == [cmd[1] for _, cmd, _ in STEPS]
    statuses_ok = all(s["status"] == "OK" for s in res["steps"])
    note_ok = "不是买卖指令" in res["note"]
    checks = [("dependency order", order_ok), ("all fake steps OK", statuses_ok),
              ("disclaimer in note", note_ok)]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print(f"run_nightly selftest: {sum(ok for _, ok in checks)}/{len(checks)}")
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
    print(f"[written] {OUT}")
    print("不是买卖指令；研究信号，human executes.")
    if any(s["status"] == "FAILED" for s in res["steps"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
