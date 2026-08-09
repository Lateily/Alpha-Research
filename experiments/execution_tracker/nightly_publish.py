#!/usr/bin/env python3
"""Crash-consistent staging and publication for nightly-v4."""
from __future__ import annotations

import hashlib
import json
import os
import shutil


def _fsync_parent(path):
    fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


ET_FILES = {
    "paper_signal_log.json",
    "paper_signal_log.json.quarantine.json",
    "event_ledger.jsonl",
    "event_ledger.jsonl.anchor.json",
    "run_target.json",
    "rotation_panel.json",
    "momentum_prefilter.json",
    "rotation_stats.json",
    "rotation_validation.json",
    "rotation_history.json",
    "lead_precursor.json",
    "overnight_anchor.json",
    "court_wakeup.json",
    "watch_dynamic.json",
    "position_review.json",
    "court_10d.json",
    "red_flags.json",
    "battery.json",
    "promotion_queue.json",
}
ET_DIRS = ("samples", "reports")
PROTECTED_DIRS = ("model_fund",)

# model_fund 是**资金账本**,夜链默认不得改写它 —— 这条守卫要留。
# 但 NAV 每日结算是一次正当追加,所以把守卫从"逐字节不变"升级为 append-only 语义:
#   · 下列文件允许**只追加**:既有元素必须逐字节不变,新增元素受各自规则约束
#   · 其余受保护文件仍要求逐字节不变
#   · fund.json 只允许 cash 变,且必须有对应的成交/退出事件解释它
# append-only **只保证「不改旧的」,不保证「新增的不是旧日期」** ——
# 这两个账本都有 date 键,却曾用 date_key=None,于是可以往回追加一条上个月的记录:
# 既有行逐字节未变、条数只增,守卫全过,而账本被塞进了一条伪造的历史。
# 故:凡带日期的追加型账本,新增行的日期都必须 == 本轮 target(不早不晚)。
# one_per_target 区别在于「每日只许一行」(NAV)还是「一日可多行」(决策/影子盘)。
APPEND_ONLY_PROTECTED = {
    "nav_history.json":  {"date_key": "date", "one_per_target": True},
    "decision_log.json": {"date_key": "date", "one_per_target": False},
    "human_shadow.json": {"date_key": "date", "one_per_target": False},
}
# 订单不是纯 append-only:pending→filled→closed 是**原地状态迁移**,不是追加。
# 但迁移必须单向、且已成交的价格/数量不得改写 —— 否则改一个 fill_price 就能
# 重写历史成本。允许的迁移与不可变字段在此写死。
# 状态清单必须**穷举真实账本里出现过的全部状态**,否则连"没变化"都会被判非法 ——
# 初版漏了 cancelled(未成交撤单,真实存在 2 笔),于是 cancelled→cancelled 被拒。
# 漏一个状态,守卫就从"防篡改"变成"拦正常运行"。
ORDER_TRANSITIONS = {
    None:        {"pending", "filled", "closed", "cancelled"},
    "pending":   {"pending", "filled", "closed", "cancelled"},
    "filled":    {"filled", "closed"},
    "closed":    {"closed"},                   # 已了结不可复活
    "cancelled": {"cancelled"},                # 已撤单不可复活
}
ORDER_IMMUTABLE_ONCE_SET = ("ticker", "shares", "fill_price", "fill_date",
                            "exit_price", "exit_date", "registered_at")
FUND_MUTABLE_FIELDS = {"cash"}
# 资金账本**受保护但可发布**:先过 append-only + 现金对账,通过了才随本轮原子发布。
# 初版只把它列进 PROTECTED_DIRS(只校验、不发布)—— 于是 fund_daily_mark 在 staging
# 里算出的正确 NAV(1,009,466 定盘价)永远回不到 live,账本停在 0731,
# 而夜链却报 COMPLETE+published=true。"校验过了"不等于"发布了"。
PUBLISHABLE_PROTECTED = ("model_fund",)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_parent(path)


def atomic_copy(src, dst):
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    tmp = dst + ".publish.tmp"
    shutil.copy2(src, tmp)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, dst)
    _fsync_parent(dst)


def atomic_remove(path):
    if not os.path.exists(path):
        return False
    os.remove(path)
    _fsync_parent(path)
    return True


def _tree_hashes(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith((".lock", ".tmp", ".pyc")):
                continue
            path = os.path.join(base, name)
            out[os.path.relpath(path, root)] = sha256_file(path)
    return out


def prepare_stage(live_et, live_repo, run_dir):
    """Copy runtime state and code into an isolated repository-shaped staging tree."""
    stage_repo = os.path.join(run_dir, "staging", "repo")
    stage_et = os.path.join(stage_repo, "experiments", "execution_tracker")
    stage_research = os.path.join(stage_repo, "experiments", "research_funnel")
    stage_macro = os.path.join(stage_repo, "experiments", "macro_os")
    stage_public = os.path.join(stage_repo, "public", "data", "v2")
    if os.path.exists(stage_repo):
        shutil.rmtree(stage_repo)
    os.makedirs(os.path.dirname(stage_et), exist_ok=True)
    shutil.copytree(
        live_et,
        stage_et,
        ignore=shutil.ignore_patterns(
            "runs", "__pycache__", "*.pyc", "*.lock", "*.tmp",
            "run_state.json", "nightly.lock", "publication_state.json",
        ),
    )
    live_research = os.path.join(live_repo, "experiments", "research_funnel")
    if not os.path.isdir(live_research):
        raise RuntimeError(f"research_funnel source missing: {live_research}")
    shutil.copytree(
        live_research,
        stage_research,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.lock", "*.tmp"),
    )
    live_macro = os.path.join(live_repo, "experiments", "macro_os")
    if not os.path.isdir(live_macro):
        raise RuntimeError(f"macro_os source missing: {live_macro}")
    shutil.copytree(
        live_macro,
        stage_macro,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.lock", "*.tmp"),
    )
    live_public = os.path.join(live_repo, "public", "data", "v2")
    if os.path.isdir(live_public):
        shutil.copytree(live_public, stage_public)
    else:
        os.makedirs(stage_public, exist_ok=True)
    snapshot = {
        "protected": {
            rel: _tree_hashes(os.path.join(stage_et, rel)) for rel in PROTECTED_DIRS
        },
        # append-only 校验需要**内容**快照,不能只留哈希 —— 哈希只能答"变没变",
        # 答不了"变的是不是一次合法追加"。
        "protected_content": {
            rel: _protected_content(os.path.join(stage_et, rel)) for rel in PROTECTED_DIRS
        },
    }
    atomic_json(os.path.join(run_dir, "staging_input.json"), snapshot)
    return {
        "repo": stage_repo,
        "et": stage_et,
        "research": stage_research,
        "macro": stage_macro,
        "public": stage_public,
    }


def _protected_content(root):
    """受保护目录的内容快照(仅 .json)。append-only 判定要看内容,哈希不够。"""
    out = {}
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                out[name] = json.load(fh)
        except Exception:
            out[name] = None          # 读不了就记 None,校验时按"必须逐字节不变"处理
    return out


def _order_key(o):
    stable_id = o.get("entry_id") or o.get("order_id") or o.get("id")
    if stable_id not in (None, ""):
        return f"id:{stable_id}"
    return "legacy:" + repr((o.get("ticker"), o.get("registered_at"), o.get("setup")))


def _index_orders(rows, label):
    indexed = {}
    duplicates = []
    for order in rows:
        key = _order_key(order)
        if key in indexed:
            duplicates.append(key)
        else:
            indexed[key] = order
    errors = [f"model_fund/orders.json: {label} 出现重复订单身份 {key}"
              for key in sorted(set(duplicates))]
    return indexed, errors


def _scan_unknown_order_status(root):
    """无条件扫描订单状态是否都已登记 —— 不依赖"本轮有没有变"。"""
    path = os.path.join(root, "orders.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            orders = json.load(fh)
    except Exception as e:
        return [f"model_fund/orders.json 不可解析: {e}"]
    if not isinstance(orders, list):
        return ["model_fund/orders.json: 期望 JSON 数组"]
    bad = sorted({str(o.get("status")) for o in orders
                  if isinstance(o, dict) and o.get("status") not in ORDER_TRANSITIONS})
    return [f"model_fund/orders.json: 出现未登记状态 {bad} —— "
            f"状态机需显式补齐,不得默默放行"] if bad else []


def _check_orders(before, after):
    """订单:允许单向状态推进 + 追加新单;禁止倒退、删除、改写已定值字段。"""
    if not isinstance(before, list) or not isinstance(after, list):
        return ["model_fund/orders.json: 期望 JSON 数组"]
    bmap, before_errors = _index_orders(before, "变更前")
    amap, after_errors = _index_orders(after, "变更后")
    errs = before_errors + after_errors
    if errs:
        return errs
    for k in bmap:
        if k not in amap:
            errs.append(f"model_fund/orders.json: 订单 {k} 消失,不许删除")
    for k, a in amap.items():
        b = bmap.get(k)
        if b is None:
            continue                                   # 新单:允许追加
        was, now = b.get("status"), a.get("status")
        if was not in ORDER_TRANSITIONS:
            errs.append(f"model_fund/orders.json: 订单 {k} 出现未登记状态 {was!r} —— "
                        f"状态机需显式补齐,不得默默放行")
        elif now not in ORDER_TRANSITIONS[was]:
            errs.append(f"model_fund/orders.json: 订单 {k} 状态 {was}→{now} 非法迁移")
        for f in ORDER_IMMUTABLE_ONCE_SET:
            if b.get(f) not in (None, "") and b.get(f) != a.get(f):
                errs.append(f"model_fund/orders.json: 订单 {k} 的 {f} 已定值却被改写"
                            f"({b.get(f)!r}→{a.get(f)!r})")
    return errs


def _check_append_only(name, before, after, target):
    """既有元素逐字节不变 + 新增元素合法。返回错误列表。"""
    rule = APPEND_ONLY_PROTECTED[name]
    if not isinstance(before, list) or not isinstance(after, list):
        return [f"model_fund/{name}: 期望 JSON 数组,拿到 {type(before).__name__}/{type(after).__name__}"]
    if len(after) < len(before):
        return [f"model_fund/{name}: 元素减少 {len(before)}→{len(after)},append-only 不允许删除"]
    for i, old in enumerate(before):
        if json.dumps(old, sort_keys=True, ensure_ascii=False) != \
           json.dumps(after[i], sort_keys=True, ensure_ascii=False):
            return [f"model_fund/{name}: 第 {i} 条既有记录被改写,append-only 只许追加"]
    errs = []
    added = after[len(before):]
    dk = rule.get("date_key")
    if dk:
        for row in added:
            got = str((row or {}).get(dk) or "")[:8]
            if target and got != target:
                errs.append(f"model_fund/{name}: 新增行 {dk}={got or '缺失'} ≠ 本轮 {target}")
        if rule.get("one_per_target") and target:
            target_rows = sum(
                1 for row in after
                if str((row or {}).get(dk) or "")[:8] == target
            )
            if target_rows > 1:
                errs.append(f"model_fund/{name}: 本轮日期 {target} 共 {target_rows} 行,"
                            "该文件每个交易日只许一行")
    return errs


def _cash_delta_from_orders(before_orders, after_orders):
    """按真实记账规则算出本轮应有的现金变动:
       pending→filled  : -shares*fill_price
       filled →closed  : +shares*exit_price
    返回 (期望变动, 无法解释的原因列表)。"""
    if not isinstance(before_orders, list) or not isinstance(after_orders, list):
        return 0.0, ["model_fund/orders.json 结构非预期或缺失,现金无法对账"]
    prev = {}
    for o in before_orders:
        prev[_order_key(o)] = o
    delta, why = 0.0, []
    for o in after_orders:
        key = _order_key(o)
        was = (prev.get(key) or {}).get("status")
        now = o.get("status")
        if was == now:
            continue
        try:
            if was in (None, "pending") and now in ("filled", "closed"):
                delta -= float(o["shares"]) * float(o["fill_price"])
            if now == "closed" and was in ("filled",):
                delta += float(o["shares"]) * float(o["exit_price"])
            if was in (None, "pending") and now == "closed":
                delta += float(o["shares"]) * float(o["exit_price"])
        except (KeyError, TypeError, ValueError) as e:
            why.append(f"model_fund/orders.json 订单 {key} 状态 {was}→{now} 缺少成交字段({e}),现金无法对账")
    return round(delta, 2), why


def _check_fund(before, after, before_orders, after_orders):
    """资金账本:只有 cash 可变,且变动必须能被订单状态迁移解释。

    只判"字段名是否在白名单"不够 —— 那样任意改现金都会放行,
    而无事件解释的现金变动正是这道守卫要拦的静默改写。"""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ["model_fund/fund.json: 结构非预期"]
    diff = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    illegal = diff - FUND_MUTABLE_FIELDS
    errs = []
    if illegal:
        errs.append(f"model_fund/fund.json: 只允许 {sorted(FUND_MUTABLE_FIELDS)} 变动,"
                    f"实际变了 {sorted(illegal)}")
    if "cash" in diff:
        try:
            actual = round(float(after.get("cash")) - float(before.get("cash")), 2)
        except (TypeError, ValueError):
            return errs + ["model_fund/fund.json: cash 非数值"]
        expected, why = _cash_delta_from_orders(before_orders, after_orders)
        errs.extend(why)
        if abs(actual - expected) > 1.0:            # ±1 元容差(四舍五入)
            errs.append(f"model_fund/fund.json: 现金变动 {actual:+.2f} 无成交事件解释"
                        f"(按订单状态迁移应为 {expected:+.2f})")
    return errs


def verify_protected_inputs(stage_et, run_dir, target=None):
    """资金账本守卫。默认逐字节不变;APPEND_ONLY_PROTECTED 内的文件按 append-only 判。

    升级理由:NAV 每日结算是**正当追加**,而原守卫拿整目录哈希比对,
    把这次合法写入判成了篡改(17/17 步全 OK 却发布失败)。
    拆守卫是错的答案 —— 它护的是资金账本;正确答案是让它看懂"什么算合法追加"。
    """
    path = os.path.join(run_dir, "staging_input.json")
    with open(path, encoding="utf-8") as fh:
        snap = json.load(fh)
    before_h = snap.get("protected") or {}
    before_c = snap.get("protected_content") or {}
    errors = []
    for rel in PROTECTED_DIRS:
        root = os.path.join(stage_et, rel)
        after_h = _tree_hashes(root)
        # 未登记状态是**结构性**问题,与本轮是否改动无关:文件没变也要扫,
        # 否则一个从未被处理过的状态能永远藏在账本里(哈希相同 ⇒ 整份跳过)。
        errors.extend(_scan_unknown_order_status(root))
        if after_h == before_h.get(rel, {}):
            continue                                   # 完全未动,其余校验跳过
        after_c = _protected_content(root)
        bmap, amap = before_c.get(rel) or {}, after_c
        changed = sorted(set(after_h) | set(before_h.get(rel, {})))
        for fname in changed:
            if before_h.get(rel, {}).get(fname) == after_h.get(fname):
                continue
            if fname == "orders.json":
                errors.extend(_check_orders(bmap.get(fname), amap.get(fname)))
            elif fname in APPEND_ONLY_PROTECTED:
                errors.extend(_check_append_only(fname, bmap.get(fname), amap.get(fname), target))
            elif fname == "fund.json":
                errors.extend(_check_fund(bmap.get(fname), amap.get(fname),
                                          bmap.get("orders.json"), amap.get("orders.json")))
            else:
                errors.append(f"受保护输入在 staging 被修改: {rel}/{fname}")
    return errors


def _allowed_stage_files(stage_et, stage_public):
    files = []
    for rel in sorted(ET_FILES):
        path = os.path.join(stage_et, rel)
        if os.path.isfile(path):
            files.append(("et", rel, path))
    for dirname in PUBLISHABLE_PROTECTED:
        root = os.path.join(stage_et, dirname)
        if not os.path.isdir(root):
            continue
        for base, _, names in os.walk(root):
            for name in sorted(names):
                if name.endswith(".json"):
                    path = os.path.join(base, name)
                    files.append(("et", os.path.relpath(path, stage_et), path))
    for dirname in ET_DIRS:
        root = os.path.join(stage_et, dirname)
        if not os.path.isdir(root):
            continue
        for base, _, names in os.walk(root):
            for name in sorted(names):
                if name.endswith(".json"):
                    path = os.path.join(base, name)
                    files.append(("et", os.path.relpath(path, stage_et), path))
    if os.path.isdir(stage_public):
        for base, _, names in os.walk(stage_public):
            for name in sorted(names):
                if name.endswith(".json") and name != "current_run.json":
                    path = os.path.join(base, name)
                    files.append(("public", os.path.relpath(path, stage_public), path))
    return files


def _destination(scope, rel, live_et, live_repo):
    if scope == "et":
        return os.path.join(live_et, rel)
    return os.path.join(live_repo, "public", "data", "v2", rel)


def build_publish_plan(run_id, target, stage, live_et, live_repo, run_dir):
    protected = verify_protected_inputs(stage["et"], run_dir, target=target)
    if protected:
        raise RuntimeError("; ".join(protected))
    backup_dir = os.path.join(run_dir, "publish_before")
    os.makedirs(backup_dir, exist_ok=True)
    entries = []
    for scope, rel, src in _allowed_stage_files(stage["et"], stage["public"]):
        dst = _destination(scope, rel, live_et, live_repo)
        source_hash = sha256_file(src)
        before_exists = os.path.isfile(dst)
        before_hash = sha256_file(dst) if before_exists else None
        if before_hash == source_hash:
            continue
        backup = None
        if before_exists:
            backup = os.path.join(backup_dir, scope, rel)
            atomic_copy(dst, backup)
        entries.append({
            "scope": scope,
            "rel": rel,
            "source": src,
            "source_hash": source_hash,
            "before_exists": before_exists,
            "before_hash": before_hash,
            "backup": backup,
        })
    markers = []
    publication_metadata = (
        ("public", os.path.join("runs", run_id, "manifest.json")),
        ("public", "current_run.json"),
        ("et", "current_run.json"),
    )
    for scope, rel in publication_metadata:
        dst = _destination(scope, rel, live_et, live_repo)
        before_exists = os.path.isfile(dst)
        backup = None
        if before_exists:
            backup = os.path.join(backup_dir, "markers", scope, rel)
            atomic_copy(dst, backup)
        markers.append({"scope": scope, "rel": rel,
                        "before_exists": before_exists, "backup": backup})
    plan = {
        "schema": "nightly_publish/v2",
        "run_id": run_id,
        "target_trade_date": target,
        "entries": entries,
        "markers": markers,
    }
    atomic_json(os.path.join(run_dir, "publish_plan.json"), plan)
    return plan


def rollback_plan(plan, live_et, live_repo):
    restored = 0
    for entry in reversed(plan.get("entries") or []):
        dst = _destination(entry["scope"], entry["rel"], live_et, live_repo)
        if entry.get("before_exists"):
            backup = entry.get("backup")
            if not backup or not os.path.isfile(backup):
                raise RuntimeError(f"发布回滚缺备份: {entry['scope']}:{entry['rel']}")
            atomic_copy(backup, dst)
        else:
            atomic_remove(dst)
        restored += 1
    for marker in reversed(plan.get("markers") or []):
        dst = _destination(marker["scope"], marker["rel"], live_et, live_repo)
        if marker.get("before_exists"):
            backup = marker.get("backup")
            if not backup or not os.path.isfile(backup):
                raise RuntimeError(f"发布回滚缺 marker 备份: {marker['scope']}:{marker['rel']}")
            atomic_copy(backup, dst)
        else:
            atomic_remove(dst)
        restored += 1
    return restored


def publish_stage(run_id, target, stage, live_et, live_repo, run_dir,
                  state_path, fail_after=None, fail_phase=None):
    """Publish staged files with a durable rollback journal and commit marker last."""
    plan = build_publish_plan(run_id, target, stage, live_et, live_repo, run_dir)
    state = {
        "schema": "nightly_publication_state/v2",
        "status": "PUBLISHING",
        "run_id": run_id,
        "target_trade_date": target,
        "plan": os.path.join(run_dir, "publish_plan.json"),
    }
    atomic_json(state_path, state)
    try:
        for index, entry in enumerate(plan["entries"], 1):
            dst = _destination(entry["scope"], entry["rel"], live_et, live_repo)
            atomic_copy(entry["source"], dst)
            if sha256_file(dst) != entry["source_hash"]:
                raise RuntimeError(f"发布后 hash 不符: {entry['scope']}:{entry['rel']}")
            if fail_after is not None and index >= fail_after:
                raise RuntimeError(f"injected publish failure after {index}")

        manifest = {
            "schema": "nightly_publish_manifest/v2",
            "run_id": run_id,
            "target_trade_date": target,
            "artifacts": {
                f"{e['scope']}:{e['rel']}": e["source_hash"] for e in plan["entries"]
            },
        }
        # The durable manifest exists before either pointer.  Consumers first read
        # current_run.json, then verify this immutable manifest and its artifact
        # hashes; readers that ignore the pointer have no atomicity guarantee.
        run_manifest = os.path.join(run_dir, "manifest.json")
        atomic_json(run_manifest, manifest)
        public_manifest_rel = os.path.join("runs", run_id, "manifest.json")
        public_manifest = os.path.join(
            live_repo, "public", "data", "v2", public_manifest_rel)
        atomic_copy(run_manifest, public_manifest)
        if fail_phase == "after_manifest":
            raise RuntimeError("injected publish failure after manifest")

        pointer = dict(manifest)
        pointer.update({
            "schema": "nightly_current_run/v2",
            "manifest_path": public_manifest_rel,
            "manifest_sha256": sha256_file(run_manifest),
        })
        public_marker = os.path.join(live_repo, "public", "data", "v2", "current_run.json")
        atomic_json(public_marker, pointer)
        if fail_phase == "after_public_marker":
            raise RuntimeError("injected publish failure after public marker")
        atomic_json(os.path.join(live_et, "current_run.json"), pointer)
        state["status"] = "COMMITTED"
        state["artifact_count"] = len(plan["entries"])
        state["manifest"] = run_manifest
        atomic_json(state_path, state)
        return pointer
    except BaseException:
        restored = rollback_plan(plan, live_et, live_repo)
        state["status"] = "ROLLED_BACK"
        state["restored"] = restored
        atomic_json(state_path, state)
        raise


def recover_interrupted_publish(state_path, live_et, live_repo):
    if not os.path.exists(state_path):
        return None
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"publication_state 不可解析: {exc}") from exc
    if state.get("status") == "COMMITTED":
        return verify_committed_publication(state, live_et, live_repo)
    if state.get("status") != "PUBLISHING":
        return None
    plan_path = state.get("plan")
    if not plan_path or not os.path.isfile(plan_path):
        raise RuntimeError("未完成发布缺 publish_plan —— fail-closed")
    with open(plan_path, encoding="utf-8") as fh:
        plan = json.load(fh)
    restored = rollback_plan(plan, live_et, live_repo)
    state["status"] = "RECOVERED_ROLLBACK"
    state["restored"] = restored
    atomic_json(state_path, state)
    return {"run_id": state.get("run_id"), "restored": restored}


def verify_committed_publication(state, live_et, live_repo):
    """Verify the durable commit pointer and immutable public aliases.

    Transactional ET files may legitimately change between nightlies, so their
    hashes are audited by the WAL.  Public contract aliases must stay identical
    to the committed manifest until the next publication.
    """
    manifest_path = state.get("manifest")
    if not manifest_path or not os.path.isfile(manifest_path):
        raise RuntimeError("已提交发布缺 durable manifest —— fail-closed")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    manifest_hash = sha256_file(manifest_path)
    public_marker = os.path.join(live_repo, "public", "data", "v2", "current_run.json")
    et_marker = os.path.join(live_et, "current_run.json")
    try:
        with open(public_marker, encoding="utf-8") as fh:
            public_pointer = json.load(fh)
        with open(et_marker, encoding="utf-8") as fh:
            et_pointer = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"已提交发布 pointer 不可解析: {exc}") from exc
    if public_pointer != et_pointer:
        raise RuntimeError("public/ET current_run pointer 不一致 —— fail-closed")
    if public_pointer.get("run_id") != state.get("run_id"):
        raise RuntimeError("publication_state 与 current_run 的 run_id 不一致")
    if public_pointer.get("manifest_sha256") != manifest_hash:
        raise RuntimeError("current_run 指向的 manifest hash 不一致")
    expected_rel = os.path.join("runs", str(state.get("run_id") or ""), "manifest.json")
    if public_pointer.get("manifest_path") != expected_rel:
        raise RuntimeError("current_run manifest_path 非本轮固定相对路径")
    expected_public_manifest = os.path.join(
        live_repo, "public", "data", "v2", expected_rel)
    if (not os.path.isfile(expected_public_manifest)
            or sha256_file(expected_public_manifest) != manifest_hash):
        raise RuntimeError("公开 manifest 缺失或 hash 不符")
    if manifest.get("run_id") != state.get("run_id"):
        raise RuntimeError("durable manifest 与 publication_state 的 run_id 不一致")
    for key, expected_hash in (manifest.get("artifacts") or {}).items():
        scope, sep, rel = key.partition(":")
        if not sep or scope not in ("et", "public"):
            raise RuntimeError(f"manifest artifact key 非法: {key}")
        if scope != "public":
            continue
        path = _destination(scope, rel, live_et, live_repo)
        if not os.path.isfile(path) or sha256_file(path) != expected_hash:
            raise RuntimeError(f"已提交公开契约被改写或缺失: {rel}")
    return {
        "status": "COMMITTED_VERIFIED",
        "run_id": state.get("run_id"),
        "restored": 0,
    }
