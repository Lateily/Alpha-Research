#!/usr/bin/env python3
"""Offline unit tests for scripts/data_source_health.py — zero network.

Covers (PR-A A1 regression anchors):
  - error-text classification: 权限/没有接口 → DATA_BLOCKED,接口名 → PARAM_ERROR,
    network → SOURCE_DOWN(不许把权限错误伪装成网络错误)
  - result classification: 0 rows → EMPTY_VALID(不是 OK);老数据 → STALE
  - exit semantics: required 五件任一非 OK → exit 1;可选 DATA_BLOCKED → PARTIAL + exit 0
  - --offline: 全部 NOT_RUN,exit 0,不发任何请求

Run: AR_OFFLINE=1 python3 tests/test_data_source_health_offline.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import data_source_health as dsh  # noqa: E402


def _row(endpoint, required, status):
    return {
        "endpoint": endpoint, "required": required, "permission": None,
        "status": status, "rows": 0, "as_of": None, "freshness_days": None,
        "latency_ms": 1, "error": None, "checked_at": "t",
    }


def test_classify_error_permission():
    real_msg = "Exception: 抱歉，您没有接口(news)访问权限，权限的具体详情访问：https://tushare.pro/document/1?doc_id=108。"
    assert dsh.classify_error(real_msg) == "DATA_BLOCKED", real_msg
    assert dsh.classify_error("没有访问该接口的权限") == "DATA_BLOCKED"
    print("PASS classify: 权限错误 → DATA_BLOCKED")


def test_classify_error_param():
    # verified live 2026-07-31: nonexistent api name → "请指定正确的接口名"
    assert dsh.classify_error("Exception: 请指定正确的接口名") == "PARAM_ERROR"
    print("PASS classify: 接口名错误 → PARAM_ERROR(不是权限不足)")


def test_classify_error_network():
    assert dsh.classify_error("ConnectionError: HTTPSConnectionPool timed out") == "SOURCE_DOWN"
    print("PASS classify: 网络异常 → SOURCE_DOWN")


def test_classify_result_empty_is_not_ok():
    status, as_of, fresh = dsh.classify_result("daily", [], None)
    assert status == "EMPTY_VALID" and as_of is None, (status, as_of)
    print("PASS classify: 0行 → EMPTY_VALID(0行不许标OK)")


def test_classify_result_ok_with_as_of():
    today = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")
    status, as_of, fresh = dsh.classify_result("daily", [{"trade_date": today}], None)
    assert status == "OK" and as_of == today and fresh == 0, (status, as_of, fresh)
    print("PASS classify: 有行 → OK + 真实 as_of/freshness")


def test_classify_result_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y%m%d")
    status, as_of, fresh = dsh.classify_result("daily", [{"trade_date": old}], None)
    assert status == "STALE" and fresh >= 40, (status, fresh)
    print("PASS classify: 45天旧 daily → STALE")


def test_required_failure_exits_1():
    rows = [_row(e, True, "OK") for e in dsh.REQUIRED_ENDPOINTS[:-1]]
    rows.append(_row(dsh.REQUIRED_ENDPOINTS[-1], True, "SOURCE_DOWN"))
    payload, exit_code = dsh.build_report(rows)
    assert exit_code == 1 and payload["report"] == "FAIL", (exit_code, payload["report"])
    assert payload["required_failures"] == [dsh.REQUIRED_ENDPOINTS[-1]]
    print("PASS gate: 关键五件任一失败 → FAIL + exit 1")


def test_required_empty_is_failure():
    rows = [_row(e, True, "OK") for e in dsh.REQUIRED_ENDPOINTS[:-1]]
    rows.append(_row(dsh.REQUIRED_ENDPOINTS[-1], True, "EMPTY_VALID"))
    payload, exit_code = dsh.build_report(rows)
    assert exit_code == 1 and payload["report"] == "FAIL"
    print("PASS gate: 关键接口空数据 ≠ 通过 → FAIL + exit 1")


def test_optional_blocked_is_partial_exit_0():
    rows = [_row(e, True, "OK") for e in dsh.REQUIRED_ENDPOINTS]
    rows.append(_row("news", False, "DATA_BLOCKED"))
    payload, exit_code = dsh.build_report(rows)
    assert exit_code == 0 and payload["report"] == "PARTIAL", (exit_code, payload["report"])
    print("PASS gate: 可选接口 DATA_BLOCKED → PARTIAL(不许全绿)+ exit 0")


def test_all_ok_is_green():
    rows = [_row(e, True, "OK") for e in dsh.REQUIRED_ENDPOINTS]
    rows.append(_row("forecast", False, "OK"))
    payload, exit_code = dsh.build_report(rows)
    assert exit_code == 0 and payload["report"] == "OK"
    print("PASS gate: 全 OK → OK + exit 0")


def test_offline_mode_writes_not_run_and_exits_0():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "health.json")
        code = dsh.main(["--offline", "--output", out])
        assert code == 0, code
        with open(out, encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["report"] == "NOT_RUN"
        assert payload["probes"], "probe list must not be empty in offline mode"
        assert all(p["status"] == "NOT_RUN" for p in payload["probes"])
        assert "human executes" in payload["disclaimer"]
    print("PASS offline: --offline → 全 NOT_RUN + exit 0 + 免责句")


def test_probe_specs_cover_required_and_blocked():
    endpoints = [e for e, _, _ in dsh._probe_specs()]
    for req in dsh.REQUIRED_ENDPOINTS:
        assert req in endpoints, f"required probe missing: {req}"
    for blocked in ("news", "anns_d", "cctv_news", "rt_min_daily"):
        assert blocked in endpoints, f"known-blocked probe missing: {blocked}"
    print("PASS specs: 关键五件 + 已知无权限四件均在探针清单")


if __name__ == "__main__":
    test_classify_error_permission()
    test_classify_error_param()
    test_classify_error_network()
    test_classify_result_empty_is_not_ok()
    test_classify_result_ok_with_as_of()
    test_classify_result_stale()
    test_required_failure_exits_1()
    test_required_empty_is_failure()
    test_optional_blocked_is_partial_exit_0()
    test_all_ok_is_green()
    test_offline_mode_writes_not_run_and_exits_0()
    test_probe_specs_cover_required_and_blocked()
    print("ALL data_source_health OFFLINE TESTS PASS (0 network calls)")
