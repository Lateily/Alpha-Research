#!/usr/bin/env python3
"""Read-only migration inventory (第一步·全量盘点).

Walks every root the operator names — the production checkout, the engineering
checkout, sandbox / evidence directories, backups, worktrees — and registers
each file with its source root, git class (TRACKED / UNTRACKED / IGNORED /
FILESYSTEM), size, mtime, sha256, category, purpose, version hint and proposed
destination on the new platform. Nested git checkouts are detected and their
tracked trees are summarised (recoverable from Git history) while every
untracked / ignored file — the run data that is NOT in Git — is listed one by
one. SQLite stores get a read-only table/row-count summary. Secrets are never
read or hashed: they are registered as SECRET_NOT_MIGRATED so the record shows
they exist and must be configured, not copied.

The tool writes nothing inside any root. Outputs go to --out:
  inventory.jsonl          one record per file / tree summary
  INVENTORY_SUMMARY.md     counts and bytes per root × category, gaps, secrets
  run_receipt.json         roots, HEADs, generated_at, tool sha256, inventory sha256

Nothing here migrates, uploads, deletes or rewrites anything. Missing referenced
artifacts are recorded as gaps, never fabricated. 不是买卖指令;研究信号,human executes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ar.migration_inventory.v1"
DISCLAIMER = "盘点清单,不是迁移本身;缺件只登记不补造。不是买卖指令;研究信号,human executes."

DEFAULT_EXCLUDES = ("node_modules", ".git", "__pycache__", ".DS_Store", ".pytest_cache", ".venv", "dist")
SECRET_PATTERNS = (
    re.compile(r"(^|/)\.ar_env$"), re.compile(r"(^|/)\.env($|\.)"), re.compile(r"token", re.I),
    re.compile(r"(^|/)[^/]*secret[^/]*$", re.I), re.compile(r"\.(pem|key|p12)$", re.I),
    re.compile(r"(^|/)\.ar_progress_write_key"),
)
RUN_ID_RE = re.compile(r"(20\d{6}_\d{6}_\d+_[0-9a-f]{8})")
DATE8_RE = re.compile(r"(?<![0-9])(20\d{6})(?![0-9])")

# Ordered classification rules: (regex on posix relpath, category, purpose, destination).
# The first match wins. Anything unmatched is UNCLASSIFIED and must be triaged by a human.
RULES: tuple[tuple[str, str, str, str], ...] = (
    (r"(^|/)data_history/(feature_store|macro_os)\.sqlite3$", "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
     "行情/宏观点对点历史仓(SQLite,追加式,input_hash 绑定)", "数据中心 · 历史查询 · 研究回放"),
    (r"(^|/)knowledge_card_history/", "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
     "知识卡历史采集原始文件与专用 PIT store", "数据中心 · 研究回放"),
    (r"(^|/)knowledge_cards/backtest_", "RESEARCH_ARCHIVE", "知识卡三周期点回看结果", "个股研究档案 · 方法中心"),
    (r"(^|/)data_history/panel/|\.parquet$|(^|/)data_history/sector_mapping\.json$", "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
     "旧平台市场面板(parquet)与板块映射", "数据中心 · 历史查询"),
    (r"\.(lock|sqlite3-shm|sqlite3-wal)$|(^|/)\.[a-z0-9_]+\.lock$", "TRANSIENT_NOT_MIGRATED",
     "运行时锁/WAL 临时文件", "不迁移(新环境自生)"),
    (r"(^|/)execution_tracker/(publication_migration_events|publication_rebaseline_events)", "OPS_RUNS_PUBLICATION_AUDIT",
     "发布迁移/重基线审批事件(append-only,anchor)", "运行监控 · 审计 · 事故记录"),
    (r"(^|/)execution_tracker/samples/", "PAPER_PORTFOLIO_LEDGER", "逐日信号样本(含'不具备统计声称资格'标记)", "接续原模拟盘 · 样本资格标记保留"),
    (r"(^|/)execution_tracker/reports/", "OPS_RUNS_PUBLICATION_AUDIT", "夜链逐日报告", "运行监控 · 审计"),
    (r"(^|/)(rotation_history|watchtower_log|nowcast_log)", "OPS_RUNS_PUBLICATION_AUDIT", "轮动/看守/即时预测日志", "运行监控 · 审计"),
    (r"(^|/)(\.shifts|\.agent_tasks|\.audit|\.ai-workspace|runtime/cloud-migration|local-ai|archive/workspace-manifests|archive/artifacts)/",
     "AGENT_OPS_RECORDS", "代理作业/审计/工作区记录", "运行监控 · 审计(代理记录)"),
    (r"(^|/)AR-Workbench/(state|releases|acceptance)/|(^|/)workbench\.sqlite3$|(^|/)research-runs/|(^|/)release-manifest\.json$",
     "NEW_PLATFORM_STATE", "新工作台自身状态/发布/验收(不是旧系统历史)", "新平台隔离区(不作为迁移来源)"),
    (r"(^|/)PR_REVIEW_LOG\.tsv$|(^|/)(deleted-paths|excluded-code-snapshots|head-before|status-before|restore-files)\.txt$|(^|/)(receipt|restore-receipt|inventory)\.json$|(^|/)runtime-data\.tar\.gz$",
     "OPS_RUNS_PUBLICATION_AUDIT", "同步/复审记录与归档", "运行监控 · 审计"),
    (r"(^|/)public/data/(tushare|lhb|margin|top_inst|chip_distribution|quant_factors|holdertrade|pledge_stat|repurchase|restricted_shares|inst_research|consensus_forecast|broker_recommend|issuer_guidance|macro)/",
     "MARKET_FINANCIAL_FLOW_MACRO_HISTORY", "付费源逐票快照(watchlist 级)", "数据中心 · 来源快照"),
    (r"(^|/)data_history/funnel/", "SCREENING_COHORT_BATTERY_PACKETS",
     "全市场漏斗 bundle:U0-U4 packet、电池、manifest(不可变)", "候选生成与入选/拒绝追溯"),
    (r"(^|/)public/data/v2/(funnel_|security_registry|feature_store_health|funnel_health|battery|candidate|e1_event_layer|rotation_panel|red_flags|premarket_frame|macro_gate|position_review|trade_cards|model_portfolio_state)",
     "SCREENING_COHORT_BATTERY_PACKETS", "夜链发布的筛选/电池/注册表产物", "候选生成追溯 · 数据中心"),
    (r"(^|/)data_history/research_advisory/u4_decision_ledger", "DECISION_RECORDS",
     "U4 决策账本(SELECT/REJECT/DEFER/NO_TRADE/DATA_BLOCKED 全记录)", "完整决策历史(不得只留成功样本)"),
    (r"(^|/)data_history/research_advisory/", "DECISION_RECORDS", "研究顾问层日切产物", "决策历史"),
    (r"(^|/)execution_tracker/event_ledger\.jsonl", "DECISION_RECORDS",
     "事件账本(append-only,anchor 锁链)", "决策历史 · 审计追溯"),
    (r"(^|/)(public/data|docs/research)/decision_sheets/", "DECISION_RECORDS", "单票决策书", "个股研究档案"),
    (r"(^|/)execution_tracker/model_fund/", "PAPER_PORTFOLIO_LEDGER",
     "模拟盘:订单/成交/持仓/现金/NAV/费用", "接续原模拟盘,不重新开账"),
    (r"(^|/)(paper_signal_log|paper_trades|paper_execution|nav_history|five_axis|attribution)", "PAPER_PORTFOLIO_LEDGER",
     "模拟盘信号/成交/五轴归因记录", "接续原模拟盘 · 归因"),
    (r"(^|/)public/data/(core_validation_ledger|ai_forward_beta_checkpoint_ledger)", "PAPER_PORTFOLIO_LEDGER",
     "验证/检查点账本", "接续原模拟盘 · 归因"),
    (r"(^|/)docs/research/(factpacks|screens|review|tribunal|case_studies|serenity|factcheck|prospective|sectors|macro)/",
     "RESEARCH_ARCHIVE", "Thesis/事实包/复审/封存材料/研究报告", "个股研究档案 · 版本对比"),
    (r"(^|/)(authoring|closure|closure_bundle|sealed|evidence_)", "RESEARCH_ARCHIVE",
     "走查/封存材料", "个股研究档案 · 版本对比"),
    (r"(^|/)public/data/(thesis_outcomes|thesis_factcheck)/", "RESEARCH_ARCHIVE", "命题结果与事实核查产物", "个股研究档案"),
    (r"(^|/)data/knowledge_cards/", "METHOD_AND_CODE_VERSIONS", "知识卡(REVIEWED 状态与阈值锚)", "模型与方法中心"),
    (r"(^|/)docs/research/contracts/", "METHOD_AND_CODE_VERSIONS", "冻结契约与 schema", "模型与方法中心"),
    (r"(^|/)scripts/llm/(prompts|fixtures)/", "METHOD_AND_CODE_VERSIONS", "提示词与任务 fixture", "模型与方法中心"),
    (r"(^|/)scripts/governance_mutation_gate\.py$", "METHOD_AND_CODE_VERSIONS", "治理变异门(钉表)", "模型与方法中心"),
    (r"(^|/)(tests/|\.github/workflows/)", "METHOD_AND_CODE_VERSIONS", "测试与 CI 证据", "模型与方法中心"),
    (r"(^|/)execution_tracker/runs/", "OPS_RUNS_PUBLICATION_AUDIT", "夜链 run manifest(durable)", "运行监控 · 审计"),
    (r"(^|/)execution_tracker/(current_run|nightly_run|publication_state|nightly\.lock|launchd/|nowcast_log|overnight_anchor|court_|eod_candidates|momentum_prefilter|lead_precursor|battery\.json|macro_events)",
     "OPS_RUNS_PUBLICATION_AUDIT", "夜链运行状态/发布指针/日切产物", "运行监控 · 审计"),
    (r"(^|/)public/data/v2/(current_run|meta)\.json$", "OPS_RUNS_PUBLICATION_AUDIT", "发布指针", "运行监控 · 审计"),
    (r"(^|/)(ar-sync-backups|audits|backups|runtime-backups)/", "OPS_RUNS_PUBLICATION_AUDIT",
     "同步/验收/备份归档(迁移与事故记录)", "运行监控 · 审计"),
    (r"(^|/)(input-pack|input-pack-.*\.zip|evidence-.*\.zip|twin-\d{8}/|e2e-twin/)", "WALKTHROUGH_EVIDENCE",
     "E2E 走查冻结输入包、发现与工单、B4 回看", "研究档案 · 方法中心"),
    (r"\.(py|js|jsx|mjs|ts|tsx|css|html|sh|command)$", "CODE", "源码(由 Git 历史承载)", "代码版本(Git)"),
    (r"(^|/)(README|STATUS|ROADMAP|SESSION_HANDOFF|CLAUDE|AGENTS|CONTRACT|WORKSPACE_CONTRACT)[^/]*\.md$|(^|/)docs/",
     "DOCS", "文档(由 Git 历史承载)", "文档"),
    (r"(^|/)public/data/", "SCREENING_COHORT_BATTERY_PACKETS", "其他公开数据产物", "数据中心"),
)


class InventoryError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, limit: int | None = None) -> str | None:
    size = path.stat().st_size
    if limit is not None and size > limit:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_secret(relpath: str) -> bool:
    return any(pattern.search(relpath) for pattern in SECRET_PATTERNS)


HISTORY_CATEGORIES = frozenset({
    "MARKET_FINANCIAL_FLOW_MACRO_HISTORY", "SCREENING_COHORT_BATTERY_PACKETS", "DECISION_RECORDS",
    "RESEARCH_ARCHIVE", "PAPER_PORTFOLIO_LEDGER", "METHOD_AND_CODE_VERSIONS", "OPS_RUNS_PUBLICATION_AUDIT",
    "WALKTHROUGH_EVIDENCE",
})


def classify(relpath: str, root: str = "") -> tuple[str, str, str]:
    """Classify by the root-qualified posix path; the first matching rule wins."""
    qualified = f"{root}/{relpath}" if root else relpath
    for pattern, category, purpose, destination in RULES:
        if re.search(pattern, qualified):
            return category, purpose, destination
    return "UNCLASSIFIED", "未匹配任何规则,需人工归类", "待定"


def must_migrate(category: str, git_class: str) -> str:
    """MIGRATE (history not held by Git), GIT_RECOVERABLE, or NOT_MIGRATED."""
    if category in ("SECRET", "TRANSIENT_NOT_MIGRATED", "NEW_PLATFORM_STATE"):
        return "NOT_MIGRATED"
    if git_class == "TRACKED":
        return "GIT_RECOVERABLE"
    if category in HISTORY_CATEGORIES or category in ("AGENT_OPS_RECORDS", "UNCLASSIFIED"):
        return "MIGRATE"
    return "GIT_RECOVERABLE" if category in ("CODE", "DOCS") else "MIGRATE"


def version_hint(relpath: str) -> str | None:
    run = RUN_ID_RE.search(relpath)
    if run:
        return f"run_id:{run.group(1)}"
    dates = DATE8_RE.findall(relpath)
    if dates:
        return f"as_of:{dates[-1]}"
    return None


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise InventoryError(f"git {' '.join(args)} failed in {root}: {result.stderr.strip()[:200]}")
    return result.stdout


def is_git_root(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def git_state(root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD").strip()
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    tracked = set(line for line in _git(root, "ls-files", "-z").split("\0") if line)
    untracked: set[str] = set()
    ignored: set[str] = set()
    status = _git(root, "status", "--porcelain=v1", "-z", "--ignored", "-uall")
    for entry in status.split("\0"):
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        if code == "??":
            untracked.add(rel)
        elif code == "!!":
            ignored.add(rel)
    return {"head": head, "branch": branch, "tracked": tracked, "untracked": untracked, "ignored": ignored}


def sqlite_summary(path: Path) -> dict[str, Any]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        return {"error": type(exc).__name__}
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts: dict[str, int] = {}
        for table in tables:
            try:
                counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            except sqlite3.Error:
                counts[table] = -1
        meta = {}
        if "store_meta" in tables:
            meta = {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM store_meta")}
        return {"tables": counts, "store_meta": meta}
    except sqlite3.Error as exc:
        return {"error": type(exc).__name__}
    finally:
        conn.close()


def _excluded(parts: Sequence[str], excludes: Sequence[str]) -> bool:
    return any(part in excludes for part in parts)


def walk_root(name: str, root: Path, *, excludes: Sequence[str], hash_limit: int | None,
              tracked_per_file_dirs: Sequence[str]) -> Iterable[dict[str, Any]]:
    """Yield inventory records for one root; nested git checkouts are summarised."""
    root = root.resolve()
    if not root.exists():
        yield {"record": "ROOT_MISSING", "root": name, "path": str(root)}
        return
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        if is_git_root(current):
            yield from _walk_git(name, root, current, excludes=excludes, hash_limit=hash_limit,
                                 tracked_per_file_dirs=tracked_per_file_dirs)
            continue
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            yield {"record": "UNREADABLE", "root": name, "path": str(current), "error": type(exc).__name__}
            continue
        for entry in entries:
            rel = entry.relative_to(root).as_posix()
            if _excluded(entry.relative_to(root).parts, excludes):
                continue
            if entry.is_symlink():
                yield {"record": "SYMLINK", "root": name, "relpath": rel, "target": os.readlink(entry)}
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield file_record(name, root, entry, git_class="FILESYSTEM", hash_limit=hash_limit)


def _walk_git(name: str, root: Path, checkout: Path, *, excludes: Sequence[str], hash_limit: int | None,
              tracked_per_file_dirs: Sequence[str]) -> Iterable[dict[str, Any]]:
    state = git_state(checkout)
    prefix = checkout.relative_to(root).as_posix() if checkout != root else ""
    tracked_summary: dict[str, dict[str, int]] = {}
    for rel in sorted(state["tracked"]):
        path = checkout / rel
        if not path.is_file():
            continue
        top = rel.split("/", 1)[0]
        per_file = any(rel == d or rel.startswith(d.rstrip("/") + "/") for d in tracked_per_file_dirs)
        if per_file:
            yield file_record(name, root, path, git_class="TRACKED", hash_limit=hash_limit,
                              checkout_head=state["head"], checkout=prefix)
        else:
            bucket = tracked_summary.setdefault(top, {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += path.stat().st_size
    yield {
        "record": "GIT_TREE", "root": name, "checkout": prefix or ".", "head": state["head"],
        "branch": state["branch"], "tracked_files": len(state["tracked"]),
        "tracked_summary_by_top_dir": tracked_summary,
        "note": "tracked files are recoverable from Git history at this HEAD; per-file records only for data dirs",
    }
    for cls, paths in (("UNTRACKED", state["untracked"]), ("IGNORED", state["ignored"])):
        for rel in sorted(paths):
            path = checkout / rel
            parts = Path(rel).parts
            if _excluded(parts, excludes):
                continue
            if path.is_dir():
                for sub in sorted(path.rglob("*")):
                    if sub.is_file() and not _excluded(sub.relative_to(checkout).parts, excludes):
                        if is_git_root(sub.parent) and sub.parent != checkout:
                            continue
                        yield file_record(name, root, sub, git_class=cls, hash_limit=hash_limit,
                                          checkout_head=state["head"], checkout=prefix)
            elif path.is_file():
                yield file_record(name, root, path, git_class=cls, hash_limit=hash_limit,
                                  checkout_head=state["head"], checkout=prefix)


def file_record(name: str, root: Path, path: Path, *, git_class: str, hash_limit: int | None,
                checkout_head: str | None = None, checkout: str = "") -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    stat = path.stat()
    record: dict[str, Any] = {
        "record": "FILE", "root": name, "relpath": rel, "checkout": checkout or None,
        "git_class": git_class, "checkout_head": checkout_head,
        "bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }
    if is_secret(rel):
        record.update({"category": "SECRET", "purpose": "密钥/口令,不作为数据迁移", "destination": "SECRET_NOT_MIGRATED(新环境安全配置)",
                       "migration": "NOT_MIGRATED", "sha256": None, "version_hint": None})
        return record
    category, purpose, destination = classify(rel, name)
    record.update({"category": category, "purpose": purpose, "destination": destination,
                   "migration": must_migrate(category, git_class),
                   "sha256": sha256_file(path, hash_limit), "version_hint": version_hint(rel)})
    if path.suffix == ".sqlite3":
        record["sqlite"] = sqlite_summary(path)
    return record


def referenced_pointers(roots: Mapping[str, Path]) -> list[dict[str, Any]]:
    """Follow known publication pointers and record whether their targets exist."""
    gaps: list[dict[str, Any]] = []
    for name, root in roots.items():
        for pointer in ("experiments/execution_tracker/current_run.json", "public/data/v2/current_run.json"):
            path = root / pointer
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                gaps.append({"root": name, "pointer": pointer, "status": "UNREADABLE_POINTER"})
                continue
            manifest = payload.get("manifest_path")
            run_id = payload.get("run_id")
            if manifest:
                target = root / "experiments/execution_tracker" / str(manifest)
                gaps.append({"root": name, "pointer": pointer, "run_id": run_id, "manifest_path": str(manifest),
                             "status": "PRESENT" if target.is_file() else "MISSING_REFERENCED"})
    return gaps


def summarise(records: Sequence[Mapping[str, Any]], gaps: Sequence[Mapping[str, Any]], roots: Mapping[str, Path]) -> str:
    files = [r for r in records if r.get("record") == "FILE"]
    trees = [r for r in records if r.get("record") == "GIT_TREE"]
    agg: dict[tuple[str, str, str], dict[str, int]] = {}
    for r in files:
        key = (r["root"], r["category"], r["git_class"])
        bucket = agg.setdefault(key, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += int(r["bytes"])
    lines = ["# 迁移全量盘点摘要", "", f"- 生成时间: {_now()}", f"- 根: " + ", ".join(f"`{k}`={v}" for k, v in roots.items()),
             f"- 文件记录: {len(files)}; git 树摘要: {len(trees)}; 缺件/指针检查: {len(gaps)}", "",
             "## 根 × 类别 × git 分类", "", "| 根 | 类别 | git 分类 | 文件数 | 字节 |", "|---|---|---|---:|---:|"]
    for (root, category, cls), bucket in sorted(agg.items()):
        lines.append(f"| {root} | {category} | {cls} | {bucket['files']} | {bucket['bytes']:,} |")
    mig: dict[str, dict[str, int]] = {}
    seen_hash: set[str] = set()
    unique_bytes = 0
    for r in files:
        bucket = mig.setdefault(r.get("migration", "?"), {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += int(r["bytes"])
        digest = r.get("sha256")
        if r.get("migration") == "MIGRATE" and digest and digest not in seen_hash:
            seen_hash.add(digest)
            unique_bytes += int(r["bytes"])
    lines += ["", "## 迁移集合(按 sha256 去重后的 MIGRATE 唯一内容)", "", "| 迁移分类 | 文件数 | 字节 |", "|---|---:|---:|"]
    for key, bucket in sorted(mig.items()):
        lines.append(f"| {key} | {bucket['files']} | {bucket['bytes']:,} |")
    lines.append(f"| MIGRATE 去重唯一内容 | {len(seen_hash)} | {unique_bytes:,} |")
    lines += ["", "## Git 树(tracked,按 HEAD 可恢复)", "", "| 根 | checkout | HEAD | tracked 文件 |", "|---|---|---|---:|"]
    for t in trees:
        lines.append(f"| {t['root']} | {t['checkout']} | {t['head'][:12]} | {t['tracked_files']} |")
    unclassified = [r for r in files if r["category"] == "UNCLASSIFIED"]
    lines += ["", f"## 未归类(需人工,{len(unclassified)})", ""]
    for r in unclassified[:80]:
        lines.append(f"- `{r['root']}:{r['relpath']}` ({r['bytes']:,} B)")
    if len(unclassified) > 80:
        lines.append(f"- … 另 {len(unclassified) - 80} 项见 inventory.jsonl")
    secrets = [r for r in files if r["category"] == "SECRET"]
    lines += ["", f"## 密钥类(登记不迁移,{len(secrets)})", ""] + [f"- `{r['root']}:{r['relpath']}`" for r in secrets]
    lines += ["", "## 指针与缺件", ""]
    for g in gaps:
        lines.append(f"- {g['root']}: `{g['pointer']}` → {g.get('manifest_path')} · **{g['status']}**")
    stores = [r for r in files if r.get("sqlite")]
    lines += ["", "## SQLite 仓(只读行数)", ""]
    for r in stores:
        tables = r["sqlite"].get("tables") or {}
        lines.append(f"- `{r['root']}:{r['relpath']}` ({r['bytes']:,} B) meta={r['sqlite'].get('store_meta')} 表={len(tables)} 行合计={sum(v for v in tables.values() if v > 0):,}")
    lines += ["", DISCLAIMER, ""]
    return "\n".join(lines)


def run(roots: Mapping[str, Path], out_dir: Path, *, excludes: Sequence[str], hash_limit: int | None,
        tracked_per_file_dirs: Sequence[str]) -> dict[str, Any]:
    for root in roots.values():
        if out_dir.resolve() == root.resolve() or root.resolve() in out_dir.resolve().parents:
            raise InventoryError("output directory must not live inside a scanned root")
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for name, root in roots.items():
        records.extend(walk_root(name, root, excludes=excludes, hash_limit=hash_limit,
                                 tracked_per_file_dirs=tracked_per_file_dirs))
    gaps = referenced_pointers(roots)
    inventory = out_dir / "inventory.jsonl"
    with inventory.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    (out_dir / "INVENTORY_SUMMARY.md").write_text(summarise(records, gaps, roots), encoding="utf-8")
    receipt = {
        "schema": SCHEMA, "generated_at": _now(), "roots": {k: str(v) for k, v in roots.items()},
        "records": len(records), "gaps": gaps, "inventory_sha256": sha256_file(inventory),
        "tool_sha256": sha256_file(Path(__file__).resolve()), "hash_limit_bytes": hash_limit,
        "excludes": list(excludes), "disclaimer": DISCLAIMER,
    }
    (out_dir / "run_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def _selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="ar-inventory-") as raw:
        tmp = Path(raw)
        root = tmp / "root"
        (root / "data_history").mkdir(parents=True)
        (root / "experiments/execution_tracker/model_fund").mkdir(parents=True)
        (root / "node_modules/x").mkdir(parents=True)
        (root / "node_modules/x/junk.js").write_text("ignored", encoding="utf-8")
        db = root / "data_history/feature_store.sqlite3"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE store_meta(key TEXT, value TEXT)")
        conn.execute("INSERT INTO store_meta VALUES('schema_version','2')")
        conn.execute("CREATE TABLE raw_daily(ts_code TEXT)")
        conn.executemany("INSERT INTO raw_daily VALUES(?)", [("a",), ("b",)])
        conn.commit(); conn.close()
        (root / "experiments/execution_tracker/model_fund/nav_history.json").write_text("{}", encoding="utf-8")
        (root / "experiments/execution_tracker/current_run.json").write_text(
            json.dumps({"run_id": "20260828_163504_1787906104453843000_b52ddd98",
                        "manifest_path": "runs/20260828_163504_1787906104453843000_b52ddd98/manifest.json"}),
            encoding="utf-8")
        (root / ".ar_env").write_text("export TUSHARE_TOKEN=should-never-be-read\n", encoding="utf-8")
        (root / "mystery.bin").write_bytes(b"\x00\x01")
        out = tmp / "out"
        receipt = run({"fixture": root}, out, excludes=DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
        records = [json.loads(line) for line in (out / "inventory.jsonl").read_text(encoding="utf-8").splitlines()]
        by_rel = {r["relpath"]: r for r in records if r.get("record") == "FILE"}
        checks = {
            "sqlite_summarised": by_rel["data_history/feature_store.sqlite3"]["sqlite"]["tables"] == {"raw_daily": 2, "store_meta": 1},
            "category_history": by_rel["data_history/feature_store.sqlite3"]["category"] == "MARKET_FINANCIAL_FLOW_MACRO_HISTORY",
            "category_paper": by_rel["experiments/execution_tracker/model_fund/nav_history.json"]["category"] == "PAPER_PORTFOLIO_LEDGER",
            "secret_not_hashed": by_rel[".ar_env"]["category"] == "SECRET" and by_rel[".ar_env"]["sha256"] is None,
            "unclassified_listed": by_rel["mystery.bin"]["category"] == "UNCLASSIFIED",
            "node_modules_excluded": "node_modules/x/junk.js" not in by_rel,
            "missing_manifest_recorded": any(g["status"] == "MISSING_REFERENCED" for g in receipt["gaps"]),
            "hash_present": len(by_rel["mystery.bin"]["sha256"]) == 64,
            "secret_value_absent": "should-never-be-read" not in (out / "inventory.jsonl").read_text(encoding="utf-8"),
        }
        failed = [k for k, ok in checks.items() if not ok]
        if failed:
            print("SELFTEST FAIL: " + ", ".join(failed), file=sys.stderr)
            return 1
        try:
            run({"fixture": root}, root / "out-inside", excludes=DEFAULT_EXCLUDES, hash_limit=None, tracked_per_file_dirs=())
        except InventoryError:
            checks["refuses_output_inside_root"] = True
        else:
            print("SELFTEST FAIL: output inside root was accepted", file=sys.stderr)
            return 1
    print("SELFTEST OK: " + ",".join(checks))
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], metavar="NAME=PATH",
                        help="a root to inventory (repeatable), e.g. ar-live=/Users/x/ar-live")
    parser.add_argument("--out", help="output directory (must not be inside any root)")
    parser.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDES), help="directory names to skip")
    parser.add_argument("--hash-limit-bytes", type=int, default=None, help="skip sha256 for files larger than this")
    parser.add_argument("--tracked-per-file-dir", action="append", default=["public/data", "docs/research", "data"],
                        help="tracked dirs listed per file (others are summarised per checkout)")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.root or not args.out:
        print("REFUSED: --root NAME=PATH (repeatable) and --out are required", file=sys.stderr)
        return 2
    roots: dict[str, Path] = {}
    for item in args.root:
        if "=" not in item:
            print(f"REFUSED: bad --root {item!r}", file=sys.stderr)
            return 2
        name, path = item.split("=", 1)
        roots[name] = Path(path).expanduser()
    try:
        receipt = run(roots, Path(args.out).expanduser(), excludes=tuple(args.exclude),
                      hash_limit=args.hash_limit_bytes, tracked_per_file_dirs=tuple(args.tracked_per_file_dir))
    except InventoryError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"inventory records={receipt['records']} gaps={len(receipt['gaps'])} out={args.out} sha256={receipt['inventory_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
