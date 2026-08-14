#!/usr/bin/env python3
"""夜链隔离步骤:全市场研究漏斗 U1→U4(观察期)。

产物分工照抄 feature_store 的先例 —— 夜链所有引擎都在 staging 里跑,大体量数据
必须走持久路径穿透 staging 拆除,而**可验证产物**是发布树里的一个小 health 文件:

  · 完整 bundle(scan/candidates/queue/projected registry,约 30MB)
    → `AR_FUNNEL_OUTPUT_ROOT/<target>/<run_id>/`,即 live 的
      data_history/funnel/<target>/<run_id>/。
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
import re
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
    _hash,
    run_pipeline,
    validate_all_market_scan,
    validate_candidate_review,
    validate_deep_research_queue,
)
from security_registry import validate_registry  # noqa: E402

HEALTH_SCHEMA = "ar.research_funnel_health"
REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_FILES = (
    "all_market_scan.json",
    "candidate_review.json",
    "deep_research_queue.json",
    "security_registry_projected.json",
)
DEFAULT_RETENTION_DAYS = 14
_QUALITY_ORDER = ("COMPLETE", "PARTIAL", "DATA_BLOCKED")


def _require_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    # governance-mutation: FUNNEL_NIGHTLY_RUN_CONTEXT
    if not value:
        raise FunnelError(f"缺少必需环境变量 {name} —— 拒绝在无本轮上下文时产出漏斗产物")
    return value


def observation_root(raw: str) -> Path:
    """观察区根本身不得是符号链接。

    这条是复审打出来的洞:原来先 `output_root.resolve()` 再比对父目录,等于把
    逃逸**归一化掉**而不是检测出来 —— 根本身是 symlink 时,解析后的父目录当然
    等于解析后的根,校验恒真,而随后 rmtree 删的是仓库外的目录(已实测)。
    在 `data_history/funnel` 位置种一个链接,就能把"清理观察区"变成"删任意目录"。

    只挡根这一层,不挡祖先路径:macOS 的 /var → /private/var 之类是常态,把整条
    路径都禁掉会让工具在正常机器上跑不起来 —— 那种过严本身也是一种失效。
    搬迁观察区请直接改 AR_FUNNEL_OUTPUT_ROOT,环境变量本来就是搬迁机制。
    """
    root = Path(os.path.abspath(raw))
    # governance-mutation: FUNNEL_NIGHTLY_ROOT_SYMLINK
    if root.is_symlink():
        raise FunnelError(
            f"观察区根本身是符号链接,拒绝使用: {root} -> {os.path.realpath(root)}"
        )
    return root


def _date_dir(output_root: Path, target: str) -> Path:
    """把日期容器钉死在 output_root/<target> 之下。"""
    if not (len(target) == 8 and target.isdigit()):
        raise FunnelError(f"target_trade_date 必须是 8 位日期: {target!r}")
    root = Path(os.path.abspath(output_root))
    if root.is_symlink():
        raise FunnelError(f"观察区根本身是符号链接,拒绝使用: {root}")
    candidate = root / target
    # governance-mutation: FUNNEL_NIGHTLY_DATE_PATH_GUARD
    if candidate.is_symlink() or os.path.realpath(candidate) != os.path.join(
        os.path.realpath(root), target
    ):
        raise FunnelError(f"漏斗产物目录越界: {os.path.realpath(candidate)}")
    return candidate


def _bundle_dir(output_root: Path, target: str, run_id: str) -> Path:
    """每轮 bundle 都有不可覆盖的 run-scoped 地址。

    子步骤的 health 只写进 staging,真正公开提交点在外层 publish_stage。固定日期目录
    会迫使子步骤在外层提交前覆盖旧证据;一旦 publish_stage 失败,live health 仍是旧
    文件却已经找不到旧 bundle。运行级不可变路径从结构上消除这段回滚窗口。
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id or ""):
        raise FunnelError(f"run_id 不能安全地作为路径组件: {run_id!r}")
    date_dir = _date_dir(output_root, target)
    candidate = date_dir / run_id
    # governance-mutation: FUNNEL_NIGHTLY_IMMUTABLE_RUN_PATH
    if candidate.is_symlink() or os.path.realpath(candidate) != os.path.join(
        os.path.realpath(date_dir), run_id
    ):
        raise FunnelError(f"漏斗运行目录越界: {os.path.realpath(candidate)}")
    return candidate


def prune_observation_area(
    output_root: Path, keep: int, protect: str | set[str] | None = None
) -> dict[str, list[str]]:
    """观察区约 30MB/交易日,不清理一年就是 7-8GB。只保留最近 keep 个日期目录。

    `protect` 同时包含本轮目标和 staging 中既有 live health 引用的日期。后者必须
    保护到外层 publish_stage 成功之后;否则本轮尚未公开,清理却先删了线上仍在引用
    的证据。

    只认 8 位日期目录名,只删经 _date_dir 校验过的路径;认不出的东西一律不碰。
    """
    # governance-mutation: FUNNEL_NIGHTLY_RETENTION
    if keep < 1:
        raise FunnelError(f"观察区保留天数必须 >= 1: {keep}")
    protected = ({protect} if isinstance(protect, str) else set(protect or ()))
    dated, skipped = [], []
    for entry in output_root.iterdir():
        if not (len(entry.name) == 8 and entry.name.isdigit()):
            continue
        if entry.is_dir() and not entry.is_symlink():
            dated.append(entry.name)
        else:
            # 名字像日期但不是普通目录(杂散文件 / 符号链接):不碰,但要记下来,
            # 否则它会永远躺在观察区里而没人知道。
            skipped.append(entry.name)
    dated.sort(reverse=True)
    removed = []
    for name in dated[keep:]:
        # governance-mutation: FUNNEL_NIGHTLY_RETENTION_PROTECT
        if name in protected:
            continue
        shutil.rmtree(_date_dir(output_root, name))
        removed.append(name)
    return {"removed": removed, "skipped_not_a_directory": sorted(skipped)}


def published_bundle_date(public_v2: Path) -> str | None:
    """返回 staging 中现有 live health 正在引用的日期,供 retention 保护。

    staging 是 live 的副本。文件存在却无法证明其引用落在本观察区时必须拒绝清理,
    不能把损坏的旧指针当成"没有引用"。
    """
    path = public_v2 / "funnel_health.json"
    if not path.exists():
        return None
    data = _load(path)
    as_of = _date8(str(data.get("as_of") or ""))
    location = str((data.get("bundle") or {}).get("location") or "")
    prefix = f"data_history/funnel/{as_of}"
    if location != prefix and not location.startswith(prefix + "/"):
        raise FunnelError(f"既有 funnel health 的 bundle.location 非法: {location!r}")
    # governance-mutation: FUNNEL_NIGHTLY_PUBLISHED_RETENTION_PROTECT
    return as_of


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_count(payload: dict) -> int:
    rows = payload.get("rows")
    return len(rows) if isinstance(rows, list) else 0


def _worst(*qualities: str) -> str:
    seen = [q for q in qualities if q in _QUALITY_ORDER]
    if len(seen) != len(qualities):
        raise FunnelError(f"bundle 内部状态不在允许集合内: {qualities}")
    return max(seen, key=_QUALITY_ORDER.index)


def read_bundle(bundle_dir: Path, target: str) -> tuple[dict, dict[str, str], dict]:
    """把 bundle 读成"经过完整性校验的证据",而不是"几个恰好在手边的路径"。

    只从 bundle_dir 里按固定文件名读 —— 复审第二轮打出来的洞之一是 build_health
    从调用方传进来的 outputs 读 status/counts,那些路径可以指向 bundle 之外,
    等于给"用别处的数据描述这个 bundle"留了门。
    """
    manifest = _load(bundle_dir / "manifest.json")
    # governance-mutation: FUNNEL_NIGHTLY_HEALTH_EVIDENCE
    if str(manifest.get("as_of") or "") != target:
        raise FunnelError(
            f"bundle manifest 的 as_of={manifest.get('as_of')!r} 与本轮 target {target} 不符"
        )
    if manifest.get("schema") != "ar.research_funnel_bundle":
        raise FunnelError(f"bundle manifest schema 非法: {manifest.get('schema')!r}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise FunnelError(
            f"bundle manifest 版本={manifest.get('schema_version')!r} 与本工具 {SCHEMA_VERSION} 不符"
        )
    declared = manifest.get("artifacts")
    if not isinstance(declared, dict) or set(declared) != set(BUNDLE_FILES):
        raise FunnelError(f"bundle manifest 的产物清单不完整: {sorted(declared or {})}")
    measured = {name: _sha256(bundle_dir / name) for name in BUNDLE_FILES}
    drifted = sorted(n for n in BUNDLE_FILES if declared[n] != measured[n])
    if drifted:
        raise FunnelError(f"bundle 实物与 manifest 哈希不符: {drifted}")
    if manifest.get("bundle_hash") != _hash(declared):
        raise FunnelError("bundle_hash 与产物清单不自洽")
    payloads = {name: _load(bundle_dir / name) for name in BUNDLE_FILES}
    return manifest, measured, payloads


def validate_bundle_contracts(payloads: dict, registry: dict, scan_key: str) -> None:
    """跑四份既有契约 validator。

    复审第二轮:build_health 只核对了哈希,没让 bundle 过一遍 #267 合入的那四份
    契约 —— 哈希只证明"文件没被改",证明不了"内容仍然合规"。
    """
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_CONTRACTS
    # governance-mutation: FUNNEL_NIGHTLY_CONTRACT_REGISTRY
    validate_registry(payloads["security_registry_projected.json"])
    # governance-mutation: FUNNEL_NIGHTLY_CONTRACT_SCAN
    validate_all_market_scan(payloads[scan_key], registry)
    # governance-mutation: FUNNEL_NIGHTLY_CONTRACT_CANDIDATES
    validate_candidate_review(
        payloads["candidate_review.json"], registry, payloads[scan_key]
    )
    # governance-mutation: FUNNEL_NIGHTLY_CONTRACT_QUEUE
    validate_deep_research_queue(payloads["deep_research_queue.json"])


def build_health(
    *, target: str, run_id: str, bundle_dir: Path, registry: dict,
    generated_at: str,
) -> dict:
    """health 的每个字段都必须由 bundle 实物推导,不得是声称。

    这条是复审打出来的洞:原来 status 写死 COMPLETE、u4_queue_empty 写死 True、
    bundle_hash 原样抄 manifest —— 底层 DATA_BLOCKED、U4 非空、哈希伪造,health
    照样报 COMPLETE(已实测)。一份把自己的结论硬编码进去的 health 不是证据。
    """
    manifest, measured, payloads = read_bundle(bundle_dir, target)
    validate_bundle_contracts(payloads, registry, "all_market_scan.json")
    return compose_health(
        target=target, run_id=run_id, manifest=manifest, measured=measured,
        payloads=payloads, generated_at=generated_at,
    )


def compose_health(
    *, target: str, run_id: str, manifest: dict, measured: dict[str, str],
    payloads: dict, generated_at: str,
) -> dict:
    """把已校验的实物**转述**成 health。这一层只做推导,不做断言。"""
    scan = payloads["all_market_scan.json"]
    candidates = payloads["candidate_review.json"]
    queue = payloads["deep_research_queue.json"]
    queue_rows = _row_count(queue)
    status = _worst(
        str(scan.get("data_status") or scan.get("status") or "").upper(),
        str(candidates.get("status") or "").upper(),
    )
    return {
        "schema": HEALTH_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "rule_version": RULE_VERSION,
        # 由 bundle 内部状态取最差,而不是断言成功
        "status": status,
        "as_of": target,
        "target_trade_date": target,
        "run_id": run_id,
        "generated_at": generated_at,
        "bundle": {
            # 只登记相对位置:bundle 在 untracked 观察区,发布树不得依赖它的绝对路径
            # governance-mutation: FUNNEL_NIGHTLY_IMMUTABLE_HEALTH_LOCATION
            "location": f"data_history/funnel/{target}/{run_id}",
            "published": False,
            "immutable": True,
            "bundle_hash": manifest["bundle_hash"],
            "artifacts": measured,
        },
        "counts": {
            "scan_rows": _row_count(scan),
            "candidate_rows": _row_count(candidates),
            "deep_queue_rows": queue_rows,
        },
        "policy": {
            "nightly_mode": "OBSERVATION_ONLY_NOT_PUBLISHED",
            "isolated_step": True,
            "u4_selection_supplied": False,
            # 由实测行数推导:没有选票就该是 0 行,不是"我们说它是空的"
            "u4_queue_empty_by_construction": queue_rows == 0,
            "macro_input_wired": False,
        },
        # status 在观察期几乎恒为 PARTIAL(有几个通道结构性缺数),光一个 PARTIAL
        # 没有行动价值,还会把人训练成忽略它。把 scan 自己算出的逐通道缺数带上来,
        # 顶层看到 PARTIAL 时能直接知道是哪几条链缺,以及有没有变化。
        "degraded_channels": dict(
            (scan.get("coverage") or {}).get("blocked_by_channel") or {}
        ),
        "disclaimer": DISCLAIMER,
    }


def run(argv: list[str] | None = None) -> int:
    target = _date8(_require_env("AR_TARGET_TRADE_DATE"))
    run_id = _require_env("AR_RUN_ID")
    output_root = observation_root(_require_env("AR_FUNNEL_OUTPUT_ROOT"))
    output_root.mkdir(parents=True, exist_ok=True)
    keep = int(os.environ.get("AR_FUNNEL_RETENTION_DAYS") or DEFAULT_RETENTION_DAYS)

    # 输入读的是本轮 staging 树(本文件在 staging 副本里运行),产物写持久观察区。
    staged_root = REPO_ROOT
    feature_db = Path(
        os.environ.get("AR_FEATURE_STORE_DB")
        or staged_root / "data_history" / "feature_store.sqlite3"
    )
    public_v2 = staged_root / "public" / "data" / "v2"

    # governance-mutation: FUNNEL_NIGHTLY_RUN_SCOPED_OUTPUT
    bundle_dir = _bundle_dir(output_root, target, run_id)
    # governance-mutation: FUNNEL_NIGHTLY_OUTPUT_NO_OVERWRITE
    if os.path.lexists(bundle_dir):
        raise FunnelError(f"本轮漏斗 bundle 已存在,拒绝覆盖: {bundle_dir}")
    previously_published_date = published_bundle_date(public_v2)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_pipeline(
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
        target=target, run_id=run_id, bundle_dir=bundle_dir,
        registry=_load(public_v2 / "security_registry.json"),
        generated_at=generated_at,
    )
    protected_dates = {target}
    if previously_published_date:
        protected_dates.add(previously_published_date)
    pruned = prune_observation_area(output_root, keep, protect=protected_dates)
    health["retention"] = dict(
        pruned, keep_days=keep, protected_dates=sorted(protected_dates)
    )
    # health 仍只是 staging 完成戳。bundle 使用不可覆盖的 run-scoped 地址,所以即使
    # 外层 publish_stage 随后失败,live health 引用的旧证据也不会被本步改写。
    _atomic_write_json(public_v2 / "funnel_health.json", health)
    print(json.dumps({
        "step": "research_funnel",
        "target_trade_date": target,
        "bundle": str(bundle_dir),
        "status": health["status"],
        "counts": health["counts"],
        "degraded_channels": health["degraded_channels"],
        "retention": health["retention"],
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
