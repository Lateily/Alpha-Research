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
import os, re, sys, json, datetime, subprocess

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
    out["value"] = min(claimed, g)
    out["backdated"] = claimed > g            # 自称早于首次入库 ⇒ 回填过去日期
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


def stamp_new_record(rec, *, registered_at, script, version, run_id,
                     ledger_path=None, ledger_append=None):
    """给**新**登记记录打 schema v2 三字段,并向 R-015 事件账本追加 register 事件。

    拒绝:①registered_at 为空(不许本模块发明时间戳)②记录已有任一 schema v2 字段
    (那是既有记录,再写即 rewrite,C5 §2.2)③写入者不在允许清单
    ④事件账本写入失败(不允许产生无审计轨迹的信号)。
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

    appender = ledger_append if ledger_append is not None else _make_appender(ledger_path)
    if appender is not False:
        appender("register", rec.get("signal_id") or "UNKNOWN",
                 {"ticker": rec.get("ticker"), "setup_type": rec.get("setup_type"),
                  "registered_at": rec["registered_at"],
                  "registered_trade_date": d, "written_by": rec["written_by"]})
    return rec


def _make_appender(ledger_path):
    if ledger_path is None:
        raise ValueError("ledger_path 必填 —— 不得隐式落到仓库里那条真链")
    def _append(kind, rec_id, payload):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import event_ledger
        return event_ledger.append(kind, rec_id, payload, path=ledger_path)
    return _append


def audit_ledger(path):
    """只读体检:统计三字段覆盖、可派生率、backdated 命中。不写盘。"""
    data = json.load(open(path, encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("signals", data.get("log", []))
    out = {"n": len(rows), "has_field": {f: 0 for f in LEDGER_FIELDS},
           "derivable_trade_date": 0, "unparseable_timestamp": [], "backdated": []}
    for s in rows:
        for f in LEDGER_FIELDS:
            if s.get(f):
                out["has_field"][f] += 1
        d, src = registered_trade_date(s)
        if d:
            out["derivable_trade_date"] += 1
        else:
            out["unparseable_timestamp"].append(s.get("signal_id"))
    return out


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
    got = stamp_new_record(base, registered_at="20260803 15:00", script="registry_selftest",
                           version="1", run_id="r1", ledger_append=False)
    ck("新登记三字段齐备", all(got.get(f) for f in LEDGER_FIELDS))
    ck("registered_trade_date 由 registered_at 派生", got["registered_trade_date"] == "20260803")

    # 断言必须指认**具体哪道闸门**拦住的 —— 否则空值被下游"不可解析"接住时,
    # 这条断言照样绿,而它声称测的那道闸门已经被拆了(实测:短路它 → 转红 0 条)。
    for name, kw, want in (
            ("registered_at 为空 → 被『必填』闸门拦住", dict(registered_at=""), "必填"),
            ("registered_at 不可解析 → 被『交易日解析』闸门拦住", dict(registered_at="昨天"), "不可解析")):
        try:
            stamp_new_record(base, script="registry_selftest", version="1", run_id="r1",
                             ledger_append=False, **kw)
            hit = ""
        except ValueError as e:
            hit = str(e)
        ck(name, want in hit)
    try:
        stamp_new_record(got, registered_at="20260803 15:00", script="registry_selftest",
                         version="1", run_id="r1", ledger_append=False); blocked = False
    except ValueError:
        blocked = True
    ck("已有 schema v2 字段再写 → 拒绝(rewrite)", blocked)

    # 事件账本写不进去 ⇒ 登记必须失败,不允许无审计轨迹的信号
    def boom(*a, **k):
        raise IOError("ledger down")
    try:
        stamp_new_record(base, registered_at="20260803 15:00", script="registry_selftest",
                         version="1", run_id="r1", ledger_append=boom); blocked = False
    except IOError:
        blocked = True
    ck("事件账本写入失败 → 登记失败(不产生无审计信号)", blocked)

    # 真实追加到临时事件账本
    d0 = tempfile.mkdtemp()
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import event_ledger
        lp = os.path.join(d0, "t.jsonl")
        stamp_new_record(base, registered_at="20260803 15:00", script="registry_selftest",
                         version="1", run_id="r1", ledger_path=lp)
        st = event_ledger.verify(lp)
        ck("register 事件真的落进 R-015 链", st["ok"] and st["n"] == 1)
        try:
            stamp_new_record({"signal_id": "s9"}, registered_at="20260803 15:00",
                             script="registry_selftest", version="1", run_id="r9")
            blocked = False
        except ValueError as e:
            blocked = "ledger_path 必填" in str(e)
        ck("不给 ledger_path → 拒绝(不得隐式写真链)", blocked)
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
