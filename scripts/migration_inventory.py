#!/usr/bin/env python3
"""Read-only migration inventory (第一步·全量盘点).

Walks every root the operator names — the production checkout, the engineering
checkout, sandbox / evidence directories, backups, worktrees — and registers
each file with its source root, git class (TRACKED / UNTRACKED / IGNORED /
FILESYSTEM), size, mtime, sha256, category, purpose, version hint and proposed
destination on the new platform. Nested git checkouts are detected and their
tracked trees are summarised (recoverable from Git history) while every
untracked / ignored file — the run data that is NOT in Git — is listed one by
one. SQLite stores are NOT opened: DB/WAL/journal files are inventoried pending
a consistent snapshot. Path-classified secrets are never read or hashed and are
registered as SECRET_NOT_MIGRATED so the record shows
they exist and must be configured, not copied.

The tool writes nothing inside any root. Outputs go to --out:
  inventory.jsonl          one record per file / tree summary
  INVENTORY_SUMMARY.md     counts and bytes per root × category, gaps, secrets
  run_receipt.json         roots, HEADs, generated_at, tool sha256, inventory sha256

Git child processes run with protocol.allow=never (the effective offline guard on every git
version) plus GIT_NO_LAZY_FETCH / GIT_OPTIONAL_LOCKS=0 (honoured by newer git only).
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
import stat as stat_mode
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "ar.migration_inventory.v1"
DISCLAIMER = "盘点清单,不是迁移本身;缺件只登记不补造。不是买卖指令;研究信号,human executes."

DEFAULT_EXCLUDES = ("node_modules", ".git", "__pycache__", ".DS_Store", ".pytest_cache", ".venv", "dist")
# Path-name classification only (never a content scan). A hit means: never read, never hash,
# never migrate. Filename component only, so a directory called "tokens/" does not swallow its
# children. Known false positive kept on purpose: a research note named *token* loses its hash
# but stays listed — the safe direction.
SECRET_PATTERNS = (
    re.compile(r"(^|/)\.ar_env($|\.)"), re.compile(r"(^|/)\.env($|\.|rc$)"), re.compile(r"(^|/)\.envrc$"),
    re.compile(r"(^|/)\.netrc$"), re.compile(r"(^|/)\.git-credentials$"), re.compile(r"(^|/)\.(npmrc|pypirc)$"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"(^|/)[^/]*credential[^/]*$", re.I), re.compile(r"(^|/)[^/]*token[^/]*$", re.I),
    re.compile(r"(^|/)[^/]*secret[^/]*$", re.I), re.compile(r"(^|/)[^/]*(passw(or)?d|apikey|api_key)[^/]*$", re.I),
    re.compile(r"\.(pem|key|p12|pfx|jks|keystore)$", re.I),
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
    (r"(^|/)data_history/panel/|\.parquet$|(^|/)data_history/sector_mapping\.json$", "LEGACY_HISTORY",
     "旧平台市场面板与映射;来源与质量待验证,不得自动用于正式研究", "数据中心 · legacy · 只读"),
    (r"\.(sqlite3|sqlite|db)-(wal|journal)$", "SQLITE_RECOVERY_COMPONENT",
     "数据库恢复组件;取得一致性快照前不得丢弃", "数据中心 · 待快照(不独立恢复)"),
    (r"\.(lock|sqlite3-shm|sqlite-shm|db-shm)$|(^|/)\.[a-z0-9_]+\.lock$", "TRANSIENT_NOT_MIGRATED",
     "运行时锁/共享内存(不含 WAL 或 journal)", "不迁移(新环境自生)"),
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
    (r"(^|/)execution_tracker/(position_review|promotion_queue|red_flags|rotation_panel|rotation_stats|rotation_validation|run_target|watch_dynamic|watchtower_state)\.json$",
     "OPS_RUNS_PUBLICATION_AUDIT", "夜链日切状态(工作树,通常领先于提交)", "运行监控 · 审计"),
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


@contextmanager
def regular_reader(path: Path, root: Path | None = None):
    """Open relative to pinned directory descriptors; never follow components."""
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise InventoryError("no-follow directory-relative IO is required on this host")
    lexical_anchor = Path(os.path.abspath(root or path.parent))
    anchor = lexical_anchor.resolve()
    absolute = Path(os.path.abspath(path))
    try:
        parts = absolute.relative_to(lexical_anchor).parts
        if not parts or any(p in (".", "..") for p in parts):
            raise InventoryError("invalid relative source path")
        directory = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat_mode.S_ISREG(before.st_mode):
                raise InventoryError("source must be a regular file")
            yield handle
            after = os.fstat(handle.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise InventoryError("source changed during inspection")
    except (OSError, ValueError) as exc:
        raise InventoryError(f"unsafe or unreadable source: {path}") from exc


def sha256_file(path: Path, limit: int | None = None, *, root: Path | None = None) -> str | None:
    with regular_reader(path, root) as handle:
        if limit is not None and os.fstat(handle.fileno()).st_size > limit:
            return None
        digest = hashlib.sha256()
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
    if git_class == "MODIFIED":
        return "MIGRATE"  # live working-tree state ahead of the last commit
    if git_class == "TRACKED":
        return "GIT_RECOVERABLE"
    if category in HISTORY_CATEGORIES or category in ("AGENT_OPS_RECORDS", "UNCLASSIFIED"):
        return "MIGRATE"
    return "MIGRATE"


def version_hint(relpath: str) -> str | None:
    run = RUN_ID_RE.search(relpath)
    if run:
        return f"run_id:{run.group(1)}"
    dates = DATE8_RE.findall(relpath)
    if dates:
        return f"as_of:{dates[-1]}"
    return None


def _git_result(root: Path, *args: str):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false",
                           "-C", str(root), *args], env=env, capture_output=True, check=False)


def _git(root: Path, *args: str) -> str:
    result = _git_result(root, *args)
    if result.returncode != 0:
        raise InventoryError(f"git {' '.join(args)} failed in {root}; no network fallback")
    return os.fsdecode(result.stdout)


def is_git_root(path: Path) -> bool:
    """A checkout marker is a real .git dir or file; a symlinked .git is never followed."""
    try:
        marker = os.lstat(path / ".git")
    except OSError:
        return False
    return stat_mode.S_ISDIR(marker.st_mode) or stat_mode.S_ISREG(marker.st_mode)


def git_state(root: Path) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD").strip()
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    tracked = set(line for line in _git(root, "ls-files", "-z").split("\0") if line)
    untracked: set[str] = set()
    ignored: set[str] = set()
    modified: set[str] = set()
    deleted: set[str] = set()
    status = _git(root, "status", "--porcelain=v1", "-z", "--ignored", "-uall")
    entries = status.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        if code[0] in "RC" or code[1] in "RC":
            if "R" in code:
                deleted.add(entries[index])
            index += 1
        if "D" in code:
            deleted.add(rel)
        if code == "??":
            untracked.add(rel)
        elif code == "!!":
            ignored.add(rel)
        elif any(ch in "MADRCU" for ch in code):
            modified.add(rel)  # tracked, but the working tree differs from HEAD: not in Git
    return {"head": head, "branch": branch, "tracked": tracked, "untracked": untracked,
            "ignored": ignored, "modified": modified, "deleted": deleted}


def head_blob_sha256(checkout: Path, rel: str) -> str | None:
    result = _git_result(checkout, "show", f"HEAD:{rel}")
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def sqlite_summary(path: Path) -> dict[str, Any]:
    # mode=ro is not an OS-level no-write guarantee. Inventory never opens SQLite.
    return {"status": "SNAPSHOT_REQUIRED", "inspection": "ENGINE_NOT_OPENED",
            "reason": "DB/WAL/journal must be bound to a consistent snapshot before row counts or restore",
            "components": [path.name, path.name + "-wal", path.name + "-journal"],
            "row_counts": None, "integrity_verified": False}


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
                yield link_record(name, root, entry)
                continue
            if entry.is_dir():
                stack.append(entry)
            else:
                yield leaf_record(name, root, entry, git_class="FILESYSTEM", hash_limit=hash_limit)


def _walk_git(name: str, root: Path, checkout: Path, *, excludes: Sequence[str], hash_limit: int | None,
              tracked_per_file_dirs: Sequence[str]) -> Iterable[dict[str, Any]]:
    state = git_state(checkout)
    prefix = checkout.relative_to(root).as_posix() if checkout != root else ""
    tracked_summary: dict[str, dict[str, int]] = {}
    # Everything this pass accounted for, checkout-relative: emitted records plus the tracked
    # files that are only summarised. The reconciliation sweep below uses it to find what git
    # never reported at all.
    accounted: set[str] = set(state["tracked"]) | set(state["deleted"])
    walked_checkouts: set[str] = set()

    def track(record: dict[str, Any]) -> dict[str, Any]:
        rel = record.get("relpath")
        if isinstance(rel, str):
            absolute = root / rel
            try:
                accounted.add(absolute.relative_to(checkout).as_posix())
            except ValueError:
                pass
        if record.get("record") == "GIT_TREE" and record.get("checkout") not in (None, "."):
            nested = root / str(record["checkout"])
            try:
                walked_checkouts.add(nested.relative_to(checkout).as_posix())
            except ValueError:
                pass
        return record
    for rel in sorted(state["deleted"]):
        yield track({"record": "TOMBSTONE", "root": name,
               "relpath": (checkout / rel).relative_to(root).as_posix(), "checkout": prefix or None,
               "checkout_head": state["head"], "operation": "DELETE", "migration": "APPLY_TOMBSTONE"})
    for rel in sorted(state["tracked"]):
        path = checkout / rel
        if path.is_symlink():
            yield track(link_record(name, root, path))
            continue
        if not path.is_file():
            continue
        top = rel.split("/", 1)[0]
        if rel in state["modified"]:
            record = file_record(name, root, path, git_class="MODIFIED", hash_limit=hash_limit,
                                 checkout_head=state["head"], checkout=prefix)
            if record["category"] != "SECRET":
                record["head_sha256"] = head_blob_sha256(checkout, rel)
            yield track(record)
            continue
        per_file = any(rel == d or rel.startswith(d.rstrip("/") + "/") for d in tracked_per_file_dirs)
        if per_file:
            yield track(file_record(name, root, path, git_class="TRACKED", hash_limit=hash_limit,
                                    checkout_head=state["head"], checkout=prefix))
        else:
            bucket = tracked_summary.setdefault(top, {"files": 0, "bytes": 0})
            bucket["files"] += 1
            bucket["bytes"] += path.stat().st_size
    yield track({
        "record": "GIT_TREE", "root": name, "checkout": prefix or ".", "head": state["head"],
        "branch": state["branch"], "tracked_files": len(state["tracked"]),
        "git_recovery_status": "LOCAL_HEAD_RECORDED_REMOTE_AVAILABILITY_NOT_VERIFIED",
        "tracked_summary_by_top_dir": tracked_summary, "modified_tracked_files": len(state["modified"]),
        "note": "tracked files are recoverable from Git history at this HEAD; per-file records for data dirs and for MODIFIED working-tree files (whose content is not in Git)",
    })
    for cls, paths in (("UNTRACKED", state["untracked"]), ("IGNORED", state["ignored"])):
        for rel in sorted(paths):
            path = checkout / rel
            parts = Path(rel).parts
            if _excluded(parts, excludes):
                continue
            if path.is_symlink():
                yield track(link_record(name, root, path))
                continue
            if path.is_dir():
                for record in _walk_loose_dir(name, root, checkout, path, cls, state["head"], prefix,
                                              excludes=excludes, hash_limit=hash_limit,
                                              tracked_per_file_dirs=tracked_per_file_dirs):
                    yield track(record)
            else:
                yield track(leaf_record(name, root, path, git_class=cls, hash_limit=hash_limit,
                                        checkout_head=state["head"], checkout=prefix))
    # Git reports neither special files (FIFO/socket) nor anything under a directory it could
    # not read, so a git-only pass is not a full inventory. Sweep the checkout and register
    # every entry this pass did not account for.
    # governance-mutation: MIGRATION_GIT_BLIND_SPOTS_SWEPT
    yield from _reconcile_checkout(name, root, checkout, accounted, walked_checkouts, prefix,
                                   state["head"], excludes=excludes, hash_limit=hash_limit,
                                   tracked_per_file_dirs=tracked_per_file_dirs)


def _skip_reconcile(*args: Any, **kwargs: Any) -> Iterable[dict[str, Any]]:
    """Mutation target only: the disabled form of the reconciliation sweep."""
    return ()


def _reconcile_checkout(name: str, root: Path, checkout: Path, accounted: set[str],
                        walked_checkouts: set[str], prefix: str, head: str, *,
                        excludes: Sequence[str], hash_limit: int | None,
                        tracked_per_file_dirs: Sequence[str]) -> Iterable[dict[str, Any]]:
    """Register what git never reported: special files, unreadable dirs, and files beneath them.

    Anything already accounted for by the git pass is skipped, so this adds records and never
    duplicates them. Entries found here carry git_class UNREPORTED_BY_GIT: they exist on disk,
    Git does not know about them, therefore they must be migrated explicitly."""
    errors: list[dict[str, Any]] = []

    def onerror(exc: OSError) -> None:
        errors.append(_unreadable_record(name, root, exc))

    for dirpath, dirnames, filenames in os.walk(checkout, topdown=True, onerror=onerror, followlinks=False):
        current = Path(dirpath)
        keep: list[str] = []
        for child_name in sorted(dirnames):
            child = current / child_name
            rel = child.relative_to(checkout).as_posix()
            if child_name == ".git" or _excluded(child.relative_to(checkout).parts, excludes):
                continue
            if rel in walked_checkouts:
                continue
            if child.is_symlink():
                if rel not in accounted:
                    yield link_record(name, root, child)
                continue
            if is_git_root(child):
                # A checkout git never reported (e.g. hidden under a directory it could not read).
                yield from _walk_git(name, root, child, excludes=excludes, hash_limit=hash_limit,
                                     tracked_per_file_dirs=tracked_per_file_dirs)
                continue
            keep.append(child_name)
        dirnames[:] = keep
        for file_name in sorted(filenames):
            entry = current / file_name
            rel = entry.relative_to(checkout).as_posix()
            if rel in accounted or _excluded(entry.relative_to(checkout).parts, excludes):
                continue
            if entry.is_symlink():
                yield link_record(name, root, entry)
                continue
            yield leaf_record(name, root, entry, git_class="UNREPORTED_BY_GIT", hash_limit=hash_limit,
                              checkout_head=head, checkout=prefix)
        while errors:
            yield errors.pop(0)
    while errors:
        yield errors.pop(0)


def _walk_loose_dir(name: str, root: Path, checkout: Path, top: Path, cls: str, head: str, prefix: str, *,
                    excludes: Sequence[str], hash_limit: int | None,
                    tracked_per_file_dirs: Sequence[str]) -> Iterable[dict[str, Any]]:
    """Untracked/ignored directory under a checkout. A nested checkout found inside it is
    summarised as its own GIT_TREE (its files attributed to ITS head), never merged into the
    outer tree; symlinks are registered, not followed; unreadable dirs become records."""
    # governance-mutation: MIGRATION_NESTED_CHECKOUT_SUMMARISED
    if is_git_root(top):
        yield from _walk_git(name, root, top, excludes=excludes, hash_limit=hash_limit,
                             tracked_per_file_dirs=tracked_per_file_dirs)
        return
    errors: list[dict[str, Any]] = []

    def onerror(exc: OSError) -> None:
        errors.append(_unreadable_record(name, root, exc))

    for dirpath, dirnames, filenames in os.walk(top, topdown=True, onerror=onerror, followlinks=False):
        current = Path(dirpath)
        keep: list[str] = []
        for child_name in sorted(dirnames):
            child = current / child_name
            if _excluded(child.relative_to(checkout).parts, excludes):
                continue
            if child.is_symlink():
                yield link_record(name, root, child)
                continue
            if is_git_root(child):
                yield from _walk_git(name, root, child, excludes=excludes, hash_limit=hash_limit,
                                     tracked_per_file_dirs=tracked_per_file_dirs)
                continue
            keep.append(child_name)
        dirnames[:] = keep
        for file_name in sorted(filenames):
            sub = current / file_name
            if _excluded(sub.relative_to(checkout).parts, excludes):
                continue
            if sub.is_symlink():
                yield link_record(name, root, sub)
                continue
            yield leaf_record(name, root, sub, git_class=cls, hash_limit=hash_limit, checkout_head=head, checkout=prefix)
        while errors:
            yield errors.pop(0)
    # os.walk reports a directory it could not read while producing the NEXT item, so the last
    # error can arrive after the final iteration body; drain again rather than lose it.
    while errors:
        yield errors.pop(0)


def _unreadable_record(name: str, root: Path, exc: OSError) -> dict[str, Any]:
    filename = str(exc.filename) if exc.filename else ""
    try:
        rel = Path(filename).relative_to(root).as_posix()
    except ValueError:
        rel = filename
    return {"record": "UNREADABLE", "root": name, "relpath": rel,
            "error": type(exc).__name__, "migration": "REVIEW_UNREADABLE"}


def leaf_record(name: str, root: Path, path: Path, *, git_class: str, hash_limit: int | None,
                checkout_head: str | None = None, checkout: str = "") -> dict[str, Any]:
    """A non-directory, non-symlink entry: FILE, or an explicit SPECIAL_FILE / UNREADABLE record."""
    rel = path.relative_to(root).as_posix()
    try:
        st = path.lstat()
    except OSError as exc:
        return {"record": "UNREADABLE", "root": name, "relpath": rel, "error": type(exc).__name__,
                "migration": "REVIEW_UNREADABLE"}
    if not stat_mode.S_ISREG(st.st_mode):
        return {"record": "SPECIAL_FILE", "root": name, "relpath": rel, "mode": stat_mode.filemode(st.st_mode),
                "migration": "NOT_MIGRATED"}
    try:
        return file_record(name, root, path, git_class=git_class, hash_limit=hash_limit,
                           checkout_head=checkout_head, checkout=checkout)
    except InventoryError as exc:
        return {"record": "UNREADABLE", "root": name, "relpath": rel, "git_class": git_class,
                "error": str(exc)[:160], "migration": "REVIEW_UNREADABLE"}


def link_record(name: str, root: Path, path: Path) -> dict[str, Any]:
    return {"record": "SYMLINK", "root": name, "relpath": path.relative_to(root).as_posix(),
            "target": os.readlink(path), "migration": "REVIEW_LINK_NO_FOLLOW"}


def file_record(name: str, root: Path, path: Path, *, git_class: str, hash_limit: int | None,
                checkout_head: str | None = None, checkout: str = "") -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    stat = path.lstat()
    if not stat_mode.S_ISREG(stat.st_mode):
        raise InventoryError("source is not a regular file")
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
                   "sha256": sha256_file(path, hash_limit, root=root), "version_hint": version_hint(rel)})
    if category == "LEGACY_HISTORY":
        record.update({"quality": "LEGACY_UNVALIDATED", "read_only": True, "active_research_input": False,
                       "provenance": {"root": name, "relpath": rel, "checkout_head": checkout_head}})
    if path.suffix in (".sqlite3", ".sqlite", ".db"):
        record["sqlite"] = sqlite_summary(path)
    return record


def referenced_pointers(roots: Mapping[str, Path]) -> list[dict[str, Any]]:
    """Follow known publication pointers and record whether their targets exist."""
    gaps: list[dict[str, Any]] = []
    for name, root in roots.items():
        for pointer in ("experiments/execution_tracker/current_run.json", "public/data/v2/current_run.json"):
            root = root.resolve()
            path = root / pointer
            if not path.is_file():
                continue
            try:
                with regular_reader(path, root) as handle:
                    payload = json.load(handle)
                if not isinstance(payload, dict):
                    raise ValueError("pointer is not an object")
            except (OSError, ValueError, InventoryError):
                gaps.append({"root": name, "pointer": pointer, "status": "UNREADABLE_POINTER"})
                continue
            manifest = payload.get("manifest_path")
            run_id = payload.get("run_id")
            if manifest:
                if not isinstance(manifest, str) or Path(manifest).is_absolute() or ".." in Path(manifest).parts or "\\" in manifest:
                    gaps.append({"root": name, "pointer": pointer, "status": "INVALID_POINTER"})
                    continue
                target = path.parent / manifest
                status = "MISSING_REFERENCED"
                if target.is_file() or target.is_symlink():
                    try:
                        with regular_reader(target, root):
                            status = "PRESENT"
                    except InventoryError:
                        status = "UNSAFE_REFERENCED"
                gaps.append({"root": name, "pointer": pointer, "run_id": run_id, "manifest_path": str(manifest),
                             "status": status})
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
    lines += ["", "## Git 树(tracked,按 HEAD 可恢复;MODIFIED = 工作树领先于提交,内容不在 Git)", "",
              "| 根 | checkout | HEAD | tracked 文件 | MODIFIED |", "|---|---|---|---:|---:|"]
    for t in trees:
        lines.append(f"| {t['root']} | {t['checkout']} | {t['head'][:12]} | {t['tracked_files']} | {t.get('modified_tracked_files', 0)} |")
    unreported = [r for r in files if r.get("git_class") == "UNREPORTED_BY_GIT"]
    specials = [r for r in records if r.get("record") in ("SPECIAL_FILE", "UNREADABLE")]
    lines += ["", f"## Git 未报告 / 不可读 / 特殊文件({len(unreported)} + {len(specials)})", ""]
    for r in unreported[:40]:
        lines.append(f"- 未被 Git 报告 `{r['root']}:{r['relpath']}` ({r['bytes']:,} B)")
    for r in specials[:40]:
        lines.append(f"- {r['record']} `{r['root']}:{r.get('relpath')}` {r.get('error') or r.get('mode') or ''}")
    modified = [r for r in files if r["git_class"] == "MODIFIED"]
    lines += ["", f"## 工作树已修改的 tracked 文件(内容不在 Git,必迁,{len(modified)})", ""]
    for r in modified[:120]:
        lines.append(f"- `{r['root']}:{r['relpath']}` ({r['bytes']:,} B) sha={str(r.get('sha256'))[:12]} head={str(r.get('head_sha256'))[:12]}")
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
    lines += ["", "## SQLite 仓(源引擎未打开;一致性快照前不声称行数)", ""]
    for r in stores:
        lines.append(f"- `{r['root']}:{r['relpath']}` ({r['bytes']:,} B) **{r['sqlite']['status']}**, row_counts=null")
    tombstones = [r for r in records if r.get("record") == "TOMBSTONE"]
    lines += ["", "## 工作树删除记录(不得恢复后重新带回)", ""]
    lines += [f"- `{r['root']}:{r['relpath']}` DELETE @ {r['checkout_head']}" for r in tombstones]
    lines += ["", "## 范围与一致性边界", "",
              "逐文件盘点不是跨文件一致性快照;SNAPSHOT_REQUIRED、缺根、缺件与未分类必须在导入前闭环。",
              "GIT_RECOVERABLE 只记录本地 HEAD,仍须独立证明对应对象在目的地可恢复。",
              "legacy 面板为 LEGACY_UNVALIDATED、只读、非正式研究输入。",
              "路径分类不是通用密钥检测;归档与普通文件上传仍须单独检查许可和敏感信息。"]
    lines += ["", DISCLAIMER, ""]
    return "\n".join(lines)


def _write_new_file(directory: int, name: str, content: str) -> str:
    data = content.encode("utf-8")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return hashlib.sha256(data).hexdigest()


def run(roots: Mapping[str, Path], out_dir: Path, *, excludes: Sequence[str], hash_limit: int | None,
        tracked_per_file_dirs: Sequence[str]) -> dict[str, Any]:
    for root in roots.values():
        # governance-mutation: MIGRATION_OUTPUT_OUTSIDE_ROOTS
        if out_dir.resolve() == root.resolve() or root.resolve() in out_dir.resolve().parents:
            raise InventoryError("output directory must not live inside a scanned root")
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise InventoryError("no-follow directory-relative IO is required on this host")
    # The output directory is claimed exclusively BEFORE the walk (two concurrent runs
    # cannot both succeed); if the walk then fails, the still-empty directory is removed
    # so a refused or aborted scan never blocks the retry.
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise InventoryError("output must be new; cannot exclusively create directory") from exc
    records: list[dict[str, Any]] = []
    try:
        for name, root in roots.items():
            records.extend(walk_root(name, root, excludes=excludes, hash_limit=hash_limit,
                                     tracked_per_file_dirs=tracked_per_file_dirs))
        gaps = referenced_pointers(roots)
    except BaseException:
        try:
            if not any(out_dir.iterdir()):
                out_dir.rmdir()
        except OSError:
            pass
        raise
    inventory_text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    receipt = {
        "schema": SCHEMA, "generated_at": _now(), "roots": {k: str(v) for k, v in roots.items()},
        "records": len(records), "gaps": gaps,
        "consistency": "PER_FILE_INVENTORY_NOT_A_SNAPSHOT",
        "migration_ready": False, "production_authority": False,
        "sqlite_inspection": "ENGINE_NOT_OPENED_SNAPSHOT_REQUIRED",
        "tool_sha256": sha256_file(Path(__file__).resolve()), "hash_limit_bytes": hash_limit,
        "excludes": list(excludes), "disclaimer": DISCLAIMER,
    }
    try:
        directory = os.open(out_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            receipt["inventory_sha256"] = _write_new_file(directory, "inventory.jsonl", inventory_text)
            _write_new_file(directory, "INVENTORY_SUMMARY.md", summarise(records, gaps, roots))
            _write_new_file(directory, "run_receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        finally:
            os.close(directory)
    except OSError as exc:
        raise InventoryError("output creation refused; existing files were not truncated") from exc
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
            "sqlite_snapshot_required": by_rel["data_history/feature_store.sqlite3"]["sqlite"]["status"] == "SNAPSHOT_REQUIRED",
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
