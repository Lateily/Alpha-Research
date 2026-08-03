#!/usr/bin/env python3
"""R-015 不可篡改事件账本 —— 全部簇机制(C5 / R-039 / R-040 / R-041)的地基。

C5 §6.2 把本模块列为硬前置:C5 的不可篡改性预设账本本身不可篡改,
在本模块建成前,C5 的一切保证只是纪律而非机制。

设计:
  · append-only JSONL,一行一条记录,永不改写既有行
  · 前序哈希成链:每条记录携带 prev(上一条的 hash),任何中间篡改都会断链
  · 写入持 flock 排他锁 —— 账本有至少两个写手(execution_tracker --log /
    run_post_close_report.append_log),无锁则 preflight 时点的状态 ≠ 写入时点的状态
  · 删除检测分两层 —— **哈希链抓不到尾部截断**:砍掉最后一行后 seq 与 prev 链
    依然完美自洽,而"删掉旧记录再重新登记"最容易走的正是这条路。故另设锚点文件
    (head hash + 条数,单调不减)与 git 行前缀校验双重覆盖。
    诚实边界:同时拥有账本与锚点写权限的本机攻击者可以同时改两者;
    真正的保证来自已提交的 git 历史,而 0712 的 git-reset-hard 证明 git 本身
    在此仓库也不构成 append-only —— 两者叠加只是提高门槛,不是绝对不可篡改。
  · 跨提交的 append-only 校验:旧版本必须是新版本的**行前缀**,
    仅靠单文件自洽无法发现"整份重写但自洽"的账本

fail-closed:任何无法解析、无法核验的情形一律 FAIL,不得当作通过。
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, hashlib, datetime, subprocess

GENESIS_PREV = "0" * 64
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_ledger.jsonl")
ANCHOR_SUFFIX = ".anchor.json"
HASHED_FIELDS = ("seq", "ts", "kind", "id", "payload", "prev")


def canonical(obj):
    """C5 §5.3 哈希规范:键排序 · UTF-8 · 无空格分隔 · 浮点定点。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=_fixed)


def _fixed(o):
    if isinstance(o, float):
        return format(o, ".10f")
    raise TypeError(f"不可序列化: {type(o)}")


def record_hash(rec):
    """对 HASHED_FIELDS 计算,即"移除 hash 字段后"(C5 §2.1/§5.3 同款)。"""
    return hashlib.sha256(canonical({k: rec[k] for k in HASHED_FIELDS}).encode()).hexdigest()


def _read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [ln for ln in fh.read().splitlines() if ln.strip()]


def _anchor_path(path):
    return path + ANCHOR_SUFFIX


def read_anchor(path=DEFAULT_PATH):
    try:
        with open(_anchor_path(path), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_anchor(path, n, head):
    with open(_anchor_path(path), "w", encoding="utf-8") as fh:
        json.dump({"n": n, "head": head,
                   "note": "单调不减;n 减少或 head 不匹配即尾部截断"}, fh, ensure_ascii=False)
        fh.flush(); os.fsync(fh.fileno())


def verify_anchor(path=DEFAULT_PATH):
    """尾部截断检测。哈希链自洽 ≠ 没被砍尾巴。"""
    a = read_anchor(path)
    if a is None:
        return {"ok": True, "errors": [], "note": "无锚点(首次运行)"}
    st = verify(path)
    if not st["ok"]:
        return {"ok": False, "errors": ["链本身已损坏"]}
    if st["n"] < a["n"]:
        return {"ok": False, "errors": [f"条数减少 {a['n']}→{st['n']}:尾部被截断"]}
    if st["n"] == a["n"] and st["head"] != a["head"]:
        return {"ok": False, "errors": ["条数相同但 head 不符:尾部被替换"]}
    return {"ok": True, "errors": [], "grew": st["n"] - a["n"]}


def verify(path=DEFAULT_PATH):
    """走链核验。返回 {"ok": bool, "n": int, "head": hash|None, "errors": [...]}。
    fail-closed:解析失败即 error,不跳过。"""
    errs, lines = [], _read_lines(path)
    prev, n = GENESIS_PREV, 0
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError as e:
            errs.append(f"line{i}: 不可解析 JSON ({e}) —— fail-closed,不跳过")
            return {"ok": False, "n": i, "head": None, "errors": errs}
        missing = [k for k in HASHED_FIELDS + ("hash",) if k not in rec]
        if missing:
            errs.append(f"line{i}: 缺字段 {missing}")
            return {"ok": False, "n": i, "head": None, "errors": errs}
        if rec["seq"] != i:
            errs.append(f"line{i}: seq={rec['seq']} 不连续(删除或插入的证据)")
        if rec["prev"] != prev:
            errs.append(f"line{i}: prev 不匹配上一条 hash(链断 —— 中间行被改写或删除)")
        h = record_hash(rec)
        if rec["hash"] != h:
            errs.append(f"line{i}: hash 与内容不符(本行被改写)")
        prev, n = rec["hash"], n + 1
    return {"ok": not errs, "n": n, "head": (prev if n else None), "errors": errs}


def verify_append_only(path=DEFAULT_PATH, ref="HEAD"):
    """跨提交 append-only 校验:git 中的旧版本必须是当前文件的**行前缀**。
    单文件自洽无法发现"整份重写但自洽"——那正是 0712 git-reset-hard 的形态。"""
    repo = _repo_root(path)
    if repo is None:
        return {"ok": False, "errors": ["无法定位 git 仓库根 —— fail-closed(不得当作首次提交放行)"]}
    rel = os.path.relpath(os.path.abspath(path), repo)
    try:
        old = subprocess.run(["git", "-C", repo, "show", f"{ref}:{rel}"],
                             capture_output=True, text=True, timeout=20)
    except Exception as e:
        return {"ok": False, "errors": [f"git 调用失败: {e} —— fail-closed"]}
    if old.returncode != 0:
        # 只有"该 ref 下确实没有此路径"才算首次提交;其余一切 git 错误 fail-closed。
        # (曾经的 bug:worktree 里 .git 是文件不是目录,_repo_root 走到 /,
        #  git 失败被当成首次提交 ⇒ 整个闸门 fail-open 放行一切篡改。)
        err = (old.stderr or "").lower()
        if "exists on disk, but not in" in err or "does not exist" in err or "path" in err and "not in" in err:
            return {"ok": True, "errors": [], "note": f"{ref} 中尚无该文件(首次提交)"}
        return {"ok": False, "errors": [f"git show 失败(rc={old.returncode}): {old.stderr.strip()[:120]} —— fail-closed"]}
    o = [ln for ln in old.stdout.splitlines() if ln.strip()]
    c = _read_lines(path)
    if len(c) < len(o):
        return {"ok": False, "errors": [f"行数减少 {len(o)}→{len(c)}:有记录被删除"]}
    bad = [i for i in range(len(o)) if o[i] != c[i]]
    if bad:
        return {"ok": False, "errors": [f"既有行被改写(首个差异在 line{bad[0]},共 {len(bad)} 行)"]}
    return {"ok": True, "errors": [], "appended": len(c) - len(o)}


def _repo_root(path):
    """worktree 里 .git 是**文件**不是目录,故用 git 自己解析,不手工向上找。"""
    d = os.path.dirname(os.path.abspath(path))
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def append(kind, rec_id, payload, path=DEFAULT_PATH, now=None):
    """持排他 flock 追加一条记录。写前必须链完整,否则拒写(不在坏链上继续追加)。"""
    import fcntl
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    lock = path + ".lock"
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            st = verify(path)
            if not st["ok"]:
                raise ValueError(f"账本已损坏,拒绝追加: {st['errors'][:2]}")
            an = verify_anchor(path)
            if not an["ok"]:
                raise ValueError(f"账本与锚点不符,拒绝追加: {an['errors']}")
            rec = {"seq": st["n"], "kind": kind, "id": rec_id, "payload": payload,
                   "ts": now or datetime.datetime.now().isoformat(timespec="seconds"),
                   "prev": st["head"] or GENESIS_PREV}
            rec["hash"] = record_hash(rec)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(canonical(rec) + "\n")
                fh.flush(); os.fsync(fh.fileno())
            write_anchor(path, st["n"] + 1, rec["hash"])
            return rec
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def selftest():
    """按本季教训:自查工具必须先被证明"会失败",才配被信任。
    每一类篡改都必须被抓到 —— 只证明"干净账本通过"是不够的。"""
    import tempfile, shutil
    ok = []
    def ck(name, cond): ok.append((name, cond)); print(f"  {'✓' if cond else '✗'} {name}")
    d = tempfile.mkdtemp(); p = os.path.join(d, "t.jsonl")
    try:
        for i in range(4):
            append("register", f"sig{i}", {"ticker": f"00000{i}.SZ"}, path=p, now=f"2026-08-0{i+1}T15:00:00")
        ck("干净账本 4 条 → ok", verify(p)["ok"] and verify(p)["n"] == 4)

        def mutate(fn):
            q = p + ".m"; shutil.copy(p, q)
            ls = _read_lines(q); ls = fn(ls)
            open(q, "w", encoding="utf-8").write("\n".join(ls) + "\n")
            return verify(q)

        r = mutate(lambda ls: ls[:1] + ls[2:])
        ck("删中间一行 → 抓到", not r["ok"])
        # 尾部截断:哈希链**抓不到**(seq 0..n-1 与 prev 链仍自洽)——
        # 这是设计的真实边界,不是测试写错。必须由锚点抓。
        q = p + ".tail"; shutil.copy(p, q); shutil.copy(_anchor_path(p), _anchor_path(q))
        open(q, "w", encoding="utf-8").write("\n".join(_read_lines(q)[:-1]) + "\n")
        ck("删最后一行 → 哈希链自洽(诚实承认此边界)", verify(q)["ok"])
        ck("删最后一行 → 锚点抓到", not verify_anchor(q)["ok"])
        def edit(ls):
            o = json.loads(ls[1]); o["payload"]["ticker"] = "999999.SZ"; ls[1] = canonical(o); return ls
        r = mutate(edit)
        ck("改内容不改 hash → 抓到", not r["ok"])
        def rehash(ls):
            o = json.loads(ls[1]); o["payload"]["ticker"] = "999999.SZ"
            o["hash"] = record_hash(o); ls[1] = canonical(o); return ls
        r = mutate(rehash)
        ck("改内容并重算 hash → 仍抓到(prev 链断)", not r["ok"])
        r = mutate(lambda ls: [ls[0], ls[2], ls[1], ls[3]])
        ck("调换顺序 → 抓到", not r["ok"])
        r = mutate(lambda ls: ls + ["{不是JSON"])
        ck("损坏行 → fail-closed 抓到(不跳过)", not r["ok"])
        def whole(ls):
            q2 = os.path.join(d, "w.jsonl")
            if os.path.exists(q2): os.remove(q2)
            for i in range(3):
                append("register", f"sigX{i}", {}, path=q2, now="2026-08-01T15:00:00")
            return _read_lines(q2)
        r = mutate(whole)
        ck("整份重写但自洽 → 单文件核验放行(须靠 verify_append_only)", r["ok"])

        # 被截断的账本上拒绝继续追加(否则"删掉再登记"就成了合法路径)
        try:
            append("register", "sigZ", {}, path=q); blocked = False
        except ValueError:
            blocked = True
        ck("被截断的账本上追加 → 拒写", blocked)
        # 中间被改写的账本上也拒写
        q3 = p + ".bad"; shutil.copy(p, q3); shutil.copy(_anchor_path(p), _anchor_path(q3))
        ls = _read_lines(q3); o = json.loads(ls[1]); o["payload"]["ticker"] = "X"
        ls[1] = canonical(o); open(q3, "w", encoding="utf-8").write("\n".join(ls) + "\n")
        try:
            append("register", "sigZ", {}, path=q3); blocked2 = False
        except ValueError:
            blocked2 = True
        ck("坏链上追加 → 拒写", blocked2)
        # ── 跨提交层(verify_append_only)必须被证明"会失败" ──
        # 曾经的 bug:worktree 里 .git 是文件,_repo_root 走到 / ⇒ git 失败被当成
        # "首次提交"放行 ⇒ 整个闸门 fail-open。这两条断言就是那个 bug 的回归测试。
        r = verify_append_only(os.path.join(d, "not_a_repo.jsonl"))
        ck("非仓库路径 → fail-closed(不得当首次提交放行)", not r["ok"])
        ck("  且理由是无法定位仓库根", any("仓库根" in e or "git" in e for e in r["errors"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(1 for _, c in ok if c)
    print(f"event_ledger selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    path, ref = DEFAULT_PATH, "HEAD"
    for i, a in enumerate(sys.argv):
        if a == "--path" and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
        if a == "--ref" and i + 1 < len(sys.argv):
            ref = sys.argv[i + 1]
    st = verify(path)
    an = verify_anchor(path)
    ao = verify_append_only(path, ref) if "--no-git" not in sys.argv else {"ok": True, "errors": []}
    out = {"chain": st, "anchor": an, "append_only": dict(ao, ref=ref)}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print("不是买卖指令;研究信号,human executes.")
    return 0 if (st["ok"] and an["ok"] and ao["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
