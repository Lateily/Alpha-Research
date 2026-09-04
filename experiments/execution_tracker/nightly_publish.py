#!/usr/bin/env python3
"""Crash-consistent staging and publication for nightly-v4."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil

# ── WO-OPS1 (2026-09-03): operator re-baseline for a lost durable manifest ──
# A COMMITTED publication whose durable manifest no longer exists cannot be
# verified and must not be silently accepted. The only compliant exit is an
# approved, ledgered re-baseline that marks it SUPERSEDED_BY_OPERATOR.
REBASELINE_LEDGER_NAME = "publication_rebaseline_events.jsonl"
SUPERSEDED_STATUS = "SUPERSEDED_BY_OPERATOR"
LOST_MANIFEST_EVENT_KIND = "PUBLICATION_MANIFEST_LOST"
LOST_MANIFEST_EVENT_SCHEMA = "publication_manifest_lost/v1"
APPROVAL_REF_RE = re.compile(r"session:[0-9A-Za-z][0-9A-Za-z._:-]{3,}")
APPROVAL_EVIDENCE_STRENGTH = "TRANSCRIPT_ONLY_NOT_CRYPTOGRAPHIC"
APPROVED_BY_IDENTITY_STATE = "SELF_REPORTED_NOT_AUTHENTICATED"
SAFE_RUN_ID_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,127}")
REBASELINE_APPROVAL_TEMPLATE = (
    "APPROVE publication_rebaseline run_id={run_id} "
    "durable_manifest=LOST_UNRECOVERABLE"
)
NIGHTLY_LOCK_NAME = "nightly.lock"
DISCLAIMER = "不是买卖指令；研究信号，human executes."


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


MACRO_RUNTIME_INPUTS = {"release_calendar.json", "market_features.json"}


def reset_staged_macro_outputs(stage_public):
    """Keep only immutable Macro inputs before the current staged run.

    A failed calibration module must not republish last night's derived panel as
    current evidence.  Existing live files remain untouched, but they are absent
    from this run's publication manifest unless M1-C regenerates them.
    """
    macro_root = os.path.join(stage_public, "macro")
    if not os.path.isdir(macro_root):
        return []
    removed = []
    for name in sorted(os.listdir(macro_root)):
        if name in MACRO_RUNTIME_INPUTS:
            continue
        path = os.path.join(macro_root, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        removed.append(name)
    return removed


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
    reset_staged_macro_outputs(stage_public)
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
    if state.get("status") == SUPERSEDED_STATUS:
        # governance-mutation: PUBLISH_SUPERSEDED_REQUIRES_LEDGERED_EVENT
        rec = _verify_superseded_event(
            state, _rebaseline_ledger_path(live_et), live_et, live_repo)
        return {"status": SUPERSEDED_STATUS, "run_id": state.get("run_id"),
                "restored": 0, "rebaseline_event": rec["hash"]}
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


# ────────────── WO-OPS1: lost durable manifest → operator re-baseline ──────────────
def _rebaseline_ledger_path(live_et):
    return os.path.join(live_et, REBASELINE_LEDGER_NAME)


def _canonical_state_path(live_et):
    return os.path.join(live_et, "publication_state.json")


def _same_path(left, right):
    return os.path.normcase(os.path.realpath(os.path.abspath(str(left)))) == os.path.normcase(
        os.path.realpath(os.path.abspath(str(right))))


def _require_rebaseline_layout(live_et, live_repo):
    """Bind the execution-tracker and public roots to one checkout."""
    repo_root = os.path.realpath(os.path.abspath(str(live_repo)))
    actual_et = os.path.realpath(os.path.abspath(str(live_et)))
    expected_et = os.path.realpath(os.path.join(
        repo_root, "experiments", "execution_tracker"))
    # governance-mutation: PUBLISH_REBASELINE_SINGLE_ROOT
    if actual_et != expected_et:
        raise RuntimeError(
            "live_et 必须由同一个 live_repo/experiments/execution_tracker 派生")
    return actual_et, repo_root


def required_rebaseline_approval(run_id):
    """Return the one closed-form approval decision accepted by this operation."""
    return REBASELINE_APPROVAL_TEMPLATE.format(run_id=run_id)


def _read_pointer(path):
    """Snapshot a commit pointer for the ledger; unreadable pointers are recorded, not hidden."""
    if not os.path.isfile(path):
        return {"present": False, "path": path}
    try:
        with open(path, encoding="utf-8") as fh:
            return {"present": True, "path": path, "value": json.load(fh)}
    except (OSError, json.JSONDecodeError) as exc:
        return {"present": True, "path": path, "error": str(exc)}


def _validate_rebaseline_approval(run_id, *, reason, approved_by, approval_ref,
                                  approval_verbatim, approval_channel, evidence_strength):
    """Bind the operator approval to THIS action and run_id, and refuse to dress a
    self-reported name up as an authenticated identity.

    Deliberately NOT checked: approved_by == "Junyan". String equality proves the
    string, not the authorization — approximating authority by equality is exactly
    the class of gate this platform keeps getting wrong (see R-043). What bears
    weight is the verbatim human text, which a reader can diff against the session
    transcript. The ledger therefore records approved_by as SELF_REPORTED, and the
    event self-declares that its evidence is a transcript, not cryptography.
    """
    # governance-mutation: PUBLISH_REBASELINE_REQUIRES_APPROVAL
    if not (str(reason or "").strip() and str(approved_by or "").strip()
            and str(approval_ref or "").strip()):
        raise RuntimeError("rebaseline 需要非空 reason / approved_by / approval_ref —— fail-closed")
    # governance-mutation: PUBLISH_REBASELINE_APPROVAL_CHANNEL
    if str(approval_channel or "") != "session_verbatim":
        raise RuntimeError("approval_channel 必须为 session_verbatim —— 自报身份不构成授权")
    verbatim = str(approval_verbatim or "").strip()
    required_verbatim = required_rebaseline_approval(run_id)
    # governance-mutation: PUBLISH_REBASELINE_APPROVAL_DECISION
    if verbatim != required_verbatim:
        raise RuntimeError(
            "approval_verbatim 必须逐字等于本次 run_id 的闭式 APPROVE 决策 —— "
            "否定、撤回、扩展或旧授权一律拒绝")
    if not APPROVAL_REF_RE.fullmatch(str(approval_ref or "")):
        raise RuntimeError("approval_ref 必须是非空 session: 锚点 —— fail-closed")
    # governance-mutation: PUBLISH_REBASELINE_APPROVAL_EVIDENCE_STRENGTH
    if str(evidence_strength or "") != APPROVAL_EVIDENCE_STRENGTH:
        raise RuntimeError(
            f"approval 必须自声明 evidence_strength={APPROVAL_EVIDENCE_STRENGTH} "
            "—— 账本不得暗示它不具备的证明强度")
    return {
        "reason": str(reason).strip(),
        "approved_by": str(approved_by).strip(),
        "approved_by_identity_state": APPROVED_BY_IDENTITY_STATE,
        "approval_ref": str(approval_ref).strip(),
        "approval_channel": "session_verbatim",
        "approval_verbatim": verbatim,
        "evidence_strength": APPROVAL_EVIDENCE_STRENGTH,
    }


@contextlib.contextmanager
def _nightly_exclusive(live_et):
    """Hold the SAME lock the nightly chain uses, so a re-baseline can never
    interleave with a publish nor with a second operator."""
    import fcntl
    lock_path = os.path.join(live_et, NIGHTLY_LOCK_NAME)
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)) or ".", exist_ok=True)
    with open(lock_path, "w") as lf:
        try:
            # governance-mutation: PUBLISH_REBASELINE_TAKES_NIGHTLY_LOCK
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "夜链锁被持有(nightly.lock)—— 拒绝与发布或另一次 rebaseline 并发") from exc
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _require_consistent_pointers(live_et, live_repo, state):
    """A lost manifest is the ONLY corruption this operation may absorb.

    Both commit pointers must be present, parseable, byte-identical to each other,
    and agree with publication_state on run_id and manifest identity. Anything else
    is a wider publication corruption that must not be relabelled as one clean
    lost-manifest re-baseline.
    """
    if state.get("schema") != "nightly_publication_state/v2":
        raise RuntimeError("publication_state schema 非 nightly_publication_state/v2 —— fail-closed")
    run_id = str(state.get("run_id") or "")
    target = str(state.get("target_trade_date") or "")
    # governance-mutation: PUBLISH_REBASELINE_SAFE_RUN_ID
    if SAFE_RUN_ID_RE.fullmatch(run_id) is None:
        raise RuntimeError("publication_state run_id 形状非法 —— fail-closed")
    if re.fullmatch(r"[0-9]{8}", target) is None:
        raise RuntimeError("publication_state target_trade_date 非 8 位日期 —— fail-closed")
    expected_manifest = os.path.join(
        os.path.abspath(live_et), "runs", run_id, "manifest.json")
    # governance-mutation: PUBLISH_REBASELINE_STATE_MANIFEST_IDENTITY
    if not state.get("manifest") or not _same_path(state["manifest"], expected_manifest):
        raise RuntimeError("publication_state manifest 未绑定本轮 durable manifest —— fail-closed")
    if not isinstance(state.get("artifact_count"), int) or state["artifact_count"] < 0:
        raise RuntimeError("publication_state artifact_count 非非负整数 —— fail-closed")

    public_path = os.path.join(live_repo, "public", "data", "v2", "current_run.json")
    et_path = os.path.join(live_et, "current_run.json")
    public_pointer = _read_pointer(public_path)
    et_pointer = _read_pointer(et_path)
    for label, snap in (("public", public_pointer), ("execution_tracker", et_pointer)):
        if not snap.get("present"):
            raise RuntimeError(f"{label} current_run.json 缺失 —— 非单纯 manifest 丢失,fail-closed")
        if snap.get("error") or not isinstance(snap.get("value"), dict):
            raise RuntimeError(f"{label} current_run.json 不可解析 —— fail-closed")
    if public_pointer["value"] != et_pointer["value"]:
        raise RuntimeError("两个 current_run.json 指针内容不一致 —— 发布损坏范围超出本操作,fail-closed")
    value = public_pointer["value"]
    expected_fields = {
        "schema", "run_id", "target_trade_date", "manifest_sha256",
        "manifest_path", "artifacts",
    }
    # governance-mutation: PUBLISH_REBASELINE_POINTER_SCHEMA
    if set(value) != expected_fields or value.get("schema") != "nightly_current_run/v2":
        raise RuntimeError("current_run 字段集或 schema 非 nightly_current_run/v2 —— fail-closed")
    # governance-mutation: PUBLISH_REBASELINE_POINTERS_MUST_AGREE
    if str(value.get("run_id") or "") != run_id:
        raise RuntimeError("指针 run_id 与 publication_state 不一致 —— fail-closed")
    if value.get("target_trade_date") != target:
        raise RuntimeError("指针 target_trade_date 与 publication_state 不一致 —— fail-closed")
    pinned = str(value.get("manifest_sha256") or "")
    if re.fullmatch(r"[0-9a-f]{64}", pinned) is None:
        raise RuntimeError("指针 manifest_sha256 不是 64 位十六进制 —— fail-closed")
    expected_rel = os.path.join("runs", run_id, "manifest.json")
    # governance-mutation: PUBLISH_REBASELINE_POINTER_MANIFEST_PATH
    if value.get("manifest_path") != expected_rel:
        raise RuntimeError("指针 manifest_path 未绑定本轮固定相对路径 —— fail-closed")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, dict) or len(artifacts) != state["artifact_count"]:
        raise RuntimeError("current_run artifacts 与 publication_state artifact_count 不一致")
    for key, artifact_hash in artifacts.items():
        scope, sep, rel = str(key).partition(":")
        if (not sep or scope not in ("et", "public") or not rel
                or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/")
                or re.fullmatch(r"[0-9a-f]{64}", str(artifact_hash or "")) is None):
            raise RuntimeError(f"current_run artifact 绑定非法: {key!r}")
    return public_pointer, et_pointer, pinned


def _verified_rebaseline_events(ledger_path):
    """Read the dedicated WAL only after both R-015 integrity layers pass."""
    import event_ledger
    chain = event_ledger.verify(ledger_path)
    anchor = event_ledger.verify_anchor(ledger_path)
    # governance-mutation: PUBLISH_REBASELINE_WAL_CHAIN_AND_ANCHOR
    if not chain.get("ok") or not anchor.get("ok"):
        raise RuntimeError(
            "rebaseline 控制账本或锚点损坏 —— fail-closed: "
            f"chain={chain.get('errors')} anchor={anchor.get('errors')}")
    rows = []
    for raw in event_ledger._read_lines(ledger_path):
        row = json.loads(raw)
        if row.get("kind") != LOST_MANIFEST_EVENT_KIND:
            raise RuntimeError(
                f"rebaseline 专用 WAL 含外来事件 {row.get('kind')!r} —— fail-closed")
        rows.append(row)
    return rows


def _bootstrap_rebaseline_ledger(ledger_path):
    """Anchor the empty prefix so a crash between WAL replace and anchor is recoverable."""
    import event_ledger
    anchor_path = ledger_path + event_ledger.ANCHOR_SUFFIX
    if os.path.exists(ledger_path) and not os.path.isfile(ledger_path):
        raise RuntimeError("rebaseline 控制账本不是普通文件 —— fail-closed")
    if os.path.exists(anchor_path) and not os.path.exists(ledger_path):
        raise RuntimeError("rebaseline 锚点存在但账本缺失 —— fail-closed")
    if not os.path.exists(ledger_path):
        os.makedirs(os.path.dirname(os.path.abspath(ledger_path)), exist_ok=True)
        with open(ledger_path, "xb") as fh:
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_parent(ledger_path)
    if not os.path.exists(anchor_path):
        chain = event_ledger.verify(ledger_path)
        if not chain.get("ok") or chain.get("n") != 0:
            raise RuntimeError("非空 rebaseline 控制账本缺锚点 —— fail-closed")
        event_ledger.write_anchor(ledger_path, 0, None)


def _validate_ledgered_rebaseline(rec, live_et, live_repo, ledger_path):
    payload = rec.get("payload")
    expected_payload_fields = {
        "schema", "run_id", "missing_manifest", "pinned_manifest_sha256",
        "public_pointer", "et_pointer", "prior_state", "approval", "reason",
        "approved_by", "approval_ref", "ledger_path", "note",
    }
    if not isinstance(payload, dict) or set(payload) != expected_payload_fields:
        raise RuntimeError("rebaseline 事件 payload 字段集不合法 —— fail-closed")
    run_id = str(payload.get("run_id") or "")
    if (payload.get("schema") != LOST_MANIFEST_EVENT_SCHEMA
            or rec.get("id") != f"rebaseline:{run_id}"):
        raise RuntimeError("rebaseline 事件 schema/id 与 run_id 不一致 —— fail-closed")
    if not _same_path(payload.get("ledger_path"), ledger_path):
        raise RuntimeError("rebaseline 事件未绑定规范专用 WAL —— fail-closed")
    prior_state = payload.get("prior_state")
    if not isinstance(prior_state, dict) or prior_state.get("status") != "COMMITTED":
        raise RuntimeError("rebaseline 事件缺合法 COMMITTED prior_state —— fail-closed")
    public_pointer, et_pointer, pinned = _require_consistent_pointers(
        live_et, live_repo, prior_state)
    if (payload.get("public_pointer") != public_pointer
            or payload.get("et_pointer") != et_pointer
            or payload.get("pinned_manifest_sha256") != pinned
            or not _same_path(payload.get("missing_manifest"), prior_state.get("manifest"))):
        raise RuntimeError("rebaseline 事件与当前 pointer/prior_state 证据不一致 —— fail-closed")
    approval = payload.get("approval")
    if not isinstance(approval, dict):
        raise RuntimeError("rebaseline 事件缺 approval —— fail-closed")
    normalized = _validate_rebaseline_approval(
        run_id,
        reason=approval.get("reason"),
        approved_by=approval.get("approved_by"),
        approval_ref=approval.get("approval_ref"),
        approval_verbatim=approval.get("approval_verbatim"),
        approval_channel=approval.get("approval_channel"),
        evidence_strength=approval.get("evidence_strength"),
    )
    if (approval != normalized or payload.get("reason") != normalized["reason"]
            or payload.get("approved_by") != normalized["approved_by"]
            or payload.get("approval_ref") != normalized["approval_ref"]):
        raise RuntimeError("rebaseline 事件 approval 投影不一致 —— fail-closed")
    return prior_state, normalized


def _superseded_state(state, rec, ledger_path, approval):
    """The state projection is a pure function of the ledgered event, so a retry
    after a crash can rebuild it byte-identically without appending again."""
    new_state = dict(state)
    new_state.update({
        "status": SUPERSEDED_STATUS,
        "prior_status": "COMMITTED",
        "superseded_event_kind": LOST_MANIFEST_EVENT_KIND,
        "superseded_event_id": rec["id"],
        "superseded_event_hash": rec["hash"],
        "superseded_event_ledger": os.path.abspath(ledger_path),
        "superseded_at": rec["ts"],
        "approved_by": approval["approved_by"],
        "approved_by_identity_state": approval["approved_by_identity_state"],
        "approval_ref": approval["approval_ref"],
        "approval_evidence_strength": approval["evidence_strength"],
    })
    return new_state


def rebaseline_lost_manifest(state_path, live_et, live_repo, *, reason, approved_by,
                             approval_ref, approval_verbatim=None,
                             approval_channel="session_verbatim",
                             evidence_strength=APPROVAL_EVIDENCE_STRENGTH,
                             ledger_path=None, now=None):
    """Record a lost durable manifest in the append-only control ledger and mark the
    committed publication SUPERSEDED_BY_OPERATOR so the next nightly may publish anew.

    Never re-creates or edits the lost manifest, never touches public aliases or
    pointers, and never pretends the old publication is verifiable.

    Concurrency and crash safety
    ----------------------------
    The whole operation runs under the SAME nightly.lock the publish chain takes, and
    the (kind, id) pair is unique at the ledger layer inside its own flock — so two
    operators cannot both append a rebaseline for one run_id. The ledger append is the
    single commit point: the state file is a pure projection of the ledgered event
    (see `_superseded_state`), so a crash between append and state write converges on
    retry by rebuilding that projection instead of appending again.
    """
    import event_ledger
    live_et, live_repo = _require_rebaseline_layout(live_et, live_repo)
    canonical_state = _canonical_state_path(live_et)
    # governance-mutation: PUBLISH_REBASELINE_CANONICAL_STATE
    if not _same_path(state_path, canonical_state):
        raise RuntimeError("rebaseline state 必须是 live_et 下的规范 publication_state.json")
    canonical_ledger = _rebaseline_ledger_path(live_et)
    # governance-mutation: PUBLISH_REBASELINE_CANONICAL_LEDGER
    if ledger_path is not None and not _same_path(ledger_path, canonical_ledger):
        raise RuntimeError("rebaseline ledger 必须是 live_et 下的规范专用 WAL")
    state_path = canonical_state
    ledger_path = canonical_ledger
    if not os.path.exists(state_path):
        raise RuntimeError("publication_state 不存在 —— 无可再基线的发布")
    with _nightly_exclusive(live_et):
        try:
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"publication_state 不可解析: {exc}") from exc
        run_id = str(state.get("run_id") or "")
        if not run_id:
            raise RuntimeError("publication_state 缺 run_id —— fail-closed")
        rec_id = f"rebaseline:{run_id}"
        manifest_path = state.get("manifest")
        status = state.get("status")
        events = _verified_rebaseline_events(ledger_path)
        matching = [rec for rec in events
                    if rec.get("kind") == LOST_MANIFEST_EVENT_KIND
                    and rec.get("id") == rec_id]
        if len(matching) > 1:
            raise RuntimeError(f"rebaseline 专用 WAL 含重复事件 {rec_id} —— fail-closed")

        # ── crash recovery:账本已有本次事件 ⇒ 事务已提交,只补 state 投影 ──
        existing = matching[0] if matching else None
        if existing is not None:
            base_state, prior_approval = _validate_ledgered_rebaseline(
                existing, live_et, live_repo, ledger_path)
            expected_state = _superseded_state(
                base_state, existing, ledger_path, prior_approval)
            if status == SUPERSEDED_STATUS:
                if state == expected_state:
                    raise RuntimeError(
                        "publication_state 已为 SUPERSEDED_BY_OPERATOR —— 重复 rebaseline 被拒")
                raise RuntimeError(
                    "SUPERSEDED 状态不是已验证事件的确定性投影 —— fail-closed,需人工裁决")
            if status != "COMMITTED":
                raise RuntimeError(f"账本已有 {rec_id},但状态为 {status!r} —— fail-closed")
            # governance-mutation: PUBLISH_REBASELINE_CONVERGENCE_PRIOR_STATE
            if state != base_state:
                raise RuntimeError(
                    "当前 COMMITTED state 与账本冻结 prior_state 不一致 —— 非崩溃收敛,fail-closed")
            atomic_json(state_path, expected_state)
            return {"status": SUPERSEDED_STATUS, "run_id": run_id,
                    "event_hash": existing["hash"], "ledger": ledger_path,
                    "converged_from": "LEDGER_COMMITTED_STATE_MISSING"}

        if status == SUPERSEDED_STATUS:
            raise RuntimeError("publication_state 已为 SUPERSEDED_BY_OPERATOR —— 重复 rebaseline 被拒")
        if status != "COMMITTED":
            raise RuntimeError(f"rebaseline 仅适用于 COMMITTED 发布,当前状态 {status!r} —— 拒绝")
        if manifest_path and os.path.isfile(manifest_path):
            raise RuntimeError("durable manifest 仍存在 —— 无需 rebaseline,拒绝以免掩盖可验证发布")
        public_pointer, et_pointer, pinned = _require_consistent_pointers(
            live_et, live_repo, state)
        approval = _validate_rebaseline_approval(
            run_id, reason=reason, approved_by=approved_by, approval_ref=approval_ref,
            approval_verbatim=approval_verbatim, approval_channel=approval_channel,
            evidence_strength=evidence_strength)
        _bootstrap_rebaseline_ledger(ledger_path)
        payload = {
            "schema": LOST_MANIFEST_EVENT_SCHEMA,
            "run_id": run_id,
            "missing_manifest": manifest_path,
            "pinned_manifest_sha256": pinned,
            "public_pointer": public_pointer,
            "et_pointer": et_pointer,
            "prior_state": state,
            "approval": approval,
            "reason": approval["reason"],
            "approved_by": approval["approved_by"],
            "approval_ref": approval["approval_ref"],
            "ledger_path": os.path.abspath(ledger_path),
            "note": "operator re-baseline; the lost publication is recorded as unverifiable, not restored",
        }
        rec = event_ledger.append(LOST_MANIFEST_EVENT_KIND, rec_id, payload,
                                  path=ledger_path, now=now)
        atomic_json(state_path, _superseded_state(state, rec, ledger_path, approval))
        return {"status": SUPERSEDED_STATUS, "run_id": run_id,
                "event_hash": rec["hash"], "ledger": ledger_path}


def _verify_superseded_event(state, ledger_path, live_et, live_repo):
    """A SUPERSEDED state is honoured only when its ledgered loss event exists and binds."""
    import event_ledger
    rec_id = state.get("superseded_event_id")
    want_hash = state.get("superseded_event_hash")
    if not rec_id or not want_hash:
        raise RuntimeError("SUPERSEDED 状态缺账本事件绑定 —— fail-closed")
    # governance-mutation: PUBLISH_REBASELINE_LEDGER_IDENTITY_BOUND
    bound_ledger = state.get("superseded_event_ledger")
    if bound_ledger and not _same_path(bound_ledger, ledger_path):
        raise RuntimeError(
            "SUPERSEDED 状态绑定的账本路径与生产规范账本不符 —— fail-closed")
    rows = _verified_rebaseline_events(ledger_path)
    for rec in rows:
        if rec.get("kind") == LOST_MANIFEST_EVENT_KIND and rec.get("id") == rec_id:
            if rec.get("hash") != want_hash or event_ledger.record_hash(rec) != want_hash:
                raise RuntimeError("SUPERSEDED 状态绑定的事件 hash 不符 —— fail-closed")
            prior_state, approval = _validate_ledgered_rebaseline(
                rec, live_et, live_repo, ledger_path)
            if prior_state.get("run_id") != state.get("run_id"):
                raise RuntimeError("账本事件 run_id 与 publication_state 不一致 —— fail-closed")
            expected_state = _superseded_state(
                prior_state, rec, ledger_path, approval)
            # governance-mutation: PUBLISH_REBASELINE_STATE_PROJECTION
            if state != expected_state:
                raise RuntimeError("SUPERSEDED 状态不是账本事件的确定性投影 —— fail-closed")
            return rec
    raise RuntimeError("SUPERSEDED 状态缺账本事件 —— fail-closed")


def _cli(argv=None):
    import argparse
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(prog="nightly_publish.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rb = sub.add_parser(
        "rebaseline",
        help="record a lost durable manifest and supersede the committed publication",
    )
    rb.add_argument("--reason", required=True)
    rb.add_argument("--approved-by", required=True)
    rb.add_argument("--approval-ref", required=True)
    rb.add_argument(
        "--repo-root",
        default=os.path.abspath(os.path.join(here, "..", "..")),
        help="single repository root; execution_tracker is derived from this root",
    )
    rb.add_argument("--approval-verbatim", required=True,
                    help="逐字转录的人类授权原文(必须精确包含本次 run_id)")
    # --ledger 已移除:生产 recovery 固定读规范账本,允许 override 会造成
    # "rebaseline 成功但恢复永远找不到事件" 的静默停机(复审 MAJOR 1)。
    args = parser.parse_args(argv)
    if args.cmd == "rebaseline":
        live_repo = os.path.realpath(os.path.abspath(args.repo_root))
        live_et = os.path.join(live_repo, "experiments", "execution_tracker")
        state_path = _canonical_state_path(live_et)
        try:
            out = rebaseline_lost_manifest(
                state_path, live_et, live_repo, reason=args.reason,
                approved_by=args.approved_by, approval_ref=args.approval_ref,
                approval_verbatim=args.approval_verbatim,
            )
        except RuntimeError as exc:
            print(f"REFUSED: {exc}")
            print(DISCLAIMER)
            return 2
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        print(DISCLAIMER)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
