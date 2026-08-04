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
    live_public = os.path.join(live_repo, "public", "data", "v2")
    if os.path.isdir(live_public):
        shutil.copytree(live_public, stage_public)
    else:
        os.makedirs(stage_public, exist_ok=True)
    snapshot = {
        "protected": {
            rel: _tree_hashes(os.path.join(stage_et, rel)) for rel in PROTECTED_DIRS
        }
    }
    atomic_json(os.path.join(run_dir, "staging_input.json"), snapshot)
    return {"repo": stage_repo, "et": stage_et, "public": stage_public}


def verify_protected_inputs(stage_et, run_dir):
    path = os.path.join(run_dir, "staging_input.json")
    with open(path, encoding="utf-8") as fh:
        before = json.load(fh).get("protected") or {}
    errors = []
    for rel in PROTECTED_DIRS:
        after = _tree_hashes(os.path.join(stage_et, rel))
        if after != before.get(rel, {}):
            errors.append(f"受保护输入在 staging 被修改: {rel}")
    return errors


def _allowed_stage_files(stage_et, stage_public):
    files = []
    for rel in sorted(ET_FILES):
        path = os.path.join(stage_et, rel)
        if os.path.isfile(path):
            files.append(("et", rel, path))
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
    protected = verify_protected_inputs(stage["et"], run_dir)
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
