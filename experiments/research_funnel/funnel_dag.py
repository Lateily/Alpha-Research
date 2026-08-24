#!/usr/bin/env python3
"""研究漏斗三段子 DAG:funnel_candidates → candidate_battery → funnel_finalize。

为什么拆三段
------------
U3 需要每只候选的六维电池,而电池要走网络。原来的 `research_funnel` 是纯离线、
确定性的一步 —— 把网络采集直接塞进去,会让契约层沾上副作用与不可复现性。所以:

  1. funnel_candidates  纯计算 U0/U1/U2,产出**不可变候选清单**(candidate_manifest)
  2. candidate_battery  **唯一**网络步骤:绑定候选清单 hash,逐票跑六维电池;
                        数据源整体失败也要形成**逐票** DATA_BLOCKED,结构损坏才失败
  3. funnel_finalize    纯计算:校验电池覆盖集合与候选清单**完全相等**,再生成 U3/U4

三段同 as_of、同 run_id、同 bundle 目录、同候选 hash。任何一段读不到前段的产物、
或前段产物的 hash 对不上,就 fail-closed。禁止 T-1 候选、禁止 watchlist 回退、
禁止静默缺行。候选数量从 manifest 读,不硬编码。

外层仍是隔离观察步:三段挂了都记 DATA_BLOCKED,不否决 NAV/账本/其余研究发布。
U4 的 3–5 只人工选择门不放宽。`full_battery --from-watchlist` 保留给 court/promoter,
本模块不动它;它的单票函数 `battery(pro, tk, today)` 被复用。

不是买卖指令;研究信号,human executes.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "execution_tracker"))

from funnel_pipeline import (  # noqa: E402
    BATTERY_DIMENSIONS,
    BATTERY_U2_SCHEMA,
    DISCLAIMER,
    RULE_VERSION,
    SCHEMA_VERSION,
    FunnelError,
    _atomic_write_json,
    _date8,
    _hash,
    _load_json,
    advance_registry,
    build_all_market_scan,
    build_candidate_manifest,
    build_candidate_review,
    build_deep_research_queue,
    load_feature_snapshot,
    validate_candidate_battery,
    validate_candidate_manifest,
)
from nightly_funnel import (  # noqa: E402
    BUNDLE_FILES,
    DAG_EVIDENCE_FILES,
    DEFAULT_RETENTION_DAYS,
    REPO_ROOT,
    _bundle_dir,
    _require_env,
    _sha256,
    build_health,
    observation_root,
    prune_observation_area,
    published_bundle_date,
)
import semiconductor_inputs as semiconductor_evidence  # noqa: E402

STAGE1_FILES = ("all_market_scan.json", "candidate_review.json", "candidate_manifest.json")
STAGE2_FILES = ("candidate_battery.json",)
STAGE3_FILES = ("deep_research_queue.json", "security_registry_projected.json")
INDUSTRY_TAXONOMY_PATH = Path(__file__).resolve().with_name("industry_taxonomy.v1.json")


# ── 公共:分段 manifest ────────────────────────────────────────────────────

def _stage_manifest_path(bundle_dir: Path, stage: str) -> Path:
    return bundle_dir / f"stage_{stage}.json"


def _write_stage(bundle_dir: Path, stage: str, files: dict[str, dict], *,
                 as_of: str, run_id: str, generated_at: str, binds: dict[str, str]) -> None:
    """把一段的产物原子落进 bundle_dir,并写该段的 stage manifest。

    bundle 目录由第一段创建;后两段往里**追加**自己的文件。每段拒绝覆盖自己的
    产物 —— 同一 run_id 重跑某一段等于承认前一次是错的,那应该换 run_id。
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for name in list(files) + [_stage_manifest_path(bundle_dir, stage).name]:
        # governance-mutation: FUNNEL_DAG_STAGE_NO_OVERWRITE
        if os.path.lexists(bundle_dir / name):
            raise FunnelError(f"stage {stage} 产物已存在,拒绝覆盖: {name}")
    staging = Path(tempfile.mkdtemp(prefix=f".stage_{stage}.", dir=bundle_dir))
    try:
        for name, payload in files.items():
            _atomic_write_json(staging / name, payload)
        manifest = {
            "schema": "ar.research_funnel_stage",
            "schema_version": SCHEMA_VERSION,
            "rule_version": RULE_VERSION,
            "stage": stage,
            "as_of": as_of,
            "run_id": run_id,
            "generated_at": generated_at,
            "binds": binds,
            "artifacts": {name: _sha256(staging / name) for name in files},
        }
        manifest["stage_hash"] = _hash({k: v for k, v in manifest.items() if k != "stage_hash"})
        _atomic_write_json(staging / _stage_manifest_path(bundle_dir, stage).name, manifest)
        for name in list(files) + [_stage_manifest_path(bundle_dir, stage).name]:
            os.replace(staging / name, bundle_dir / name)
        fd = os.open(bundle_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write_stage_receipt(public_v2: Path, stage: str, bundle_dir: Path, *,
                         as_of: str, run_id: str, generated_at: str) -> None:
    """往发布树写一份 ~300B 的 stage receipt。

    前两段的实物全在 untracked 观察区,夜链的通用产物契约看不到;这份 receipt 让
    契约能校"本轮绑定 + 新鲜度",finalize 再把三份 receipt 的 stage_hash 链起来核。
    receipt 只转述 stage manifest 的 hash,不携带任何研究内容。
    """
    manifest = _load_json(_stage_manifest_path(bundle_dir, stage))
    receipt = {
        "schema": "ar.research_funnel_stage_receipt",
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "as_of": as_of,
        "target_trade_date": as_of,
        "run_id": run_id,
        "generated_at": generated_at,
        "stage_hash": manifest["stage_hash"],
        "bundle_location": f"data_history/funnel/{as_of}/{run_id}",
        "disclaimer": DISCLAIMER,
    }
    _atomic_write_json(public_v2 / f"funnel_stage_{stage}.json", receipt)


def _read_stage(bundle_dir: Path, stage: str, *, as_of: str, run_id: str) -> tuple[dict, dict]:
    """读前段:stage manifest 存在、绑本轮 as_of/run_id、逐产物哈希一致。"""
    mp = _stage_manifest_path(bundle_dir, stage)
    if not mp.is_file():
        raise FunnelError(f"前段 {stage} 尚未完成(缺 {mp.name}),拒绝跳过")
    manifest = _load_json(mp)
    # governance-mutation: FUNNEL_DAG_STAGE_BINDING
    if manifest.get("as_of") != as_of or manifest.get("run_id") != run_id:
        raise FunnelError(
            f"前段 {stage} 属于另一轮: as_of={manifest.get('as_of')} run_id={manifest.get('run_id')}"
        )
    if manifest.get("stage_hash") != _hash({k: v for k, v in manifest.items() if k != "stage_hash"}):
        raise FunnelError(f"前段 {stage} 的 stage manifest 不自洽")
    payloads = {}
    for name, digest in manifest["artifacts"].items():
        path = bundle_dir / name
        if not path.is_file() or _sha256(path) != digest:
            raise FunnelError(f"前段 {stage} 的产物 {name} 缺失或已被改动")
        payloads[name] = _load_json(path)
    return manifest, payloads


def _context() -> tuple[str, str, Path, Path, Path]:
    target = _date8(_require_env("AR_TARGET_TRADE_DATE"))
    run_id = _require_env("AR_RUN_ID")
    output_root = observation_root(_require_env("AR_FUNNEL_OUTPUT_ROOT"))
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_dir = _bundle_dir(output_root, target, run_id)
    public_v2 = REPO_ROOT / "public" / "data" / "v2"
    return target, run_id, output_root, bundle_dir, public_v2


# ── 段 1:funnel_candidates(纯计算)────────────────────────────────────────

def run_candidates() -> int:
    target, run_id, _root, bundle_dir, public_v2 = _context()
    if os.path.lexists(bundle_dir):
        raise FunnelError(f"本轮漏斗 bundle 已存在,拒绝覆盖: {bundle_dir}")
    feature_db = Path(os.environ.get("AR_FEATURE_STORE_DB")
                      or REPO_ROOT / "data_history" / "feature_store.sqlite3")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    registry = _load_json(public_v2 / "security_registry.json")
    e1 = _load_json(public_v2 / "e1_event_layer.json")
    rotation = _load_json(public_v2 / "rotation_panel.json", optional=True)
    features = load_feature_snapshot(feature_db, target)
    has_semiconductor_scope = any(
        row.get("industry_key") == semiconductor_evidence.SEMICONDUCTOR_INDUSTRY_KEY
        and row.get("qualification", {}).get("u1_scan_eligible") is True
        for row in registry["rows"]
    )
    try:
        semiconductor_inputs = (
            semiconductor_evidence.build_snapshot(feature_db, registry, target)
            if has_semiconductor_scope else None
        )
    except semiconductor_evidence.SemiconductorInputError as exc:
        raise FunnelError(f"semiconductor positive inputs are invalid: {exc}") from exc
    taxonomy = _load_json(INDUSTRY_TAXONOMY_PATH) if has_semiconductor_scope else None
    scan = build_all_market_scan(
        registry=registry, e1_events=e1, features=features, rotation=rotation,
        macro_industry=None, semiconductor_inputs=semiconductor_inputs,
        industry_taxonomy=taxonomy, trade_date=target, generated_at=generated_at,
    )
    candidates = build_candidate_review(
        registry=registry, scan=scan, features=features, trade_date=target,
        generated_at=generated_at,
    )
    manifest = build_candidate_manifest(candidate_review=candidates, scan=scan, run_id=run_id)
    validate_candidate_manifest(manifest)
    _write_stage(
        bundle_dir, "candidates",
        {"all_market_scan.json": scan, "candidate_review.json": candidates,
         "candidate_manifest.json": manifest},
        as_of=target, run_id=run_id, generated_at=generated_at,
        binds={"candidate_manifest_hash": manifest["manifest_hash"]},
    )
    _write_stage_receipt(public_v2, "candidates", bundle_dir,
                         as_of=target, run_id=run_id, generated_at=generated_at)
    print(json.dumps({
        "step": "funnel_candidates", "target_trade_date": target, "run_id": run_id,
        "bundle": str(bundle_dir), "expected_candidates": manifest["expected_count"],
        "manifest_hash": manifest["manifest_hash"][:16],
    }, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


# ── 段 2:candidate_battery(唯一网络步)─────────────────────────────────────

def _blocked_row(tk: str, today: str, why: str) -> dict:
    """数据源整体不可用时的逐票 DATA_BLOCKED 行 —— 六维齐全,每维显式阻断。"""
    dims = {d: {"status": "DATA_BLOCKED", "err": why[:80]} for d in BATTERY_DIMENSIONS}
    return {
        "ts_code": tk, "checked_at": today, "dims": dims,
        "completeness": {"covered": 0, "of": 6, "missing": list(BATTERY_DIMENSIONS),
                         "verdict": "PARTIAL"},
    }


def _battery_provider() -> tuple[Callable[[str, str], dict] | None, str]:
    """返回 (单票电池函数, 不可用原因)。整体不可用 → (None, why),不抛。

    这一层把"数据源整体失败"从异常变成数据:token 缺失、tushare 不可导入、
    连接被拒,都不该让步骤崩掉 —— 该让每只候选拿到一行显式 DATA_BLOCKED。
    只有结构损坏(前段产物对不上)才是步骤失败,那在 run_battery 里由 _read_stage 抛。
    """
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        return None, "NO TUSHARE_TOKEN"
    try:
        import tushare as ts  # noqa: WPS433
        import full_battery  # noqa: WPS433
    except Exception as exc:  # 缺依赖 = 整体不可用
        return None, f"battery provider unavailable: {type(exc).__name__}"
    try:
        pro = ts.pro_api(token)
    except Exception as exc:
        return None, f"tushare pro_api failed: {type(exc).__name__}"

    def one(tk: str, today: str) -> dict:
        return _sanitize_row(full_battery.battery(pro, tk, today))

    return one, ""


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return value != value or value in (float("inf"), float("-inf"))
    if isinstance(value, dict):
        return any(_has_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_non_finite(v) for v in value)
    return False


def _sanitize_row(row: dict) -> dict:
    """真 API 会给出 NaN/Inf(亏损票 PE、停牌票量能)。JSON 写不进去,而且一维的
    NaN 不该让 105 只全部作废。含非有限值的维度整维降为显式 DATA_BLOCKED ——
    **不**静默改成 0 或 None:那会把"没算出来"伪装成"算出来是零"。
    """
    dims = row.get("dims")
    if not isinstance(dims, dict):
        return row
    for name in list(dims):
        if _has_non_finite(dims[name]):
            dims[name] = {"status": "DATA_BLOCKED",
                          "err": "non-finite value from provider (NaN/Inf), refused"}
    missing = [k for k, v in dims.items()
               if isinstance(v, dict) and v.get("status") in ("DATA_BLOCKED", "NOT_RUN")]
    row["completeness"] = {"covered": len(dims) - len(missing), "of": len(dims),
                           "missing": missing,
                           "verdict": "COMPLETE" if not missing else "PARTIAL"}
    return row


def run_battery() -> int:
    target, run_id, _root, bundle_dir, public_v2 = _context()
    _stage1, payloads = _read_stage(bundle_dir, "candidates", as_of=target, run_id=run_id)
    manifest = payloads["candidate_manifest.json"]
    validate_candidate_manifest(manifest)
    codes = list(manifest["ts_codes"])  # 数量与身份都从 manifest 读
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    provider, why = _battery_provider()
    results: list[dict] = []
    provider_state = "AVAILABLE"
    if provider is None:
        provider_state = f"UNAVAILABLE: {why}"
        results = [_blocked_row(tk, target, why) for tk in codes]
    else:
        for tk in codes:
            try:
                row = provider(tk, target)
            except Exception as exc:  # 单票整只失败也不许缺行
                row = _blocked_row(tk, target, f"battery raised {type(exc).__name__}")
            if row.get("ts_code") != tk:
                raise FunnelError(f"battery returned a row for {row.get('ts_code')} when asked for {tk}")
            results.append(row)

    battery = {
        "schema": BATTERY_U2_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "as_of": target,
        # 既有 U3 消费者(_battery_rows)按 target_trade_date/checked_at 校同日,同时给出
        "target_trade_date": target,
        "checked_at": target,
        "run_id": run_id,
        "generated_at": generated_at,
        "manifest_hash": manifest["manifest_hash"],
        "provider_state": provider_state,
        "results": results,
        "disclaimer": DISCLAIMER,
    }
    battery["rows_hash"] = _hash(results)
    coverage = validate_candidate_battery(battery, manifest)  # 自校验:集合相等 + 六维
    _write_stage(
        bundle_dir, "battery", {"candidate_battery.json": battery},
        as_of=target, run_id=run_id, generated_at=generated_at,
        binds={"candidate_manifest_hash": manifest["manifest_hash"],
               "battery_rows_hash": battery["rows_hash"]},
    )
    _write_stage_receipt(public_v2, "battery", bundle_dir,
                         as_of=target, run_id=run_id, generated_at=generated_at)
    print(json.dumps({
        "step": "candidate_battery", "target_trade_date": target, "run_id": run_id,
        "provider_state": provider_state, **coverage,
    }, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


# ── 段 3:funnel_finalize(纯计算)──────────────────────────────────────────

def _final_bundle_files() -> tuple[str, ...]:
    # governance-mutation: FUNNEL_DAG_FINAL_MANIFEST_EVIDENCE
    return BUNDLE_FILES + DAG_EVIDENCE_FILES


def run_finalize() -> int:
    target, run_id, output_root, bundle_dir, public_v2 = _context()
    keep = int(os.environ.get("AR_FUNNEL_RETENTION_DAYS") or DEFAULT_RETENTION_DAYS)
    _s1, p1 = _read_stage(bundle_dir, "candidates", as_of=target, run_id=run_id)
    _s2, p2 = _read_stage(bundle_dir, "battery", as_of=target, run_id=run_id)
    manifest = p1["candidate_manifest.json"]
    battery = p2["candidate_battery.json"]
    validate_candidate_manifest(manifest)
    # 发布树里的两份 receipt 必须与观察区实物的 stage_hash 一致 —— 否则本轮 health
    # 会给一对"看起来是本轮、实际是别轮"的前段背书
    for stage, stage_manifest in (("candidates", _s1), ("battery", _s2)):
        receipt = _load_json(public_v2 / f"funnel_stage_{stage}.json")
        # governance-mutation: FUNNEL_DAG_RECEIPT_CHAIN
        if (receipt.get("run_id") != run_id or receipt.get("as_of") != target
                or receipt.get("stage_hash") != stage_manifest["stage_hash"]):
            raise FunnelError(f"发布树 receipt funnel_stage_{stage}.json 与观察区实物不符")
    # governance-mutation: FUNNEL_DAG_FINALIZE_COVERAGE
    coverage = validate_candidate_battery(battery, manifest)
    scan, candidates = p1["all_market_scan.json"], p1["candidate_review.json"]
    if candidates.get("rows_hash") != manifest.get("candidate_rows_hash"):
        raise FunnelError("candidate_review 与 candidate_manifest 的 rows_hash 不符")

    registry = _load_json(public_v2 / "security_registry.json")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # U3/U4:电池来源是本轮 candidate_battery,不是 watchlist 那份 battery.json
    queue = build_deep_research_queue(
        candidate_review=candidates, battery=battery, selected_tickers=(),
        trade_date=target, generated_at=generated_at,
    )
    projected = advance_registry(
        registry=registry, scan=scan, candidate_review=candidates, battery=battery,
        deep_queue=queue, generated_at=generated_at,
    )
    _write_stage(
        bundle_dir, "finalize",
        {"deep_research_queue.json": queue, "security_registry_projected.json": projected},
        as_of=target, run_id=run_id, generated_at=generated_at,
        binds={"candidate_manifest_hash": manifest["manifest_hash"],
               "battery_rows_hash": battery["rows_hash"]},
    )
    # 顶层 bundle manifest:与 #269 的 read_bundle 契约兼容(四个核心文件 + 哈希)
    final_files = _final_bundle_files()
    core = {name: _sha256(bundle_dir / name) for name in final_files}
    top = {
        "schema": "ar.research_funnel_bundle", "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION, "as_of": target, "run_id": run_id,
        "generated_at": generated_at,
        "artifacts": core, "dag": {
            "stages": ["candidates", "battery", "finalize"],
            "candidate_manifest_hash": manifest["manifest_hash"],
            "battery_rows_hash": battery["rows_hash"],
        },
    }
    top["bundle_hash"] = _hash(core)
    if os.path.lexists(bundle_dir / "manifest.json"):
        raise FunnelError("bundle manifest 已存在,拒绝覆盖")
    _atomic_write_json(bundle_dir / "manifest.json", top)

    health = build_health(target=target, run_id=run_id, bundle_dir=bundle_dir,
                          registry=registry, generated_at=generated_at)
    health["battery_coverage"] = dict(coverage, provider_state=battery["provider_state"])
    previously = published_bundle_date(public_v2)
    protected = {target} | ({previously} if previously else set())
    pruned = prune_observation_area(output_root, keep, protect=protected)
    health["retention"] = dict(pruned, keep_days=keep, protected_dates=sorted(protected))
    _atomic_write_json(public_v2 / "funnel_health.json", health)
    print(json.dumps({
        "step": "funnel_finalize", "target_trade_date": target, "run_id": run_id,
        "status": health["status"], "counts": health["counts"],
        "battery_coverage": health["battery_coverage"],
    }, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


STAGES = {"candidates": run_candidates, "battery": run_battery, "finalize": run_finalize}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in STAGES:
        print(f"usage: funnel_dag.py {{{'|'.join(STAGES)}}}")
        return 2
    try:
        return STAGES[args[0]]()
    except (FunnelError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
