#!/usr/bin/env python3
"""R-015 不可篡改事件账本 —— 全部簇机制(C5 / R-039 / R-040 / R-041 / R-038)的地基。

C5 §6.2 把本模块列为硬前置:C5 的不可篡改性预设账本本身不可篡改,
在本模块建成前,C5 的一切保证只是纪律而非机制。

三层,每层管一类上一层管不了的事:
  ① 前序哈希链 verify()          — 改写既有行 · 删中间行 · 换序 · 坏行 · 未知字段 ·
                                    非规范序列化 · ts 倒流 · register 重复
  ② 锚点 verify_anchor()          — 尾部截断/替换。**哈希链证明抓不到尾部截断**:
                                    砍掉最后一行后 seq 与 prev 链依然完美自洽。
  ③ git 行前缀 verify_append_only() — 整份重写但自洽 · **账本与锚点被一并删除**
                                    (这两类①②构造上都发现不了:全删之后本地
                                     无从区分"被清空"和"真正第一次运行")

写入持排他 flock:账本将有多个写手,无锁则 preflight 时点状态 ≠ 写入时点状态。
链、锚点、ts、唯一性任一不过则拒绝追加,不在坏账本上叠加。

fail-closed:任何无法解析、无法核验的情形一律 FAIL,不得当作通过。
诚实边界:三层叠加只是提高门槛,不是绝对不可篡改。真正的保证来自已提交的 git 历史,
而 0712 的 git-reset-hard 证明 git 本身在此仓库也不构成 append-only。
不是买卖指令;研究信号,human executes.
"""
import os, sys, json, hashlib, datetime, subprocess

GENESIS_PREV = "0" * 64
OPERATIONAL_TIMEZONE = datetime.timezone(datetime.timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_ledger.jsonl")
ANCHOR_SUFFIX = ".anchor.json"
HASHED_FIELDS = ("seq", "ts", "kind", "id", "payload", "prev")
ALLOWED_FIELDS = set(HASHED_FIELDS) | {"hash"}
# 这些 kind 的 (kind,id) 全账本唯一。事务三段以 transaction_id 为 id,
# 故"同一 txn 重试"在链层就被拒,不依赖上层记得判重。
UNIQUE_KINDS = {"register", "genesis",
                "register_intent", "register_commit", "register_abort",
                "evaluation",
                "evaluation_intent", "evaluation_commit", "evaluation_abort",
                # governance-mutation: U4_LEDGER_EVENT_KIND_UNIQUE
                "u4_decision",
                "publication_migration_intent", "publication_migration_commit",
                "publication_migration_abort"}


def _runtime_timestamp():
    """Return the ledger's legacy naive timestamp in the fixed platform timezone."""
    return (datetime.datetime.now(OPERATIONAL_TIMEZONE)
            .replace(tzinfo=None).isoformat(timespec="seconds"))


def canonical(obj):
    """规范序列化:键排序 · UTF-8 · 无空格分隔 · 拒绝 NaN/Infinity。
    磁盘行与行等值校验都用本函数,故它必须与写盘完全一致。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _fixed_floats(o):
    """C5 §5.3 的浮点定点:仅用于**哈希输入**,不改变写盘内容。
    (旧版把它挂在 json.dumps 的 default= 上 —— 而 default 只对 json 无法序列化的
     类型生效,float 是原生可序列化的,故该函数从未被调用过,定点规范形同虚设。)"""
    if isinstance(o, float):
        return format(o, ".10f")
    if isinstance(o, dict):
        return {k: _fixed_floats(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_fixed_floats(v) for v in o]
    return o


def record_hash(rec):
    """对 HASHED_FIELDS 计算(即移除 hash 字段后),浮点先定点化。"""
    return hashlib.sha256(
        canonical(_fixed_floats({k: rec[k] for k in HASHED_FIELDS})).encode()).hexdigest()


def _read_lines(path):
    if not os.path.exists(path) or os.path.isdir(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [ln for ln in fh.read().splitlines() if ln.strip()]


# ────────────────────────────── ① 哈希链 ──────────────────────────────
def verify(path=DEFAULT_PATH):
    """走链核验。fail-closed:解析失败即 error,不跳过。"""
    errs, lines = [], _read_lines(path)
    prev, prev_ts, seen = GENESIS_PREV, "", set()
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError as e:
            errs.append(f"line{i}: 不可解析 JSON ({e}) —— fail-closed,不跳过")
            return {"ok": False, "n": i, "head": None, "errors": errs}
        if not isinstance(rec, dict):
            errs.append(f"line{i}: 不是对象")
            return {"ok": False, "n": i, "head": None, "errors": errs}
        extra = set(rec) - ALLOWED_FIELDS
        missing = ALLOWED_FIELDS - set(rec)
        if missing or extra:
            # 未知字段不进哈希 ⇒ 可以塞进任意未被证明的内容而哈希不变
            errs.append(f"line{i}: 字段集不符(缺 {sorted(missing)} 多 {sorted(extra)})")
            return {"ok": False, "n": i, "head": None, "errors": errs}
        if ln != canonical(rec):
            errs.append(f"line{i}: 非规范序列化(磁盘行 ≠ canonical(rec))")
        if rec["seq"] != i:
            errs.append(f"line{i}: seq={rec['seq']} 不连续(删除或插入的证据)")
        if rec["prev"] != prev:
            errs.append(f"line{i}: prev 不匹配上一条 hash(链断)")
        if rec["hash"] != record_hash(rec):
            errs.append(f"line{i}: hash 与内容不符(本行被改写)")
        if str(rec["ts"]) < prev_ts:
            errs.append(f"line{i}: ts 倒流({rec['ts']} < {prev_ts})—— 预注册账本里"
                        f"回填过去日期正是首要威胁")
        if rec["kind"] in UNIQUE_KINDS:
            key = (rec["kind"], rec["id"])
            if key in seen:
                errs.append(f"line{i}: {key} 重复(删除后重新登记的形态)")
            seen.add(key)
        prev, prev_ts = rec["hash"], str(rec["ts"])
    return {"ok": not errs, "n": len(lines), "head": (prev if lines else None), "errors": errs}


# ────────────────────────────── ② 锚点 ──────────────────────────────
def _anchor_path(path):
    return path + ANCHOR_SUFFIX


def read_anchor(path=DEFAULT_PATH):
    """返回 (anchor|None, status)。status ∈ absent / corrupt / ok —— 三者必须可区分:
    把"锚点被删/被损坏"和"首次运行"归为同一条路径,等于给攻击者一个关闭本层的开关。"""
    p = _anchor_path(path)
    if not os.path.exists(p):
        return None, "absent"
    try:
        with open(p, encoding="utf-8") as fh:
            a = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None, "corrupt"
    if not isinstance(a, dict) or "n" not in a or "head" not in a:
        return None, "corrupt"
    return a, "ok"


def write_anchor(path, n, head):
    """原子写:先落临时文件再 rename,避免崩在半途留下坏锚点(坏锚点会关闭本层)。"""
    p, tmp = _anchor_path(path), _anchor_path(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"n": n, "head": head,
                   "note": "head 必须仍位于链的第 n-1 条;仅比较条数不足以发现尾部替换"},
                  fh, ensure_ascii=False)
        fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, p)
    dir_fd = os.open(os.path.dirname(os.path.abspath(p)), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def verify_anchor(path=DEFAULT_PATH):
    """尾部截断/替换检测。哈希链自洽 ≠ 没被砍尾巴或换尾巴。"""
    a, status = read_anchor(path)
    st = verify(path)
    if status == "corrupt":
        return {"ok": False, "errors": ["锚点损坏 —— fail-closed(不得当作首次运行放行)"]}
    if status == "absent":
        # 只有账本本身确实还不存在时,"没有锚点"才是合法的首次运行
        if os.path.exists(path) and st["n"] > 0:
            return {"ok": False, "errors": [f"账本已有 {st['n']} 条却无锚点 —— 锚点被删,本层已被关闭"]}
        return {"ok": True, "errors": [], "note": "账本与锚点均不存在(首次运行)"}
    if not st["ok"]:
        return {"ok": False, "errors": ["链本身已损坏:" + "; ".join(st["errors"][:2])]}
    if st["n"] < a["n"]:
        return {"ok": False, "errors": [f"条数减少 {a['n']}→{st['n']}:尾部被截断"]}
    # ★ 核心:锚定的 head 必须仍然位于第 a["n"]-1 条。只比条数会被
    #   「删尾部 k 条 + 重新接上 ≥k 条、锚点一字不动」整个绕过 —— 那正是本层要挡的攻击。
    if a["n"] > 0:
        lines = _read_lines(path)
        try:
            at = json.loads(lines[a["n"] - 1])["hash"]
        except (IndexError, json.JSONDecodeError, KeyError):
            return {"ok": False, "errors": [f"取不到第 {a['n']-1} 条以核对锚定 head —— fail-closed"]}
        if at != a["head"]:
            return {"ok": False,
                    "errors": [f"锚定 head 已不在链上(第 {a['n']-1} 条为 {at[:12]}…,"
                               f"锚点记 {a['head'][:12]}…):尾部被替换"]}
    return {"ok": True, "errors": [], "grew": st["n"] - a["n"]}


# ────────────────────────────── ③ git 行前缀 ──────────────────────────────
def _repo_root(path):
    """worktree 里 .git 是**文件**不是目录,故用 git 自己解析,不手工向上找。"""
    d = os.path.dirname(os.path.realpath(path))
    if not os.path.isdir(d):
        return None
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def verify_append_only(path=DEFAULT_PATH, ref="HEAD"):
    """跨提交 append-only:git 中的旧版本必须是当前文件的**行前缀**。
    ①②都无法发现"整份重写但自洽"——那正是 0712 git-reset-hard 的形态。"""
    if os.path.isdir(path):
        return {"ok": False, "errors": ["路径是目录 —— fail-closed"]}
    repo = _repo_root(path)
    if repo is None:
        return {"ok": False, "errors": ["无法定位 git 仓库根 —— fail-closed(不得当作首次提交放行)"]}
    # 两侧都取 realpath:macOS 的 /var → /private/var 等符号链接会让
    # git rev-parse(已解析)与 os.path.abspath(未解析)对不上,
    # relpath 算出 ../../.. 的越界路径 ⇒ 每次都 fail-closed 误报红。
    # 误报的下场是这个检查被人关掉,所以它和漏报同样要命。
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo))
    try:
        old = subprocess.run(["git", "-C", repo, "show", f"{ref}:{rel}"],
                             capture_output=True, text=True, timeout=20)
    except Exception as e:
        return {"ok": False, "errors": [f"git 调用失败: {e} —— fail-closed"]}
    if old.returncode != 0:
        # 只有"该 ref 下确实没有此路径"才算首次提交;其余一切 git 错误 fail-closed。
        # (旧版 bug:worktree 里 .git 是文件,_repo_root 走到 /,git 失败被当成首次提交
        #  ⇒ 整个跨提交闸门 fail-open,实测五类跨提交篡改全部被放行。)
        err = (old.stderr or "").lower()
        if "exists on disk, but not in" in err or "does not exist" in err:
            return {"ok": True, "errors": [], "note": f"{ref} 中尚无该文件(首次提交)"}
        return {"ok": False,
                "errors": [f"git show 失败(rc={old.returncode}): {old.stderr.strip()[:120]} —— fail-closed"]}
    o = [ln for ln in old.stdout.splitlines() if ln.strip()]
    c = _read_lines(path)
    if len(c) < len(o):
        return {"ok": False, "errors": [f"行数减少 {len(o)}→{len(c)}:有记录被删除"]}
    bad = [i for i in range(len(o)) if o[i] != c[i]]
    if bad:
        return {"ok": False, "errors": [f"既有行被改写(首个差异在 line{bad[0]},共 {len(bad)} 行)"]}
    return {"ok": True, "errors": [], "appended": len(c) - len(o)}


# ────────────────────────────── 写入 ──────────────────────────────
def append(kind, rec_id, payload, path=DEFAULT_PATH, now=None):
    """持排他 flock 追加。写前链与锚点都必须过,否则拒写(不在坏账本上叠加)。"""
    import fcntl
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            st = verify(path)
            if not st["ok"]:
                raise ValueError(f"账本已损坏,拒绝追加: {st['errors'][:2]}")
            an = verify_anchor(path)
            if not an["ok"]:
                raise ValueError(f"账本与锚点不符,拒绝追加: {an['errors']}")
            ts = now or _runtime_timestamp()
            lines = _read_lines(path)
            if lines and str(ts) < str(json.loads(lines[-1])["ts"]):
                raise ValueError(f"ts 早于链尾({ts} < {json.loads(lines[-1])['ts']}),拒绝回填过去日期")
            if kind in UNIQUE_KINDS:
                for ln in lines:
                    r = json.loads(ln)
                    if r["kind"] == kind and r["id"] == rec_id:
                        raise ValueError(f"({kind},{rec_id}) 已存在,拒绝重复登记")
            rec = {"seq": st["n"], "kind": kind, "id": rec_id, "payload": payload,
                   "ts": ts, "prev": st["head"] or GENESIS_PREV}
            rec["hash"] = record_hash(rec)
            line = canonical(rec)                      # 与 verify 的行等值校验同一函数
            # 整份临时文件替换,避免 append 在进程崩溃时留下半行 JSON。
            # ledger 已替换而 anchor 尚未来得及更新是安全的:verify_anchor 会确认
            # 旧 anchor head 仍在链上,下一次写入再推进 anchor。
            tmp = path + ".append.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for old_line in lines:
                    fh.write(old_line + "\n")
                fh.write(line + "\n")
                fh.flush(); os.fsync(fh.fileno())
            os.replace(tmp, path)
            dir_fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            write_anchor(path, st["n"] + 1, rec["hash"])
            return rec
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


# ────────────────────────────── selftest ──────────────────────────────
def selftest():
    """按本季教训:自查工具必须先被证明"会失败",才配被信任。
    三层各自都必须有"关掉它就会红"的断言 —— 否则那一层等于没测。"""
    import tempfile, shutil
    ok = []
    def ck(name, cond): ok.append((name, cond)); print(f"  {'✓' if cond else '✗'} {name}")
    def overwrite(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    d = tempfile.mkdtemp(); p = os.path.join(d, "t.jsonl")
    try:
        for i in range(4):
            append("register", f"sig{i}", {"ticker": f"00000{i}.SZ", "px": 1.5},
                   path=p, now=f"2026-08-0{i+1}T15:00:00")
        ck("干净账本 4 条 → ok", verify(p)["ok"] and verify(p)["n"] == 4)

        def mut(fn, keep_anchor=True):
            q = os.path.join(d, "m.jsonl")
            for s in (q, _anchor_path(q)):
                if os.path.exists(s): os.remove(s)
            shutil.copy(p, q)
            if keep_anchor: shutil.copy(_anchor_path(p), _anchor_path(q))
            ls = fn(_read_lines(q))
            overwrite(q, ("\n".join(ls) + "\n") if ls else "")
            return q

        # ── ① 哈希链 ──
        ck("删中间一行 → 链抓到", not verify(mut(lambda l: l[:1] + l[2:]))["ok"])
        def edit(l):
            o = json.loads(l[1]); o["payload"]["ticker"] = "999999.SZ"; l[1] = canonical(o); return l
        ck("改内容不改 hash → 链抓到", not verify(mut(edit))["ok"])
        def rehash(l):
            o = json.loads(l[1]); o["payload"]["ticker"] = "999999.SZ"
            o["hash"] = record_hash(o); l[1] = canonical(o); return l
        ck("改内容并重算 hash → 链抓到(prev 断)", not verify(mut(rehash))["ok"])
        ck("调换顺序 → 链抓到", not verify(mut(lambda l: [l[0], l[2], l[1], l[3]]))["ok"])
        ck("坏行 → 链 fail-closed 抓到", not verify(mut(lambda l: l + ["{不是JSON"]))["ok"])
        def unknown(l):
            o = json.loads(l[1]); o["status"] = "cancelled"; l[1] = canonical(o); return l
        ck("塞未知字段(hash 不变)→ 链抓到", not verify(mut(unknown))["ok"])
        def noncanon(l):
            o = json.loads(l[1])
            l[1] = json.dumps(o, ensure_ascii=False, separators=(", ", ": ")); return l
        ck("非规范序列化 → 链抓到", not verify(mut(noncanon))["ok"])
        def backdate(l):
            o = json.loads(l[2]); o["ts"] = "2020-01-01T00:00:00"
            o["hash"] = record_hash(o); l[2] = canonical(o); return l
        ck("ts 倒流 → 链抓到", not verify(mut(backdate))["ok"])
        def dup(l):
            o = json.loads(l[3]); o["id"] = "sig0"; o["hash"] = record_hash(o)
            l[3] = canonical(o); return l
        ck("register 重复 id → 链抓到", not verify(mut(dup))["ok"])

        # ── ② 锚点(链证明抓不到的那些)──
        q = mut(lambda l: l[:-1])
        ck("删最后一行 → 链自洽(诚实承认此边界)", verify(q)["ok"])
        ck("删最后一行 → 锚点抓到", not verify_anchor(q)["ok"])
        def forge(l):                       # 删尾 2 条 + 重接 3 条,锚点一字不动
            prev = json.loads(l[1])["hash"]; out = l[:2]
            for i in range(3):
                r = {"seq": 2 + i, "kind": "note", "id": f"F{i}", "payload": {},
                     "ts": "2026-08-09T15:00:00", "prev": prev}
                r["hash"] = record_hash(r); prev = r["hash"]; out.append(canonical(r))
            return out
        q2 = mut(forge)
        ck("删尾重接使 n 变大 → 链自洽", verify(q2)["ok"])
        ck("删尾重接使 n 变大 → 锚点抓到(核对锚定 head 仍在第 n-1 条)",
           not verify_anchor(q2)["ok"])
        q3 = mut(lambda l: l[:-1]); os.remove(_anchor_path(q3))
        ck("截断并删掉锚点 → 仍抓到(不得当首次运行)", not verify_anchor(q3)["ok"])
        q4 = mut(lambda l: l[:-1]); overwrite(_anchor_path(q4), "{坏")
        ck("截断并损坏锚点 → 仍抓到", not verify_anchor(q4)["ok"])
        q5 = mut(lambda l: [], keep_anchor=True); os.remove(q5)
        ck("删账本但锚点还在 → 锚点抓到", not verify_anchor(q5)["ok"])
        # 账本与锚点一并删除:①②构造上必然放行(本地无从区分全删与首次运行),
        # 必须由第③层接住 —— 与"尾部截断由锚点接住"同款,如实写出而非粉饰。
        gw = os.path.join(d, "wipe")
        os.makedirs(gw); subprocess.run(["git", "init", "-q", gw], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", gw, "config", k, v], check=True)
        wp = os.path.join(gw, "led.jsonl")
        for i in range(3):
            append("register", f"w{i}", {}, path=wp, now=f"2026-08-0{i+1}T15:00:00")
        subprocess.run(["git", "-C", gw, "add", "-A"], check=True)
        subprocess.run(["git", "-C", gw, "commit", "-qm", "s"], check=True)
        os.remove(wp); os.remove(_anchor_path(wp))
        ck("账本与锚点全删 → ①②放行(诚实承认此边界)",
           verify(wp)["ok"] and verify_anchor(wp)["ok"])
        ck("账本与锚点全删 → 第③层抓到", not verify_append_only(wp, "HEAD")["ok"])

        # ── push 事件形态:基准是**父提交**,两侧都是 commit(而非工作树 vs commit)──
        # 父提交 3 行 → 当前提交重写成 4 行(更长但非前缀)⇒ 必须失败。
        # 上一版 CI 在 push 到 main 时用 origin/main 作基准,那就是刚推上去的提交本身,
        # 比较恒等 ⇒ 整步空转。本条断言把"基准必须是父提交"这件事钉死。
        gpush = os.path.join(d, "pushrepo")
        os.makedirs(gpush); subprocess.run(["git", "init", "-q", gpush], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", gpush, "config", k, v], check=True)
        pp = os.path.join(gpush, "led.jsonl")
        for i in range(3):
            append("register", f"p{i}", {}, path=pp, now=f"2026-08-0{i+1}T15:00:00")
        subprocess.run(["git", "-C", gpush, "add", "-A"], check=True)
        subprocess.run(["git", "-C", gpush, "commit", "-qm", "parent(3 lines)"], check=True)
        parent = subprocess.run(["git", "-C", gpush, "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        os.remove(pp); os.remove(_anchor_path(pp))          # 整份重写成 4 行
        for i in range(4):
            append("register", f"q{i}", {}, path=pp, now=f"2026-08-0{i+1}T15:00:00")
        subprocess.run(["git", "-C", gpush, "add", "-A"], check=True)
        subprocess.run(["git", "-C", gpush, "commit", "-qm", "current(4 rewritten)"], check=True)
        ck("push形态:父提交3行 vs 当前重写4行 → 抓到",
           not verify_append_only(pp, parent)["ok"])
        ck("push形态:与自身提交比 → 恒等放行(这正是固定用 origin/main 的空转形态)",
           verify_append_only(pp, "HEAD")["ok"])
        subprocess.run(["git", "-C", gpush, "commit", "-q", "--allow-empty", "-m", "next"], check=True)
        append("register", "q4", {}, path=pp, now="2026-08-09T15:00:00")
        ck("push形态:纯追加 vs 父提交 → 放行", verify_append_only(pp, "HEAD")["ok"])
        for q6 in (q, q2, q3, q4):
            pass
        try:
            append("note", "z", {}, path=q2); blocked = False
        except ValueError:
            blocked = True
        ck("被伪造的账本上追加 → 拒写(不洗白成新锚点)", blocked)

        # ── ③ git 行前缀(必须有"关掉就红"的断言,否则这一层等于没测)──
        g = os.path.join(d, "repo")
        os.makedirs(g); subprocess.run(["git", "init", "-q", g], check=True)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", g, "config", k, v], check=True)
        gp = os.path.join(g, "led.jsonl")
        for i in range(3):
            append("register", f"g{i}", {}, path=gp, now=f"2026-08-0{i+1}T15:00:00")
        subprocess.run(["git", "-C", g, "add", "-A"], check=True)
        subprocess.run(["git", "-C", g, "commit", "-qm", "seed"], check=True)
        ck("git层:未改动 → 放行", verify_append_only(gp, "HEAD")["ok"])
        base = _read_lines(gp)
        overwrite(gp, "\n".join(base[:-1]) + "\n")
        ck("git层:尾部截断 → 抓到", not verify_append_only(gp, "HEAD")["ok"])
        o = json.loads(base[1]); o["payload"]["x"] = 1; o["hash"] = record_hash(o)
        overwrite(gp, "\n".join([base[0], canonical(o)] + base[2:]) + "\n")
        ck("git层:改写既有行 → 抓到", not verify_append_only(gp, "HEAD")["ok"])
        w = os.path.join(d, "whole.jsonl")
        for i in range(5):
            append("register", f"w{i}", {}, path=w, now="2026-08-01T15:00:00")
        shutil.copy(w, gp)
        ck("git层:整份重写但自洽且更长 → 抓到(①②都发现不了)",
           not verify_append_only(gp, "HEAD")["ok"])
        overwrite(gp, "\n".join(base) + "\n")
        ck("git层:恢复 → 放行", verify_append_only(gp, "HEAD")["ok"])
        ck("git层:非仓库路径 → fail-closed", not verify_append_only(os.path.join(d, "x.jsonl"))["ok"])
        # 符号链接回归:macOS tempdir 本身就是 /var→/private/var 的软链,
        # 上面几条 git 层断言只要 realpath 处理错了就会集体转红。此条把它钉死。
        ck("git层:路径含符号链接时 repo/rel 解析正确",
           os.path.relpath(os.path.realpath(gp), os.path.realpath(_repo_root(gp))) == "led.jsonl")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(1 for _, c in ok if c)
    print(f"event_ledger selftest: {passed}/{len(ok)}")
    return passed == len(ok)


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1
    path, ref, skip_git = DEFAULT_PATH, "HEAD", "--no-git" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--path" and i + 1 < len(sys.argv): path = sys.argv[i + 1]
        if a == "--ref" and i + 1 < len(sys.argv): ref = sys.argv[i + 1]
    st, an = verify(path), verify_anchor(path)
    ao = ({"ok": True, "skipped": True, "errors": [],
           "warning": "--no-git:第③层未运行,本次结果不构成 append-only 保证"}
          if skip_git else dict(verify_append_only(path, ref), ref=ref))
    print(json.dumps({"chain": st, "anchor": an, "append_only": ao}, ensure_ascii=False, indent=1))
    print("不是买卖指令;研究信号,human executes.")
    return 0 if (st["ok"] and an["ok"] and ao["ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
