#!/usr/bin/env python3
"""夜链隔离步骤:全市场研究漏斗 U1→U4(观察期)。

产物分工照抄 feature_store 的先例 —— 夜链所有引擎都在 staging 里跑,大体量数据
必须走持久路径穿透 staging 拆除,而**可验证产物**是发布树里的一个小 health 文件:

  · 完整 bundle(scan/candidates/queue/projected registry,约 30MB)
    → `AR_FUNNEL_OUTPUT_ROOT/<target>/`,即 live 的 data_history/funnel/<target>/。
      该目录不入库(.gitignore 已排除 data_history/),也不在 nightly_publish 的采集
      范围内(它只收 stage_public 的 .json 与 samples/reports/model_fund)。
  · health 摘要(约 1KB)
    → 发布树 public/data/v2/funnel_health.json,携带 run_id 与 target_trade_date,
      由夜链的产物契约逐轮校验新鲜度与本轮绑定。

观察期内漏斗只需证明"每夜能跑出当日新鲜 bundle",不承担任何发布语义,也不产生
任何交易含义:

  · 不传 u4 选票文件 ⇒ U4 深研队列**结构性为空**(选票只能由 Junyan 显式给出)
  · 不传 macro 输入   ⇒ 本轮不消费宏观(宏观授权边界另行接线)

本步在夜链里被隔离:失败记 DATA_BLOCKED,不否决 NAV、账本与其余研究的发布。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from funnel_pipeline import (  # noqa: E402
    DISCLAIMER,
    RULE_VERSION,
    SCHEMA_VERSION,
    FunnelError,
    _atomic_write_json,
    _date8,
    run_pipeline,
)

HEALTH_SCHEMA = "ar.research_funnel_health"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _require_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    # governance-mutation: FUNNEL_NIGHTLY_RUN_CONTEXT
    if not value:
        raise FunnelError(f"缺少必需环境变量 {name} —— 拒绝在无本轮上下文时产出漏斗产物")
    return value


def _bundle_dir(output_root: Path, target: str) -> Path:
    """把 bundle 目录钉死在 output_root/<target> 之下。

    target 来自环境变量,直接拼进路径再 rmtree 是删错目录的经典写法。这里先解析
    再校验父目录与目录名,任一不符即拒绝,不做"尽力而为"的清理。
    """
    if not (len(target) == 8 and target.isdigit()):
        raise FunnelError(f"target_trade_date 必须是 8 位日期: {target!r}")
    resolved_root = output_root.resolve()
    candidate = (resolved_root / target).resolve()
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_PATH_GUARD
    if candidate.parent != resolved_root or candidate.name != target:
        raise FunnelError(f"漏斗产物目录越界: {candidate}")
    return candidate


def _discard_stale_bundle(bundle_dir: Path, output_root: Path, target: str) -> bool:
    """产物契约要求本轮重写,所以同日残留必须先清掉再重跑。

    只清 output_root/<target>,且路径已由 _bundle_dir 校验过;output_root 是
    untracked 的观察区,不碰任何入库或已发布的东西。
    """
    if not bundle_dir.exists():
        return False
    if bundle_dir != _bundle_dir(output_root, target):
        raise FunnelError("拒绝删除未经校验的漏斗产物目录")
    shutil.rmtree(bundle_dir)
    return True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_count(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def build_health(
    *, target: str, run_id: str, outputs: dict[str, Path], bundle_dir: Path,
    generated_at: str, discarded_stale: bool,
) -> dict:
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "schema": HEALTH_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        "status": "COMPLETE",
        "as_of": target,
        "target_trade_date": target,
        "run_id": run_id,
        "generated_at": generated_at,
        "bundle": {
            # 只登记相对位置:bundle 在 untracked 观察区,发布树不得依赖它的绝对路径
            "location": f"data_history/funnel/{target}",
            "published": False,
            "bundle_hash": manifest.get("bundle_hash"),
            "artifacts": {name: _sha256(bundle_dir / name) for name in sorted(
                p.name for p in outputs.values()
            )},
        },
        "counts": {
            "scan_rows": _row_count(outputs["scan"]),
            "candidate_rows": _row_count(outputs["candidates"]),
            "deep_queue_rows": _row_count(outputs["queue"]),
        },
        "policy": {
            "nightly_mode": "OBSERVATION_ONLY_NOT_PUBLISHED",
            "isolated_step": True,
            "u4_selection_supplied": False,
            "u4_queue_empty_by_construction": True,
            "macro_input_wired": False,
        },
        "stale_bundle_discarded": discarded_stale,
        "disclaimer": DISCLAIMER,
    }


def run(argv: list[str] | None = None) -> int:
    target = _date8(_require_env("AR_TARGET_TRADE_DATE"))
    run_id = _require_env("AR_RUN_ID")
    output_root = Path(_require_env("AR_FUNNEL_OUTPUT_ROOT"))
    output_root.mkdir(parents=True, exist_ok=True)

    # 输入读的是本轮 staging 树(本文件在 staging 副本里运行),产物写持久观察区。
    staged_root = REPO_ROOT
    feature_db = Path(
        os.environ.get("AR_FEATURE_STORE_DB")
        or staged_root / "data_history" / "feature_store.sqlite3"
    )
    public_v2 = staged_root / "public" / "data" / "v2"

    bundle_dir = _bundle_dir(output_root, target)
    discarded = _discard_stale_bundle(bundle_dir, output_root, target)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    outputs = run_pipeline(
        registry_path=public_v2 / "security_registry.json",
        e1_path=public_v2 / "e1_event_layer.json",
        feature_db=feature_db,
        output_dir=bundle_dir,
        trade_date=target,
        rotation_path=public_v2 / "rotation_panel.json",
        battery_path=public_v2 / "battery.json",
        # macro 输入与 u4 选票都不接:见模块 docstring
        macro_industry_path=None,
        selected_tickers=(),
        generated_at=generated_at,
    )
    health = build_health(
        target=target, run_id=run_id, outputs=outputs, bundle_dir=bundle_dir,
        generated_at=generated_at, discarded_stale=discarded,
    )
    # health 最后写:它是本步的完成戳。中途死掉 ⇒ 契约判"产物不存在" ⇒ fail-closed。
    _atomic_write_json(public_v2 / "funnel_health.json", health)
    print(json.dumps({
        "step": "research_funnel",
        "target_trade_date": target,
        "bundle": str(bundle_dir),
        "counts": health["counts"],
    }, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except (FunnelError, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
