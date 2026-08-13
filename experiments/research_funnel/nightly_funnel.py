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


def _bundle_dir(output_root: Path, target: str) -> Path:
    """把 bundle 目录钉死在 output_root/<target> 之下。

    target 来自环境变量,直接拼进路径再 rmtree 是删错目录的经典写法。这里同时挡
    三件事:根这一层被换成链接、子目录被换成链接、以及解析后跑出根之外。
    """
    if not (len(target) == 8 and target.isdigit()):
        raise FunnelError(f"target_trade_date 必须是 8 位日期: {target!r}")
    root = Path(os.path.abspath(output_root))
    if root.is_symlink():
        raise FunnelError(f"观察区根本身是符号链接,拒绝使用: {root}")
    candidate = root / target
    # governance-mutation: FUNNEL_NIGHTLY_BUNDLE_PATH_GUARD
    if candidate.is_symlink() or os.path.realpath(candidate) != os.path.join(
        os.path.realpath(root), target
    ):
        raise FunnelError(f"漏斗产物目录越界: {os.path.realpath(candidate)}")
    return candidate


def _reserve_stale_bundle(bundle_dir: Path, output_root: Path, target: str) -> Path | None:
    """产物契约要求本轮重写,所以同日残留必须先让位;但**不能直接删**。

    对抗复核打出来的:原来在 run_pipeline 之前就 rmtree,一旦本轮随后失败,上一轮
    已发布的 health 指向的 bundle 就没了 —— 清理把别人正在引用的东西删掉。改成
    先重命名挪开,成功后再删,失败则原样还原。后缀不是 8 位日期,retention 的
    扫描认不出它,不会被误清。
    """
    if not bundle_dir.exists() and not bundle_dir.is_symlink():
        return None
    if bundle_dir != _bundle_dir(output_root, target):
        raise FunnelError("拒绝移动未经校验的漏斗产物目录")
    if bundle_dir.is_file():
        # 该位置上的杂散文件会把这个日期永久卡死:目录建不出来,retention 又只认
        # 目录。就地移走,让它自愈而不是每晚重复失败。
        reserved = bundle_dir.with_name(f"{target}.superseded-file")
    else:
        reserved = bundle_dir.with_name(f"{target}.superseded")
    if reserved.exists() or reserved.is_symlink():
        raise FunnelError(
            f"备份位已被占用,拒绝覆盖: {reserved.name} —— 它是上一轮崩溃留下的"
            "最后一份有效证据,必须先由 recover_crashed_reserve 回滚"
        )
    # governance-mutation: FUNNEL_NIGHTLY_STALE_RESERVE
    os.replace(bundle_dir, reserved)
    return reserved


def recover_crashed_reserve(output_root: Path, target: str) -> bool:
    """上一轮在 reserve 与 drop 之间被 SIGKILL:`.superseded` 是最后一份有效证据。

    终审复核打出来的:原来无条件 rmtree 既有 `.superseded`,等于崩溃一次之后,
    下一轮把唯一的旧证据也删了。正确做法是**先回滚**:把备份还原回目标位置
    (连同丢弃崩溃那轮留下的半成品),再让本轮正常 reserve。
    """
    bundle_dir = _bundle_dir(output_root, target)
    recovered = False
    for suffix in (".superseded", ".superseded-file"):
        reserved = bundle_dir.with_name(f"{target}{suffix}")
        if not (reserved.exists() or reserved.is_symlink()):
            continue
        # governance-mutation: FUNNEL_NIGHTLY_CRASH_RECOVERY
        _restore_reserved(reserved, bundle_dir)
        recovered = True
    return recovered


def _drop_reserved(reserved: Path | None) -> bool:
    if reserved is None:
        return False
    if reserved.is_dir() and not reserved.is_symlink():
        shutil.rmtree(reserved)
    else:
        reserved.unlink()
    return True


def _restore_reserved(reserved: Path | None, bundle_dir: Path) -> None:
    if reserved is None:
        return
    if bundle_dir.exists() or bundle_dir.is_symlink():
        shutil.rmtree(bundle_dir, ignore_errors=True)
    os.replace(reserved, bundle_dir)


def prune_observation_area(
    output_root: Path, keep: int, protect: str | None = None
) -> list[str]:
    """观察区约 30MB/交易日,不清理一年就是 7-8GB。只保留最近 keep 个日期目录。

    `protect` 是本轮目标,永不删除。复审打出来的洞:重跑历史日期时,刚生成的那个
    目录按日期排序落在末尾,会被当成过期数据删掉,随后发布一份指向不存在 bundle
    的 health —— 清理把本轮成果清掉,是 retention 最典型的自伤。

    只认 8 位日期目录名,只删经 _bundle_dir 校验过的路径;认不出的东西一律不碰。
    """
    # governance-mutation: FUNNEL_NIGHTLY_RETENTION
    if keep < 1:
        raise FunnelError(f"观察区保留天数必须 >= 1: {keep}")
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
        if protect is not None and name == protect:
            continue
        shutil.rmtree(_bundle_dir(output_root, name))
        removed.append(name)
    return {"removed": removed, "skipped_not_a_directory": sorted(skipped)}


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
    generated_at: str, discarded_stale: bool,
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
        payloads=payloads, generated_at=generated_at, discarded_stale=discarded_stale,
    )


def compose_health(
    *, target: str, run_id: str, manifest: dict, measured: dict[str, str],
    payloads: dict, generated_at: str, discarded_stale: bool,
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
            "location": f"data_history/funnel/{target}",
            "published": False,
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
        "stale_bundle_discarded": discarded_stale,
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

    bundle_dir = _bundle_dir(output_root, target)
    # 上一轮若在 reserve 与 drop 之间崩溃,先把备份回滚,再正常 reserve
    recovered = recover_crashed_reserve(output_root, target)
    # 同日残留先挪开而不是直接删:本轮若失败,上一轮已发布的 health 指向的 bundle
    # 必须还在。成功才丢弃,失败原样还原。
    reserved = _reserve_stale_bundle(bundle_dir, output_root, target)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
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
            generated_at=generated_at, discarded_stale=reserved is not None,
        )
        health["crashed_reserve_recovered"] = recovered
        pruned = prune_observation_area(output_root, keep, protect=target)
        health["retention"] = dict(pruned, keep_days=keep)
        # health 是本步的完成戳,必须先落盘。终审复核打出来的:原来在 retention 与
        # 落盘**之前**就丢弃了备份 —— 后面任一步失败,旧证据已经没了,而新 bundle
        # 又没有完成戳,两头落空。备份只有在完成戳落地之后才可以丢。
        _atomic_write_json(public_v2 / "funnel_health.json", health)
    except BaseException:
        _restore_reserved(reserved, bundle_dir)
        raise
    # governance-mutation: FUNNEL_NIGHTLY_DROP_AFTER_STAMP
    _drop_reserved(reserved)
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
