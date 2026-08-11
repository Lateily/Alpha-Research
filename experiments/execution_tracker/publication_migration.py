#!/usr/bin/env python3
"""R-040 发布迁移账本 —— 已发布 manifest 的合法纠错通道。

## 存在的理由

发布快照用 manifest 哈希绑定产物。一旦产物在发布**之后**被合法修改
(例如经 PR 审批的数据迁移),manifest 与磁盘就会失配,
`nightly_publish.verify_committed_publication` 会 fail-closed 拒绝启动夜链。

这个 fail-closed 是**对的** —— 它正是发布快照该有的行为。缺的不是放宽,
而是一条**合法的纠错通道**:把"已发布的事实"与"后续经批准的修正"
用一条 append-only 记录连接起来,而不是原地洗写历史或重跑覆盖。

2026-08-07 起生产夜链停摆三天,根因即此:0806 发布后,PR #241/#242 的
合法修正落到磁盘与 ET durable manifest,但已发布副本仍是旧哈希。

## 铁律

- **append-only**:账本只追加。原 manifest 原文留档,永不删除、永不原地改写。
- **幂等**:migration_id = 记录内容哈希。重复执行零新增。
- **fail-closed**:任何前置校验不过即拒绝执行并保留现状,绝不"尽力而为"。
- 迁移**不创造事实**:每条 field_change 的 after 值必须与磁盘实际哈希相符,
  否则拒绝 —— 账本记录的是已经发生的合法修正,不是对未来的授权。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LEDGER = os.path.join(HERE, "publication_migrations.jsonl")
SCHEMA = "ar.publication_migration.v1"
SUPERSEDE_SCHEMA = "ar.manifest_supersede.v1"

ROOTS = {"et": HERE, "public": os.path.join(REPO, "public", "data", "v2")}


class MigrationError(RuntimeError):
    """前置校验失败。调用方必须保留现状,不得降级重试。"""


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _artifact_path(key: str) -> str:
    scope, sep, rel = key.partition(":")
    if not sep or scope not in ROOTS:
        raise MigrationError(f"artifact key 非法: {key}")
    return os.path.join(ROOTS[scope], rel)


def migration_id(record: dict) -> str:
    """内容哈希 —— 幂等的判重依据。

    刻意排除 executed_at:同一份迁移在不同时刻重放,必须算作同一条,
    否则"重复执行零新增"无法成立。
    """
    payload = {k: v for k, v in record.items()
               if k not in {"migration_id", "executed_at"}}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def read_ledger(path: str = LEDGER) -> list[dict]:
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # 损坏的账本不能当空账本 —— 那是 #217 踩过的坑
                raise MigrationError(f"迁移账本第 {lineno} 行损坏: {exc}") from exc
    return rows


def _manifest_paths(run_id: str) -> tuple[str, str]:
    rel = os.path.join("runs", run_id, "manifest.json")
    return os.path.join(HERE, rel), os.path.join(ROOTS["public"], rel)


def _current_run_paths() -> tuple[str, str]:
    return (os.path.join(HERE, "current_run.json"),
            os.path.join(ROOTS["public"], "current_run.json"))


def plan(run_id: str) -> dict:
    """扫描三方(已发布 manifest / ET manifest / 磁盘),产出待迁移清单。

    不修改任何东西。三方一致的产物一律不进 plan。
    """
    et_mp, pub_mp = _manifest_paths(run_id)
    for p in (et_mp, pub_mp):
        if not os.path.isfile(p):
            raise MigrationError(f"manifest 缺失,拒绝迁移: {p}")
    et = json.load(open(et_mp, encoding="utf-8"))
    pub = json.load(open(pub_mp, encoding="utf-8"))

    if set(et.get("artifacts") or {}) != set(pub.get("artifacts") or {}):
        raise MigrationError("两份 manifest 的 artifact 键集合不同 —— 超出迁移范围")

    changes, unresolved = [], []
    for key in sorted(et["artifacts"]):
        published, declared = pub["artifacts"][key], et["artifacts"][key]
        path = _artifact_path(key)
        actual = sha256_file(path) if os.path.isfile(path) else None
        if published == declared == actual:
            continue
        if actual is None:
            unresolved.append((key, "产物文件缺失"))
            continue
        # 磁盘是事实。迁移把两份 manifest 对齐到磁盘 —— 前提是磁盘变化有据可依,
        # 该依据由调用方通过 --evidence 显式提供,工具本身不臆断。
        changes.append({"artifact": key,
                        "sha256_published": published,
                        "sha256_declared": declared,
                        "sha256_actual": actual})
    return {"run_id": run_id, "changes": changes, "unresolved": unresolved,
            "total_artifacts": len(et["artifacts"])}


def build_record(run_id: str, target: str, changes: list[dict], *,
                 reason: str, authorized_by: str, approval_ref: str,
                 evidence: dict[str, str], manifest_sha_before: str) -> dict:
    field_changes = []
    for c in changes:
        ev = evidence.get(c["artifact"])
        if not ev:
            raise MigrationError(
                f"{c['artifact']} 缺 --evidence —— 迁移必须有据,拒绝执行")
        field_changes.append({
            "artifact": c["artifact"],
            "sha256_before": c["sha256_published"],
            "sha256_after": c["sha256_actual"],
            "evidence": ev,
            "verified_on_disk": True,
        })
    record = {
        "schema": SCHEMA,
        "run_id": run_id,
        "target_trade_date": target,
        "reason": reason,
        "authorized_by": authorized_by,
        "approval_ref": approval_ref,
        "superseded_manifest": {
            "path": os.path.join("runs", run_id, "manifest.json"),
            "sha256_before": manifest_sha_before,
        },
        "field_changes": field_changes,
        "executed_by": "publication_migration.py",
    }
    record["migration_id"] = migration_id(record)
    return record


def apply_migration(run_id: str, *, reason: str, authorized_by: str,
                    approval_ref: str, evidence: dict[str, str],
                    dry_run: bool = False, ledger_path: str = LEDGER) -> dict:
    p = plan(run_id)
    if p["unresolved"]:
        raise MigrationError(f"存在无法解释的分歧,拒绝执行: {p['unresolved']}")
    if not p["changes"]:
        return {"status": "NOOP", "detail": "三方已一致,无需迁移"}

    et_mp, pub_mp = _manifest_paths(run_id)
    pub_manifest_sha = sha256_file(pub_mp)
    et_manifest = json.load(open(et_mp, encoding="utf-8"))
    target = str(et_manifest.get("target_trade_date") or "")

    record = build_record(run_id, target, p["changes"], reason=reason,
                          authorized_by=authorized_by, approval_ref=approval_ref,
                          evidence=evidence, manifest_sha_before=pub_manifest_sha)

    # ── 幂等 = 收敛到目标状态,不是"见过就跳过" ──
    # 崩溃场景(账本已写、manifest 未落地)下若直接返回,系统会卡在不一致状态
    # 而工具宣称"已应用" —— 那是静默失败。正确语义:账本只追加一次,
    # 状态变更可安全重放,直到 verify 干净为止。
    already_recorded = any(row.get("migration_id") == record["migration_id"]
                           for row in read_ledger(ledger_path))

    if dry_run:
        return {"status": "DRY_RUN", "record": record, "plan": p,
                "already_recorded": already_recorded}

    # ── 1. 原 manifest 原文留档(append-only:目标存在则不覆盖)──
    orig_copy = f"{pub_mp}.orig-{pub_manifest_sha[:8]}"
    if not os.path.exists(orig_copy):
        shutil.copy2(pub_mp, orig_copy)

    # ── 2. superseded 标记 ──
    supersede = {
        "schema": SUPERSEDE_SCHEMA,
        "superseded_at": datetime.now(timezone.utc).isoformat(),
        "superseded_by_migration": record["migration_id"],
        "original_sha256": pub_manifest_sha,
        "original_preserved_at": os.path.basename(orig_copy),
    }
    for mp in (et_mp, pub_mp):
        with open(mp.replace("manifest.json", "manifest.superseded.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(supersede, fh, ensure_ascii=False, indent=1)
            fh.write("\n")

    # ── 3. 两份 manifest 对齐到磁盘事实 ──
    for c in p["changes"]:
        et_manifest["artifacts"][c["artifact"]] = c["sha256_actual"]
    blob = json.dumps(et_manifest, ensure_ascii=False, indent=1) + "\n"
    for mp in (et_mp, pub_mp):
        with open(mp, "w", encoding="utf-8") as fh:
            fh.write(blob)
    new_manifest_sha = sha256_file(pub_mp)
    if sha256_file(et_mp) != new_manifest_sha:
        raise MigrationError("两份 manifest 写后哈希不一致 —— fail-closed")

    # ── 4. current_run 重新绑定 ──
    for crp in _current_run_paths():
        if not os.path.isfile(crp):
            raise MigrationError(f"current_run 缺失: {crp}")
        cr = json.load(open(crp, encoding="utf-8"))
        for c in p["changes"]:
            if c["artifact"] in (cr.get("artifacts") or {}):
                cr["artifacts"][c["artifact"]] = c["sha256_actual"]
        cr["manifest_sha256"] = new_manifest_sha
        with open(crp, "w", encoding="utf-8") as fh:
            json.dump(cr, fh, ensure_ascii=False, indent=1)
            fh.write("\n")

    # ── 5. 追加账本(append-only;已记录则跳过追加,状态变更仍已完成)──
    if not already_recorded:
        record["executed_at"] = datetime.now(timezone.utc).isoformat()
        record["superseded_manifest"]["sha256_after"] = new_manifest_sha
        with open(ledger_path, "a", encoding="utf-8") as fh:
            fh.write(_canonical(record) + "\n")

    # ── 6. 复验 ──
    problems = verify(run_id)
    if problems:
        raise MigrationError(f"迁移后复验未通过: {problems}")
    return {"status": "RECONVERGED" if already_recorded else "APPLIED",
            "migration_id": record["migration_id"],
            "changed": [c["artifact"] for c in p["changes"]],
            "ledger_appended": not already_recorded,
            "manifest_sha256": new_manifest_sha}


def verify(run_id: str) -> list[str]:
    """迁移后一致性复验 —— 等价于 verify_committed_publication 的哈希绑定部分。"""
    problems: list[str] = []
    et_mp, pub_mp = _manifest_paths(run_id)
    if sha256_file(et_mp) != sha256_file(pub_mp):
        problems.append("ET 与 public 的 manifest 不一致")
    manifest_sha = sha256_file(pub_mp)
    et_cr, pub_cr = _current_run_paths()
    a = json.load(open(et_cr, encoding="utf-8"))
    b = json.load(open(pub_cr, encoding="utf-8"))
    if a != b:
        problems.append("ET 与 public 的 current_run pointer 不一致")
    if b.get("manifest_sha256") != manifest_sha:
        problems.append("current_run.manifest_sha256 与 manifest 实际不符")
    manifest = json.load(open(pub_mp, encoding="utf-8"))
    for key, expected in (manifest.get("artifacts") or {}).items():
        path = _artifact_path(key)
        if not os.path.isfile(path):
            problems.append(f"{key}: 产物缺失")
        elif sha256_file(path) != expected:
            problems.append(f"{key}: 磁盘哈希与 manifest 不符")
    return problems


def selftest() -> bool:
    """离线自测:零网络、临时目录、不碰生产。"""
    import tempfile
    global HERE, ROOTS, LEDGER
    saved = (HERE, dict(ROOTS), LEDGER)
    ok = []
    try:
        tmp = tempfile.mkdtemp()
        HERE = os.path.join(tmp, "et")
        ROOTS = {"et": HERE, "public": os.path.join(tmp, "pub")}
        LEDGER = os.path.join(HERE, "publication_migrations.jsonl")
        rid = "TESTRUN"
        for base in (HERE, ROOTS["public"]):
            os.makedirs(os.path.join(base, "runs", rid), exist_ok=True)
        art = os.path.join(HERE, "a.json")
        with open(art, "w") as fh:
            fh.write('{"v":2}')          # 磁盘 = 修正后
        actual = sha256_file(art)
        old = hashlib.sha256(b'{"v":1}').hexdigest()
        man = {"schema": "m", "run_id": rid, "target_trade_date": "20260806",
               "artifacts": {"et:a.json": old}}
        for base in (HERE, ROOTS["public"]):
            with open(os.path.join(base, "runs", rid, "manifest.json"), "w") as fh:
                json.dump(man, fh, ensure_ascii=False, indent=1); fh.write("\n")
        msha = sha256_file(os.path.join(ROOTS["public"], "runs", rid, "manifest.json"))
        cr = {"run_id": rid, "artifacts": {"et:a.json": old}, "manifest_sha256": msha}
        for base in (HERE, ROOTS["public"]):
            with open(os.path.join(base, "current_run.json"), "w") as fh:
                json.dump(cr, fh, ensure_ascii=False, indent=1); fh.write("\n")

        kw = dict(reason="t", authorized_by="Junyan", approval_ref="ref",
                  evidence={"et:a.json": "PR #X"}, ledger_path=LEDGER)
        ok.append(("plan 只报真分歧", len(plan(rid)["changes"]) == 1))

        # migration_id 必须与执行时刻无关 —— 否则"重复执行零新增"在真实场景失效。
        # 直接比对而非依赖时间流逝,才能钉住 executed_at 被混进哈希这种回归。
        rec_a = build_record(rid, "20260806", plan(rid)["changes"], reason="t",
                             authorized_by="Junyan", approval_ref="ref",
                             evidence={"et:a.json": "PR #X"}, manifest_sha_before="z")
        rec_b = dict(rec_a, executed_at="1999-01-01T00:00:00Z")
        ok.append(("migration_id 与 executed_at 无关",
                   migration_id(rec_a) == migration_id(rec_b)))

        pub_run_dir = os.path.join(ROOTS["public"], "runs", rid)
        pre_manifest_bytes = open(os.path.join(pub_run_dir, "manifest.json"), "rb").read()

        r1 = apply_migration(rid, **kw)
        ok.append(("首次执行 APPLIED", r1["status"] == "APPLIED"))
        ok.append(("迁移后复验干净", verify(rid) == []))

        orig_files = [f for f in os.listdir(pub_run_dir)
                      if f.startswith("manifest.json.orig-")]
        ok.append(("原 manifest 留档存在", len(orig_files) == 1))
        # 只检查"存在"抓不到无条件覆盖 —— 留档必须是迁移**前**的字节
        ok.append(("留档内容是迁移前原文", bool(orig_files) and
                   open(os.path.join(pub_run_dir, orig_files[0]), "rb").read()
                   == pre_manifest_bytes))
        ok.append(("superseded 标记存在", os.path.isfile(
            os.path.join(pub_run_dir, "manifest.superseded.json"))))

        n1 = len(read_ledger(LEDGER))
        r2 = apply_migration(rid, **kw)
        ok.append(("已迁移后重跑为 NOOP 且零新增",
                   r2["status"] == "NOOP" and len(read_ledger(LEDGER)) == n1))

        # 崩溃恢复场景:账本已写、manifest 未落地(步骤 3 与 5 之间中断)。
        # 此时 plan 仍有分歧,唯一挡住重复追加的就是 migration_id 幂等门。
        # 不构造这个场景,删掉幂等门也测不出来 —— 上一版正是如此。
        with open(os.path.join(pub_run_dir, "manifest.json"), "wb") as fh:
            fh.write(pre_manifest_bytes)
        with open(os.path.join(HERE, "runs", rid, "manifest.json"), "wb") as fh:
            fh.write(pre_manifest_bytes)
        n2 = len(read_ledger(LEDGER))
        r3 = apply_migration(rid, **kw)
        # 幂等的正确语义:账本零新增,但状态必须被修好(收敛),而不是宣称已应用后撒手
        ok.append(("崩溃恢复:账本零新增", len(read_ledger(LEDGER)) == n2))
        ok.append(("崩溃恢复:状态被收敛而非静默跳过",
                   r3["status"] == "RECONVERGED" and r3["ledger_appended"] is False
                   and verify(rid) == []))

        # verify() 是 --verify CLI 的承重逻辑,单独钉住它的三类判定。
        #
        # 注:apply_migration 末尾那次 verify 调用是**防御性冗余** —— plan() 已穷尽
        # 三方分歧,迁移后 verify 结构上不可能失败,故删掉那次调用不会让本自测翻红。
        # 这是等价变异,不是覆盖缺口;保留该调用是为了防止 plan/apply 将来解耦时
        # 出现无声漏网。此处如实标注,不假装它被钉住了。
        et_cr, pub_cr = _current_run_paths()
        saved_cr = open(pub_cr, "rb").read()
        bad = json.loads(saved_cr.decode())
        bad["manifest_sha256"] = "0" * 64
        with open(pub_cr, "w", encoding="utf-8") as fh:
            json.dump(bad, fh, ensure_ascii=False, indent=1)
        ok.append(("verify 抓到 current_run 指针失配",
                   any("manifest_sha256" in p for p in verify(rid))))
        with open(pub_cr, "wb") as fh:
            fh.write(saved_cr)

        saved_art = open(art, "rb").read()
        with open(art, "wb") as fh:
            fh.write(b'{"v":999}')                     # 磁盘被改,manifest 未跟
        ok.append(("verify 抓到产物哈希漂移",
                   any("磁盘哈希与 manifest 不符" in p for p in verify(rid))))
        os.remove(art)
        ok.append(("verify 抓到产物缺失",
                   any("产物缺失" in p for p in verify(rid))))
        with open(art, "wb") as fh:
            fh.write(saved_art)
        ok.append(("恢复后 verify 干净", verify(rid) == []))

        # 不变式:留档以原文哈希命名,任何重放都不得改动已存在的留档字节。
        # (无条件 shutil.copy2 属等价变异 —— 重放时 pub_mp 已是迁移后内容,
        #  哈希不同故写的是新文件名。这条断言把不变式本身钉死,而不是钉实现。)
        archives = {f: open(os.path.join(pub_run_dir, f), "rb").read()
                    for f in os.listdir(pub_run_dir) if ".orig-" in f}
        apply_migration(rid, **kw)
        after = {f: open(os.path.join(pub_run_dir, f), "rb").read()
                 for f in os.listdir(pub_run_dir) if ".orig-" in f}
        ok.append(("留档字节在重放后不变", all(
            after.get(f) == b for f, b in archives.items())))
        ok.append(("留档文件名 == 其内容哈希", all(
            f.rsplit("orig-", 1)[1] == hashlib.sha256(b).hexdigest()[:8]
            for f, b in after.items())))
        # 缺证据必须拒绝
        try:
            build_record(rid, "20260806", [{"artifact": "x", "sha256_published": "a",
                                            "sha256_declared": "b", "sha256_actual": "c"}],
                         reason="t", authorized_by="J", approval_ref="r",
                         evidence={}, manifest_sha_before="z")
            ok.append(("缺证据被拒", False))
        except MigrationError:
            ok.append(("缺证据被拒", True))
        # 损坏账本不得当空账本
        with open(LEDGER, "a") as fh:
            fh.write("{not json\n")
        try:
            read_ledger(LEDGER); ok.append(("损坏账本阻断", False))
        except MigrationError:
            ok.append(("损坏账本阻断", True))
    finally:
        HERE, ROOTS, LEDGER = saved[0], saved[1], saved[2]
    for name, passed in ok:
        print(("  ✓ " if passed else "  ✗ ") + name)
    print(f"publication_migration selftest: {sum(p for _, p in ok)}/{len(ok)}")
    return all(p for _, p in ok)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id")
    ap.add_argument("--reason", default="")
    ap.add_argument("--authorized-by", default="")
    ap.add_argument("--approval-ref", default="")
    ap.add_argument("--evidence", action="append", default=[],
                    metavar="ARTIFACT=REF", help="每个待迁移产物的依据,可重复")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.selftest:
            return 0 if selftest() else 1
        if not a.run_id:
            ap.error("--run-id required")
        if a.plan:
            print(json.dumps(plan(a.run_id), ensure_ascii=False, indent=1)); return 0
        if a.verify:
            problems = verify(a.run_id)
            print(json.dumps({"problems": problems}, ensure_ascii=False, indent=1))
            return 1 if problems else 0
        if a.dry_run or a.apply:
            ev = dict(kv.split("=", 1) for kv in a.evidence)
            res = apply_migration(a.run_id, reason=a.reason,
                                  authorized_by=a.authorized_by,
                                  approval_ref=a.approval_ref, evidence=ev,
                                  dry_run=a.dry_run)
            print(json.dumps(res, ensure_ascii=False, indent=1)); return 0
        ap.error("需指定 --plan / --dry-run / --apply / --verify / --selftest")
    except MigrationError as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
