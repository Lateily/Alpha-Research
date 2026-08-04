#!/usr/bin/env python3
"""R-014 注册 schema v2 —— C5 §6.2 与 R-015 并列的硬前置。

C5 的三条实质规则都依赖本模块提供的字段,而现账本 0/128 行拥有它们:
  §4.1 `outcome_first_bar_settled` 需要 `registered_trade_date`
  §4.3 证据 `as_of ≤ registered_at` 需要 `registered_at`
  §3.1 写入者允许清单        需要 `written_by`

**历史行一律只派生、不写入。** C5 §2.2:冻结输入的「缺失→值」属 P3 genesis,
而 P3 仅在 S0 合法(§3);历史行全部处于 S1/S2,回填即 rewrite,preflight 必须阻断。
因此 `registered_at_of()` 返回 (值, 来源),来源标明是字段还是派生,**从不落盘**。

**新登记走 `stamp_new_record()`**,三字段与信号同一次原子操作写入,
并向 R-015 事件账本追加一条 `register` 记录;账本写不进去 ⇒ 登记失败,
不允许产生没有审计轨迹的信号。

不是买卖指令;研究信号,human executes.
"""
import os, re, sys, json, hashlib, datetime, subprocess

SCHEMA_VERSION = "registry/v2"
LEDGER_FIELDS = ("registered_at", "registered_trade_date", "written_by")

# C5 §3.1:只有允许清单内的可执行文件可以写注册记录
ALLOWED_WRITERS = {
    "paper_tracker.py",          # 研究预注册
    "execution_tracker.py",      # 盘后官方样本
    "run_official_sample.py",
    "registry_selftest",         # 本模块自检
}

# 账本实测形态(128 行):
#   102× "YYYYMMDD close (official)"
#    19× "YYYYMMDD HH:MM"
#     1× "YYYYMMDD HH:MM (intraday, 定盘判分)"
_TS_DATE_RE = re.compile(r"^\s*(\d{8})\b")
_TS_TIME_RE = re.compile(r"^\s*\d{8}\s+(\d{2}):(\d{2})\b")


def parse_trade_date(timestamp):
    """从自由文本 timestamp 提取 YYYYMMDD。不可解析返回 None(fail-closed,
    调用方必须显式处理,不得当作今天)。"""
    m = _TS_DATE_RE.match(str(timestamp or ""))
    if not m:
        return None
    d = m.group(1)
    try:
        datetime.datetime.strptime(d, "%Y%m%d")
    except ValueError:
        return None
    return d


def parse_clock(timestamp):
    """提取 HH:MM;'close (official)' 一类无显式时钟的返回 None。
    C5 §4.3 的同日证据判定需要盘中时间戳,这里如实报告有没有。"""
    m = _TS_TIME_RE.match(str(timestamp or ""))
    return f"{m.group(1)}:{m.group(2)}" if m else None


def registered_trade_date(sig):
    """C5 §4.1 用。字段优先,其次由 timestamp 派生。返回 (值|None, 来源)。"""
    v = sig.get("registered_trade_date")
    if v:
        return str(v), "field"
    d = parse_trade_date(sig.get("timestamp"))
    return (d, "derived_from_timestamp") if d else (None, "unavailable")


def first_git_appearance(signal_id, ledger_path, repo=None):
    """C5 §4.3 过渡期锚点的另一半:该 signal_id 首次出现在 git 跟踪账本 blob 的 commit 日。
    取不到返回 None —— 调用方 fail-closed,不得当作"没有问题"。"""
    repo = repo or _repo_root(ledger_path)
    if repo is None:
        return None
    rel = os.path.relpath(os.path.realpath(ledger_path), os.path.realpath(repo))
    try:
        r = subprocess.run(["git", "-C", repo, "log", "--reverse", "--format=%H %cs",
                            "-S", signal_id, "--", rel],
                           capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().splitlines()[0].split()[1].replace("-", "")


def _repo_root(path):
    d = os.path.dirname(os.path.realpath(path))
    if not os.path.isdir(d):
        return None
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def registered_at_of(sig, ledger_path=None):
    """C5 §4.3 用。返回 {value, source, backdated, clock}。**绝不写盘。**

    过渡期锚点 = min(parse_trade_date(timestamp), 首次 git 出现日);
    二者相差 > 0 个交易日 ⇒ 标 backdated(该行不计入门槛计数)。
    理由:timestamp 是操作者自填的自由文本,往前填即可把自己的证据截止线推后;
    今天登记一条 timestamp 写成上月的信号是"合法 prospective P1",
    而 backfill 会立刻用已结算的 bar 算出它的收益 —— 伪造前瞻簇的最短路径。
    """
    out = {"value": None, "source": "unavailable", "backdated": None,
           "clock": parse_clock(sig.get("timestamp"))}
    v = sig.get("registered_at")
    if v:
        out.update(value=str(v), source="field")
    else:
        d = parse_trade_date(sig.get("timestamp"))
        if d:
            out.update(value=d, source="derived_from_timestamp")
    if out["value"] is None or not ledger_path or not sig.get("signal_id"):
        return out
    g = first_git_appearance(sig["signal_id"], ledger_path)
    if g is None:
        out["backdated"] = "UNKNOWN"          # 取不到 ⇒ 不判定,也不当作干净
        return out
    claimed = out["value"][:8]
    out["anchor_git_date"] = g
    # 风险方向是 claimed **早于** 首次入库 —— 今天登记却谎称上月,
    # 结果已经可见却算「前瞻」。初版写成 claimed > g,方向反了,抓不到这个攻击;
    # 且 anchor 取 min 会选中伪造值本身,等于替攻击者背书。
    out["backdated"] = claimed < g
    # 前瞻性锚点:不得早于它真正出现在 git 的那天
    out["prospective_from"] = max(claimed, g)
    # 证据准入锚点保持保守(取早者)—— 它限制的是「能引用哪些证据」,越早越严
    out["evidence_anchor"] = min(claimed, g)
    out["value"] = out["prospective_from"]
    return out


def written_by_stamp(script, version, run_id):
    """C5 §3.1 的写入者戳。script 必须在允许清单内。"""
    base = os.path.basename(str(script))
    if base not in ALLOWED_WRITERS:
        raise ValueError(f"写入者不在允许清单: {base} —— C5 §3.1 视为 rewrite")
    return {"script": base, "version": str(version), "run_id": str(run_id)}


def ledger_path_for(signal_log_path):
    """事件账本与信号账本同目录同级 —— 路径**跟随**而非全局常量。
    这样用临时 log 的测试自动用临时链,不会污染仓库里那条真链
    (初版用全局 _default_ledger_append 打补丁,paper_tracker 自检当场把
     committed 账本从 3 条写成 4 条,且第二次跑就撞 (register,id) 唯一性而失败)。"""
    return os.path.join(os.path.dirname(os.path.abspath(signal_log_path)), "event_ledger.jsonl")


def stamp_new_record(rec, *, registered_at, script, version, run_id):
    """给**新**登记记录打 schema v2 三字段,并向 R-015 事件账本追加 register 事件。

    拒绝:①registered_at 为空(不许本模块发明时间戳)②记录已有任一 schema v2 字段
    (那是既有记录,再写即 rewrite,C5 §2.2)③写入者不在允许清单
    **纯函数:只打戳,不碰任何账本。** 事务编排在 register_transaction()。
    (初版有 ledger_append=False 这个公开旁路,等于给调用方一个"跳过审计"的开关;
     已删除 —— 想不写账本的唯一合法方式是不走登记。)
    """
    if not str(registered_at or "").strip():
        raise ValueError("registered_at 必填 —— 本模块从不发明时间戳")
    present = [f for f in LEDGER_FIELDS if rec.get(f)]
    if present:
        raise ValueError(f"记录已有 schema v2 字段 {present} —— 再写即 rewrite(C5 §2.2)")
    d = parse_trade_date(registered_at)
    if d is None:
        raise ValueError(f"registered_at 不可解析为交易日: {registered_at!r} —— fail-closed")
    rec = dict(rec)
    rec["registered_at"] = str(registered_at)
    rec["registered_trade_date"] = d
    rec["written_by"] = written_by_stamp(script, version, run_id)
    rec["registry_schema"] = SCHEMA_VERSION
    return rec


# ────────────────────────── 三段式登记事务 ──────────────────────────
class LedgerCorrupt(Exception):
    """账本不可解析或状态自相矛盾。**绝不降级为空账本 / 绝不当作正常** ——
    降级会让历史信号静默消失,而下一次写入把空账本当事实落盘,损失不可逆。"""


def load_signal_log_strict(path):
    """读信号账本。不存在 ⇒ 空列表(合法首次);存在但不可解析 ⇒ 抛错停机。"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        raise LedgerCorrupt(f"{path} 不可解析 ({e}) —— fail-closed,不得当作空账本") from e
    rows = data if isinstance(data, list) else data.get("signals", data.get("log"))
    if rows is None or not isinstance(rows, list):
        raise LedgerCorrupt(f"{path} 结构非预期(既非列表也无 signals/log 键)—— fail-closed")
    return rows


def write_signal_log_atomic(path, rows):
    """临时文件 + fsync + os.replace。半程崩溃留下的是旧文件,不是截断的新文件。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def audit_ledger(path):
    """只读体检:统计三字段覆盖与可派生率。不写盘。"""
    rows = load_signal_log_strict(path)
    out = {"n": len(rows), "has_field": {f: 0 for f in LEDGER_FIELDS},
           "derivable_trade_date": 0, "unparseable_timestamp": []}
    for s in rows:
        for f in LEDGER_FIELDS:
            if s.get(f):
                out["has_field"][f] += 1
        d, _ = registered_trade_date(s)
        (out.__setitem__("derivable_trade_date", out["derivable_trade_date"] + 1)
         if d else out["unparseable_timestamp"].append(s.get("signal_id")))
    return out


def _el():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import event_ledger
    return event_ledger


def read_events(ledger_path):
    """读事件账本。链损坏 ⇒ 抛错停机(不得在坏链上继续做事务判定)。"""
    el = _el()
    st = el.verify(ledger_path)
    if not st["ok"]:
        raise LedgerCorrupt(f"事件链损坏,拒绝进行事务判定: {st['errors'][:2]}")
    return [json.loads(ln) for ln in el._read_lines(ledger_path)]


def transaction_id_for(signal_id, registered_at, run_id):
    """确定性 —— 同一次重试必然得到同一个 txn_id,幂等性才有依据。"""
    return hashlib.sha256(f"{signal_id}|{registered_at}|{run_id}".encode()).hexdigest()[:16]


def _txn_state(events):
    intents, commits, aborts = {}, set(), set()
    for e in events:
        k, i = e.get("kind"), e.get("id")
        if k == "register_intent":
            intents[i] = e.get("payload") or {}
        elif k == "register_commit":
            commits.add(i)
        elif k == "register_abort":
            aborts.add(i)
    return intents, commits, aborts


# 注册指纹:**默认冻结**。上一版用"冻结白名单",trigger_price / support /
# main_flow / forecast_claim / mechanism_chain 等研究输入全在名单外 —— 改了照样过校验。
# 白名单永远漏字段;现在反转:除下列**显式判分产物**外,一切字段(含未来新增)
# 默认冻结,改动即指纹变化即校验失败。判分产物的完整性由判分 WAL(evaluation 事件)
# 单独保护,不靠指纹。
MUTABLE_EVALUATION_FIELDS = frozenset({
    "returns", "entry_close", "directional_call",     # backfill 每晚合法写入
    "registry_txn_id", "record_hash",                 # 事务元数据,不入指纹
})


def record_hash(rec):
    """注册指纹:默认冻结(除 MUTABLE_EVALUATION_FIELDS),全部重算,不信自报标签。"""
    payload = {k: rec[k] for k in sorted(rec) if k not in MUTABLE_EVALUATION_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def validate_transaction_projection(txn, intent_payload, projection,
                                    commit_payload=None, *,
                                    require_projection=False, require_commit=False):
    """四方一致性:intent 顶层 / intent.record / projection / commit。

    **全部重算指纹,绝不信任自报标签;必查字段缺失即失败** ——
    上一版 commit_payload 为 None 就跳过、投影缺失也放行,
    于是「intent 在、commit 空、投影不存在」被判为一致。
    返回 (ok, reasons)。
    """
    why = []
    if not intent_payload:
        return False, ["无 intent payload"]
    saved = intent_payload.get("record")
    if not saved:
        return False, ["intent 无可重放记录(旧格式)—— 不得凭 signal_id 前滚"]
    sid = saved.get("signal_id")
    if not sid:
        why.append("intent.record 无 signal_id")
    if intent_payload.get("signal_id") != sid:
        why.append("intent 顶层 signal_id 与 record 不符")
    if saved.get("registry_txn_id") != txn:
        why.append(f"record.registry_txn_id={saved.get('registry_txn_id')!r} ≠ txn(缺失同罪)")
    h_intent = record_hash(saved)
    if intent_payload.get("record_hash") != h_intent:
        why.append("intent 自报 record_hash 与重算不符(缺失同罪)")
    if projection is None:
        if require_projection:
            why.append("投影缺失 —— 已提交事务必须有投影")
    else:
        if record_hash(projection) != h_intent:
            why.append("投影重算指纹 ≠ intent 重算指纹(冻结字段被改)")
        if projection.get("registry_txn_id") != txn:
            why.append(f"投影 registry_txn_id={projection.get('registry_txn_id')!r} ≠ txn")
        if projection.get("signal_id") != sid:
            why.append("投影与 intent 的 signal_id 不符")
    if commit_payload is None:
        if require_commit:
            why.append("commit 缺失")
    else:
        if commit_payload.get("record_hash") != h_intent:
            why.append("commit 保存的 record_hash 与 intent 重算不符(空/缺失同罪)")
        if commit_payload.get("signal_id") != sid:
            why.append("commit 的 signal_id 与 intent 不符(缺失同罪)")
    return (not why), why


def _commit_payload(events, txn):
    for e in events:
        if e.get("kind") == "register_commit" and e.get("id") == txn:
            return e.get("payload") or {}
    return None


def _signal_lock(log_path):
    os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
    return open(log_path + ".lock", "w")


def _terminal_states(events):
    """commit XOR abort。同一 txn 双终态 ⇒ 账本损坏,不得继续。"""
    intents, commits, aborts = _txn_state(events)
    both = commits & aborts
    if both:
        raise LedgerCorrupt(f"txn 同时有 commit 与 abort(双终态): {sorted(both)}")
    return intents, commits, aborts


QUARANTINE_SUFFIX = ".quarantine.json"


def quarantine_projection(log_path, rows, sid, reason):
    """把与 intent 不符的投影行移出账本、存入隔离区(B10)。

    上一版只追加 abort 事件、毒投影原样留在账本里 —— abort 之后错误投影
    仍被当成事实,preflight 照样 PASS。abort 必须伴随隔离,二者同一原子写。
    返回移除后的 rows。"""
    poison = [r for r in rows if r.get("signal_id") == sid]
    clean = [r for r in rows if r.get("signal_id") != sid]
    qp = log_path + QUARANTINE_SUFFIX
    try:
        box = json.load(open(qp, encoding="utf-8")) if os.path.exists(qp) else []
    except (json.JSONDecodeError, OSError):
        box = []          # 隔离区本身坏了不阻断隔离动作 —— 宁可丢隔离历史不留毒行
    for r in poison:
        box.append({"quarantined_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "reason": reason, "record": r})
    write_signal_log_atomic(qp, box)
    write_signal_log_atomic(log_path, clean)
    return clean


def _project(rows, stamped, log_path):
    """把 stamped 记录写进投影(幂等:已存在同 signal_id 则不重复追加)。"""
    sid = stamped["signal_id"]
    if not any(r.get("signal_id") == sid for r in rows):
        rows = rows + [stamped]
        write_signal_log_atomic(log_path, rows)
    return rows


def register_transaction(record, *, registered_at, script, version, run_id,
                         ledger_path, log_path, _test_transaction_id=None):
    """三段式:register_intent(含可重放记录)→ 原子写投影 → register_commit。

    intent 携带**完整 stamped 记录与 record_hash**,因此:
      · intent 后崩溃 ⇒ 恢复可重建投影并提交,信号不会永久丢失
      · 投影与 intent 不符 ⇒ 恢复拒绝盖章,判 abort 并报损坏
      · commit 在而投影丢失 ⇒ 从 intent 重建,重建不了才硬失败(不返回幂等成功)
    """
    import fcntl
    el = _el()
    sid = record.get("signal_id")
    if not sid:
        raise ValueError("signal_id 必填")
    written_by_stamp(script, version, run_id)
    # 生产 API 不接受外部 transaction_id —— 初版允许后,可以用 sid1 的 txn 去登记 sid2:
    # 投影写 sid1、commit 声称 sid2、函数还返回 registered。txn 必须由输入自身决定。
    txn = transaction_id_for(sid, registered_at, run_id)
    if _test_transaction_id is not None:
        if _test_transaction_id != txn:
            raise ValueError("_test_transaction_id 与由输入计算出的 txn 不符 —— 拒绝交叉事务")

    with _signal_lock(log_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            events = read_events(ledger_path)
            intents, commits, aborts = _terminal_states(events)
            rows = load_signal_log_strict(log_path)
            existing = next((r for r in rows if r.get("signal_id") == sid), None)

            if txn in aborts:
                return None, f"refused: transaction {txn} 已被中止(intent 不可用),需人工复核"

            # 已 commit:投影必须真的在,否则从 intent 重建;重建不了 ⇒ 硬失败
            if txn in commits:
                ip = intents.get(txn)
                cp = _commit_payload(events, txn)
                if existing is not None:
                    ok, why = validate_transaction_projection(
                        txn, ip, existing, cp, require_projection=True, require_commit=True)
                    if not ok:
                        # 已提交但投影被改:隔离毒行(B10),并尝试从 intent 重建真身
                        rows = quarantine_projection(log_path, rows, sid,
                                                     "committed-mismatch: " + "; ".join(why)[:140])
                        ok2, why2 = validate_transaction_projection(
                            txn, ip, None, cp, require_commit=True)
                        if ok2:
                            rows = _project(rows, ip["record"], log_path)
                            return ip["record"], "recovered: poisoned projection quarantined, rebuilt from intent"
                        raise LedgerCorrupt(
                            f"txn {txn} 已 commit,投影被改已隔离,且 intent 不足以重建: {why}")
                    return existing, "idempotent: already committed (validated)"
                ok, why = validate_transaction_projection(
                    txn, ip, None, cp, require_commit=True)
                if not ok:
                    raise LedgerCorrupt(
                        f"txn {txn} 已 commit 但投影丢失且无法重建: {why}")
                rows = _project(rows, ip["record"], log_path)
                return ip["record"], "recovered: projection rebuilt from intent"

            # 投影里已有该 signal_id,却不是本事务的 ⇒ 另一次登记已完成
            if existing is not None and txn not in intents:
                return None, f"refused: signal_id {sid} 已登记(非本事务)"

            stamped = ((intents.get(txn) or {}).get("record")
                       if txn in intents else None)
            if stamped is None:
                stamped = stamp_new_record(record, registered_at=registered_at,
                                           script=script, version=version, run_id=run_id)
                stamped["registry_txn_id"] = txn
                stamped["record_hash"] = record_hash(stamped)
                # intent 只在**尚不存在**时写。旧格式 intent(无 record)也已存在,
                # 重复 append 会撞链层 (kind,id) 唯一性 —— 那是接续,不是新事务。
                if txn not in intents:
                    el.append("register_intent", txn,
                              {"signal_id": sid, "record": stamped,
                               "record_hash": stamped["record_hash"],
                               "written_by": stamped["written_by"]},
                              path=ledger_path)

            if existing is not None:
                ok, why = validate_transaction_projection(
                    txn, intents.get(txn) or {"record": stamped}, existing)
                if not ok:
                    rows = quarantine_projection(log_path, rows, sid,
                                                 "register: " + "; ".join(why)[:160])
                    el.append("register_abort", txn,
                              {"signal_id": sid, "reason": "; ".join(why)[:200],
                               "quarantined": True}, path=ledger_path)
                    raise LedgerCorrupt(f"signal {sid} 的投影与 intent 不符,已隔离并中止: {why}")

            rows = _project(rows, stamped, log_path)
            el.append("register_commit", txn,
                      {"signal_id": sid, "record_hash": record_hash(stamped)},
                      path=ledger_path)
            return stamped, "registered"
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def recover_pending(ledger_path, log_path, apply=True):
    """收拾悬空事务。**取与登记事务同一把信号锁**,避免与在写事务竞争产生双终态。

    intent 有可重放记录 ⇒ 缺投影就重建并 commit(前滚),不再一律 abort ——
    初版看到没投影就 abort,而确定性 txn_id 让重试永远撞上「已中止」,信号永久丢失。
    投影存在但 record_hash 与 intent 不符 ⇒ abort 并报损坏,绝不盖章。
    """
    import fcntl
    el = _el()
    with _signal_lock(log_path) as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            events = read_events(ledger_path)
            intents, commits, aborts = _terminal_states(events)
            rows = load_signal_log_strict(log_path)
            by_sid = {r.get("signal_id"): r for r in rows}
            out = {"rolled_forward": [], "rebuilt": [], "aborted": [],
                   "mismatch": [], "pending_examined": 0}
            for txn, payload in intents.items():
                if txn in commits or txn in aborts:
                    continue
                out["pending_examined"] += 1
                sid = payload.get("signal_id")
                saved = payload.get("record")
                existing = by_sid.get(sid)
                if existing is not None:
                    # 全部重算。旧格式 intent(无 record)在这里必然不通过 ——
                    # 不得凭 signal_id 前滚,那会把内容完全不同的记录盖成已提交。
                    ok, why = validate_transaction_projection(txn, payload, existing)
                    if not ok:
                        if apply:
                            rows = quarantine_projection(log_path, rows, sid,
                                                         "recover: " + "; ".join(why)[:160])
                            by_sid.pop(sid, None)
                            el.append("register_abort", txn,
                                      {"signal_id": sid, "reason": "; ".join(why)[:200],
                                       "quarantined": True}, path=ledger_path)
                        out["mismatch"].append(txn); out["aborted"].append(txn)
                        continue
                    if apply:
                        el.append("register_commit", txn,
                                  {"signal_id": sid, "record_hash": record_hash(existing),
                                   "by": "recover_pending"}, path=ledger_path)
                    out["rolled_forward"].append(txn)
                elif saved:
                    # 重建之前必须先验 intent 自身(txn 一致 / 顶层 sid / 自报 hash)——
                    # 上一版无条件 _project,构造 registry_txn_id=WRONG、伪 hash、
                    # 顶层与 record sid 不一致的 intent 照样被写入投影并 commit。
                    ok, why = validate_transaction_projection(txn, payload, None)
                    if not ok:
                        if apply:
                            el.append("register_abort", txn,
                                      {"signal_id": sid, "reason": "; ".join(why)[:200]},
                                      path=ledger_path)
                        out["mismatch"].append(txn); out["aborted"].append(txn)
                        continue
                    if apply:
                        rows = _project(rows, saved, log_path)
                        by_sid[sid] = saved
                        el.append("register_commit", txn,
                                  {"signal_id": sid, "record_hash": record_hash(saved),
                                   "by": "recover_pending/rebuild"}, path=ledger_path)
                    out["rebuilt"].append(txn); out["rolled_forward"].append(txn)
                else:
                    # intent 里没有可重放记录(旧格式)⇒ 只能作废
                    if apply:
                        el.append("register_abort", txn,
                                  {"signal_id": sid, "reason": "intent 无可重放记录(旧格式)"},
                                  path=ledger_path)
                    out["aborted"].append(txn)
            return out
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def selftest():
    """每一条拒绝都必须被证明会触发 —— 只证明"正常路径能过"是不够的。"""
    import tempfile, shutil
    ok = []
    def ck(n, c): ok.append((n, c)); print(f"  {'✓' if c else '✗'} {n}")

    ck("解析 close (official)", parse_trade_date("20260625 close (official)") == "20260625")
    ck("解析 HH:MM", parse_trade_date("20260711 15:20") == "20260711")
    ck("解析 intraday 变体", parse_trade_date("20260731 14:37 (intraday, 定盘判分)") == "20260731")
    ck("不可解析 → None(不得当作今天)", parse_trade_date("昨天收盘") is None)
    ck("非法日期 → None", parse_trade_date("20261345 close") is None)
    ck("clock:close 无时钟 → None", parse_clock("20260625 close (official)") is None)
    ck("clock:HH:MM → 15:20", parse_clock("20260711 15:20") == "15:20")

    d, src = registered_trade_date({"timestamp": "20260711 15:20"})
    ck("历史行只派生不写入(来源标 derived)", d == "20260711" and src == "derived_from_timestamp")
    d2, s2 = registered_trade_date({"registered_trade_date": "20260801", "timestamp": "20260711 15:20"})
    ck("字段优先于派生", d2 == "20260801" and s2 == "field")
    ck("两者皆无 → unavailable", registered_trade_date({})[1] == "unavailable")

    try:
        written_by_stamp("evil.py", "1", "r1"); bad = False
    except ValueError:
        bad = True
    ck("写入者不在允许清单 → 拒绝", bad)
    ck("允许清单内 → 通过", written_by_stamp("paper_tracker.py", "2", "r1")["script"] == "paper_tracker.py")

    base = {"signal_id": "s1", "ticker": "000001.SZ", "setup_type": "x"}
    KW = dict(registered_at="20260803 15:00", script="paper_tracker.py",
              version="v2", run_id="r1")
    got = stamp_new_record(dict(base), **KW)
    ck("新登记三字段齐备", all(got.get(f) for f in LEDGER_FIELDS))
    ck("registered_trade_date 由 registered_at 派生", got["registered_trade_date"] == "20260803")

    # 断言必须指认**具体哪道闸门** —— 否则空值被下游『不可解析』接住时,
    # 这条断言照样绿,而它声称测的那道门已经被拆了(实测:短路它 → 转红 0 条)。
    for name, kw, want in (
            ("registered_at 为空 → 被『必填』闸门拦住", dict(registered_at=""), "必填"),
            ("registered_at 不可解析 → 被『交易日解析』闸门拦住", dict(registered_at="昨天"), "不可解析")):
        try:
            stamp_new_record(dict(base), **{**KW, **kw}); hit = ""
        except ValueError as e:
            hit = str(e)
        ck(name, want in hit)
    try:
        stamp_new_record(got, **KW); blocked = False
    except ValueError:
        blocked = True
    ck("已有 schema v2 字段再写 → 拒绝(rewrite)", blocked)

    # ── 严格读写 ──
    d0 = tempfile.mkdtemp()
    try:
        bad = os.path.join(d0, "bad.json"); open(bad, "w").write("{坏")
        try:
            load_signal_log_strict(bad); blocked = False
        except LedgerCorrupt:
            blocked = True
        ck("旧 JSON 损坏 → 报错停机(绝不当空账本)", blocked)
        ck("文件不存在 → 空列表(合法首次)", load_signal_log_strict(os.path.join(d0, "none.json")) == [])
        ap = os.path.join(d0, "a.json"); write_signal_log_atomic(ap, [{"x": 1}])
        ck("原子写:落盘内容正确且无残留 .tmp",
           json.load(open(ap)) == [{"x": 1}] and not os.path.exists(ap + ".tmp"))

        # ── 时间判断:正反两组边界,调真函数、用真 git 仓库 ──
        gd = tempfile.mkdtemp()
        try:
            subprocess.run(["git", "init", "-q", gd], check=True)
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                subprocess.run(["git", "-C", gd, "config", k, v], check=True)
            gl = os.path.join(gd, "led.json")
            json.dump([{"signal_id": "SIGX", "timestamp": "20260803 15:00"}],
                      open(gl, "w"), ensure_ascii=False)
            subprocess.run(["git", "-C", gd, "add", "-A"], check=True)
            subprocess.run(["git", "-C", gd, "commit", "-qm", "s",
                            "--date=2026-08-03T15:00:00"],
                           check=True, env={**os.environ,
                                            "GIT_COMMITTER_DATE": "2026-08-03T15:00:00"})
            gday = first_git_appearance("SIGX", gl)
            ck("首次 git 出现日可取到", gday == "20260803")
            # 反例:今天登记却谎称上月 —— 结果已可见,却会被算成「前瞻」
            neg = registered_at_of({"signal_id": "SIGX", "timestamp": "20260701 15:00"}, gl)
            ck("反例 claimed<git → backdated=True", neg["backdated"] is True)
            ck("反例 前瞻锚点取晚者(不替伪造值背书)", neg["prospective_from"] == "20260803")
            ck("反例 证据锚点取早者(限制可引用证据,越早越严)", neg["evidence_anchor"] == "20260701")
            # 正例:如实登记
            pos = registered_at_of({"signal_id": "SIGX", "timestamp": "20260803 15:00"}, gl)
            ck("正例 claimed==git → backdated=False", pos["backdated"] is False)
            # 边界:claimed 晚于 git(补登,不是回填风险)
            late = registered_at_of({"signal_id": "SIGX", "timestamp": "20260905 15:00"}, gl)
            ck("边界 claimed>git → 非 backdated(补登不是倒填)", late["backdated"] is False)
            # 取不到 git 日期时不得当作干净
            unk = registered_at_of({"signal_id": "NOPE", "timestamp": "20260701 15:00"}, gl)
            ck("取不到 git 日期 → backdated=UNKNOWN(不判干净)", unk["backdated"] == "UNKNOWN")
        finally:
            shutil.rmtree(gd, ignore_errors=True)

        # ── 三段式事务:六个场景 ──
        el = _el()
        def fresh():
            dd = tempfile.mkdtemp()
            return dd, os.path.join(dd, "sig.json"), os.path.join(dd, "event_ledger.jsonl")
        def sids(sp):
            return [r["signal_id"] for r in (json.load(open(sp)) if os.path.exists(sp) else [])]
        def kinds(lp):
            return [json.loads(l)["kind"] for l in el._read_lines(lp)]

        dd, sp, lp = fresh()
        txn = transaction_id_for("s1", "20260803 15:00", "r1")
        el.append("register_intent", txn, {"signal_id": "s1"}, path=lp)
        r = recover_pending(lp, sp)
        ck("① intent 后中断 → 恢复判 abort(投影没写成)",
           r["aborted"] == [txn] and "register_abort" in kinds(lp))
        shutil.rmtree(dd, ignore_errors=True)

        # ② 用**真实事务**制造中断态(手工造 intent 会变成旧格式,那是另一个场景)
        dd, sp, lp = fresh()
        register_transaction({"signal_id": "s2", "ticker": "600000.SH"},
                             ledger_path=lp, log_path=sp, **KW)
        L = el._read_lines(lp)                       # 砍掉 commit,保留 intent 与投影
        open(lp, "w").write(L[0] + "\n")
        el.write_anchor(lp, 1, json.loads(L[0])["hash"])
        txn = transaction_id_for("s2", "20260803 15:00", "r1")
        r = recover_pending(lp, sp)
        ck("② 投影已写 commit 未写 → 恢复前滚", r["rolled_forward"] == [txn])
        ck("②b 恢复幂等(再跑一次无待处理)", recover_pending(lp, sp)["pending_examined"] == 0)
        shutil.rmtree(dd, ignore_errors=True)

        # ②c 旧格式 intent(无 record)即便投影里有同 ID,也一律 abort ——
        #     不得凭 signal_id 前滚,否则会把内容完全不同的记录盖成已提交。
        dd, sp, lp = fresh()
        txn = transaction_id_for("s2", "20260803 15:00", "r1")
        el.append("register_intent", txn, {"signal_id": "s2"}, path=lp)
        write_signal_log_atomic(sp, [{"signal_id": "s2", "ticker": "完全不同"}])
        r = recover_pending(lp, sp)
        ck("②c 旧格式 intent + 同 ID 异内容 → abort 不前滚",
           r["aborted"] == [txn] and not r["rolled_forward"])
        shutil.rmtree(dd, ignore_errors=True)

        # ②d 篡改投影内容但保留自报 record_hash → 必须被重算揪出
        dd, sp, lp = fresh()
        register_transaction({"signal_id": "s2", "ticker": "600000.SH"},
                             ledger_path=lp, log_path=sp, **KW)
        L = el._read_lines(lp); open(lp, "w").write(L[0] + "\n")
        el.write_anchor(lp, 1, json.loads(L[0])["hash"])
        rws = load_signal_log_strict(sp); rws[0]["ticker"] = "999999.SZ"
        write_signal_log_atomic(sp, rws)
        r = recover_pending(lp, sp)
        ck("②d 篡改内容保留 hash 标签 → 重算揪出,拒绝盖章",
           r["mismatch"] and not r["rolled_forward"])
        shutil.rmtree(dd, ignore_errors=True)

        # ②e 已 commit 的投影被篡改 → 绝不把毒行当幂等成功返回:
        #     隔离毒行 + 从 intent 重建真身(B10),返回的必须是原始记录
        dd, sp, lp = fresh()
        register_transaction({"signal_id": "s2", "ticker": "600000.SH"},
                             ledger_path=lp, log_path=sp, **KW)
        rws = load_signal_log_strict(sp); rws[0]["ticker"] = "999999.SZ"
        write_signal_log_atomic(sp, rws)
        rec_e, st_e = register_transaction({"signal_id": "s2", "ticker": "600000.SH"},
                                           ledger_path=lp, log_path=sp, **KW)
        box = json.load(open(sp + QUARANTINE_SUFFIX))
        ck("②e 已提交记录被篡改 → 隔离毒行并重建真身",
           st_e.startswith("recovered") and rec_e["ticker"] == "600000.SH"
           and len(box) == 1 and box[0]["record"]["ticker"] == "999999.SZ"
           and load_signal_log_strict(sp)[0]["ticker"] == "600000.SH")
        shutil.rmtree(dd, ignore_errors=True)

        # ②f 交叉事务:用别的 signal 的 txn 登记
        dd, sp, lp = fresh()
        other = transaction_id_for("other", "20260803 15:00", "r1")
        try:
            register_transaction({"signal_id": "s2", "ticker": "t"}, ledger_path=lp,
                                 log_path=sp, _test_transaction_id=other, **KW)
            blocked = False
        except ValueError:
            blocked = True
        ck("②f 交叉事务(借用他人 txn)→ 拒绝", blocked)
        shutil.rmtree(dd, ignore_errors=True)

        dd, sp, lp = fresh()
        register_transaction(dict(base), ledger_path=lp, log_path=sp, **KW)
        _, s2 = register_transaction(dict(base), ledger_path=lp, log_path=sp, **KW)
        ck("③ 同一 txn 重试 → 幂等,不重复登记",
           s2.startswith("idempotent") and len(sids(sp)) == 1)
        _, s3 = register_transaction(dict(base), ledger_path=lp, log_path=sp,
                                     **{**KW, "run_id": "r2"})
        ck("④ 不同 txn 同一 signal_id → 拒绝", "已登记" in s3 and len(sids(sp)) == 1)
        shutil.rmtree(dd, ignore_errors=True)

        dd, sp, lp = fresh()
        txn = transaction_id_for("s5", "20260803 15:00", "r1")
        el.append("register_intent", txn, {"signal_id": "s5"}, path=lp)
        _, s5 = register_transaction({"signal_id": "s5", "ticker": "t"},
                                     ledger_path=lp, log_path=sp, **KW)
        ck("⑤ 中断后重试(非恢复)→ 续做,只有一条 intent",
           s5 == "registered" and len(sids(sp)) == 1 and kinds(lp).count("register_intent") == 1)
        shutil.rmtree(dd, ignore_errors=True)

        import concurrent.futures as cf
        for label, mk, want in (("同一 signal_id", lambda i: {"signal_id": "same", "ticker": "t"}, 1),
                                ("不同 signal_id", lambda i: {"signal_id": f"c{i}", "ticker": "t"}, 8)):
            dd, sp, lp = fresh()
            def go(i):
                try:
                    return register_transaction(mk(i), ledger_path=lp, log_path=sp,
                                                **{**KW, "run_id": f"r{i}"})[1]
                except Exception as e:
                    return f"ERR {e}"
            with cf.ThreadPoolExecutor(8) as ex:
                list(ex.map(go, range(8)))
            n = sids(sp)
            ck(f"⑥ 并发 {label} ×8 → {want} 条且无重复",
               len(n) == want and len(set(n)) == want)
            shutil.rmtree(dd, ignore_errors=True)

        # 四方校验的 commit 门必须**单独**可证伪 —— 其余三方全部合法、
        # 仅 commit 为空/缺失,也必须失败(否则"intent 在、commit 空"被判一致)。
        dd, sp, lp = fresh()
        register_transaction({"signal_id": "s9", "ticker": "600000.SH"},
                             ledger_path=lp, log_path=sp, **{**KW, "run_id": "r9"})
        evs9 = read_events(lp)
        ip9 = next(e["payload"] for e in evs9 if e["kind"] == "register_intent")
        txn9 = next(e["id"] for e in evs9 if e["kind"] == "register_intent")
        proj9 = load_signal_log_strict(sp)[0]
        ok_full, _ = validate_transaction_projection(txn9, ip9, proj9,
                                                     {"signal_id": "s9",
                                                      "record_hash": record_hash(proj9)},
                                                     require_projection=True, require_commit=True)
        ck("四方全合法 → 通过", ok_full)
        ok_none, _ = validate_transaction_projection(txn9, ip9, proj9, None,
                                                     require_projection=True, require_commit=True)
        ck("仅 commit 缺失 → 失败", not ok_none)
        ok_empty, _ = validate_transaction_projection(txn9, ip9, proj9, {},
                                                      require_projection=True, require_commit=True)
        ck("仅 commit 为空 dict → 失败", not ok_empty)
        ok_noproj, _ = validate_transaction_projection(txn9, ip9, None,
                                                       {"signal_id": "s9",
                                                        "record_hash": record_hash(proj9)},
                                                       require_projection=True, require_commit=True)
        ck("仅投影缺失 → 失败", not ok_noproj)
        shutil.rmtree(dd, ignore_errors=True)

        # 链损坏时拒绝做事务判定
        dd, sp, lp = fresh()
        register_transaction({"signal_id": "z", "ticker": "t"}, ledger_path=lp, log_path=sp, **KW)
        lines = el._read_lines(lp); open(lp, "w").write(lines[0] + "\n")   # 砍尾
        try:
            register_transaction({"signal_id": "z2", "ticker": "t"},
                                 ledger_path=lp, log_path=sp, **KW); blocked = False
        except Exception:
            blocked = True
        ck("链被砍尾 → 拒绝继续做事务", blocked)
        shutil.rmtree(dd, ignore_errors=True)
    finally:
        shutil.rmtree(d0, ignore_errors=True)

    passed = sum(1 for _, c in ok if c)
    print(f"registry selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "paper_signal_log.json")
    for i, a in enumerate(sys.argv):
        if a == "--path" and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
    print(json.dumps(audit_ledger(path), ensure_ascii=False, indent=1))
    print("不是买卖指令;研究信号,human executes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
