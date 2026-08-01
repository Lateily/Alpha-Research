#!/usr/bin/env python3
"""跨层事实一致性检查 — 防"只改外层字段"的半程迁移。

事故来源(2026-08-01):single_beta 这一个事实散在四层(sample 顶层
sector_single_beta / portfolio_gate.single_beta_exposure / self_audit.
high_reflexivity_book / 每条信号的 sector_single_beta),迁移只改了一层,
文件内部自相矛盾却无人发现;报告的 claim_allowed 同样内外层不一致。

规则:同一事实在任何层出现,值必须一致;不一致 ⇒ INCONSISTENT(阻断)。
本模块纯函数、零网络,供 preflight 与离线测试共用。
不是买卖指令;研究信号,human executes.
"""


def _present(d, path):
    """按点路径取值,返回 (found, value)。"""
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return False, None
        cur = cur[k]
    return True, cur


def check_sample_single_beta(sample, signals=None):
    """single_beta 事实的四层一致性。signals 只看与该 sample 同交易日的条目。"""
    issues, seen = [], {}
    for path in ("sector_single_beta",
                 "portfolio_gate.single_beta_exposure",
                 "self_audit.high_reflexivity_book"):
        found, val = _present(sample, path)
        if found:
            seen[path] = val
    # 信号层
    td = str(sample.get("timestamp", ""))[:8]
    sig_vals = set()
    for s in (signals or []):
        if str(s.get("timestamp", ""))[:8] == td and s.get("sector_single_beta") is not None:
            sig_vals.add(bool(s["sector_single_beta"]))
    if sig_vals:
        seen["signals[].sector_single_beta"] = (sig_vals.pop() if len(sig_vals) == 1
                                                else f"MIXED{sorted(sig_vals)}")
    vals = {k: v for k, v in seen.items() if v is not None}
    distinct = {str(v) for v in vals.values()}
    if len(distinct) > 1:
        issues.append({"fact": "single_beta", "layers": vals,
                       "why": "同一事实跨层取值不一致 —— 典型的只改外层半程迁移"})
    return issues


def check_report_claim(report):
    """claim_allowed 的内外层一致性。"""
    issues = []
    outer_found, outer = _present(report, "claim_allowed")
    inner_found, inner = _present(report, "winrate_scorecard.claim_allowed")
    if outer_found and inner_found and bool(outer) != bool(inner):
        issues.append({"fact": "claim_allowed",
                       "layers": {"claim_allowed": outer,
                                  "winrate_scorecard.claim_allowed": inner},
                       "why": "顶层与 scorecard 内层不一致 —— 只加外层新键的半程迁移"})
    # claim 禁止时,警示文案不得声称门槛已满足
    if inner_found and inner is False:
        warn = str(report.get("unvalidated_warning") or "")
        if "threshold met" in warn or "门槛已满足" in warn:
            issues.append({"fact": "unvalidated_warning",
                           "layers": {"claim_allowed": inner, "unvalidated_warning": warn[:80]},
                           "why": "claim 禁止但文案仍称样本门槛已满足"})
    return issues


def check_migration_provenance(obj):
    """迁移记录必须留真值:original_value 全 null 视为未记录。"""
    issues = []
    migs = []
    if isinstance(obj, dict):
        if isinstance(obj.get("_migration"), dict):
            migs.append(obj["_migration"])
        if isinstance(obj.get("_migrations"), list):
            migs.extend(m for m in obj["_migrations"] if isinstance(m, dict))
    for m in migs:
        fields = m.get("fields")
        if isinstance(fields, dict) and fields:
            if all((f or {}).get("original_value") is None for f in fields.values()):
                issues.append({"fact": "migration_provenance", "layers": {"fields": list(fields)},
                               "why": "迁移记录的 original_value 全为 null —— 原值未被真正保存"})
        elif "original_value" in m and m["original_value"] in (None, {}, []):
            issues.append({"fact": "migration_provenance", "layers": {"original_value": m.get("original_value")},
                           "why": "迁移记录未保存真实原值"})
    return issues


def check_all(sample=None, signals=None, report=None):
    out = []
    if sample is not None:
        out += check_sample_single_beta(sample, signals)
        out += check_migration_provenance(sample)
        for k in ("portfolio_gate", "self_audit"):
            if isinstance(sample.get(k), dict):
                out += check_migration_provenance(sample[k])
    if report is not None:
        out += check_report_claim(report)
        out += check_migration_provenance(report)
        if isinstance(report.get("winrate_scorecard"), dict):
            out += check_migration_provenance(report["winrate_scorecard"])
    return out


def scan_dirs(here, sample_dir="samples", report_dir="reports",
              signal_log="paper_signal_log.json", recent=5):
    """扫描近 N 份样本与报告的跨层一致性 → issue 字符串列表。

    fail-closed 契约(2026-08-01 审计:本函数前身用 except: continue 静默跳过
    损坏文件,导致把最新报告改成 BROKEN_JSON 后 preflight 仍 PASS):
      - 目录缺失 ⇒ issue(不是"没有就算过")
      - 目录存在但无可检查文件 ⇒ issue
      - 任一文件解析失败 ⇒ issue(损坏≠无问题)
      - 信号账本解析失败 ⇒ issue(不能当成空账本继续)
    """
    import json as _json
    import os as _os

    issues = []
    log_path = _os.path.join(here, signal_log)
    sigs = []
    if not _os.path.exists(log_path):
        issues.append(f"{signal_log}: 缺失 —— 无法做信号层一致性核对")
    else:
        try:
            _log = _json.load(open(log_path, encoding="utf-8"))
            sigs = _log if isinstance(_log, list) else _log.get("signals", [])
        except Exception as e:
            issues.append(f"{signal_log}: 解析失败({type(e).__name__})—— 损坏≠空账本")

    for sub, kw in ((sample_dir, "sample"), (report_dir, "report")):
        d = _os.path.join(here, sub)
        if not _os.path.isdir(d):
            issues.append(f"{sub}/: 目录缺失 —— 一致性无从核对(缺数据≠通过)")
            continue
        files = sorted(x for x in _os.listdir(d) if x.endswith(".json"))
        if not files:
            issues.append(f"{sub}/: 无可检查的 .json —— 一致性无从核对")
            continue
        for f in files[-recent:]:
            fp = _os.path.join(d, f)
            try:
                obj = _json.load(open(fp, encoding="utf-8"))
            except Exception as e:
                issues.append(f"{sub}/{f}: 解析失败({type(e).__name__})—— 损坏文件不得放行")
                continue
            if not isinstance(obj, dict):
                issues.append(f"{sub}/{f}: 顶层不是对象({type(obj).__name__})")
                continue
            args = {kw: obj}
            if kw == "sample":
                args["signals"] = sigs
            for iss in check_all(**args):
                issues.append(f"{sub}/{f}: {iss['fact']} — {iss['why']}")
    return issues
