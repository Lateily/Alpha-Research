"""Bounded, clean-environment rendering of registered frozen shared inputs."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench_evidence as ev
import workbench_snapshot_brief as brief
from workbench_backup import durable_directory, fsync_directory, write_new
from workbench_shared_inputs import validate_snapshot
from workbench_workspace import WorkspaceError

KINDS = frozenset({"observe", "snapshot-brief"})
SEAL_SCHEMA = "ar.shared-job-output.v1"
BINDING_FIELDS = ("job_id", "workspace_id", "actor", "kind", "snapshot_id", "input_hash",
                  "code_sha", "source_tree_hash", "schema_version", "job_schema", "input_schema",
                  "source_run_id", "source_trade_date")


def _arm_deadline(seconds=120):
    if os.getpgrp() != os.getpid():
        raise WorkspaceError("SHARED_CHILD_PROCESS_GROUP_REQUIRED", 409)
    # This deadline survives loss of the trusted parent coordinator.
    def expire():
        time.sleep(seconds)
        os.killpg(os.getpgrp(), signal.SIGKILL)
    threading.Thread(target=expire, daemon=True).start()


def run_bounded(argv: list[str], env: dict, cwd: Path, timeout_seconds: float = 120) -> dict:
    allowed = {key: value for key, value in env.items() if key in {"PATH", "LANG", "LC_ALL"}}
    allowed.update(AR_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(cwd))
    process = None
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=allowed, shell=False,
                                   start_new_session=True, close_fds=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # governance-mutation: WORKBENCH_SHARED_WORKER_TIMEOUT
            code = process.wait(timeout=min(timeout_seconds, 120))
        except subprocess.TimeoutExpired:
            return {"status": "STOP", "error": "WORKER_TIMEOUT"}
        return {"status": "SUCCEEDED"} if code == 0 else {"status": "STOP", "error": "WORKER_RENDER_FAILED"}
    except (OSError, ValueError):
        return {"status": "STOP", "error": "WORKER_START_FAILED"}
    finally:
        if process is not None:
            # Kill descendants even if the immediate child already exited.
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()


def _render_child(kind, frozen_root, output_root):
    if kind not in KINDS:
        raise WorkspaceError("SHARED_RENDERER_DISABLED", 403)
    spec = ev.parse(ev.read_local(output_root, "input.json"))
    if (set(spec) != {"kind", "snapshot", "input_hash"} or spec["kind"] != kind
            or spec["input_hash"] != spec["snapshot"].get("frozen_input_hash")):
        raise WorkspaceError("SHARED_RENDER_INPUT_INVALID", 409)
    snapshot = spec["snapshot"]
    validate_snapshot(snapshot, frozen_root, sealed_originals=True)
    if kind == "snapshot-brief":
        brief.run_frozen(snapshot, frozen_root, output_root / "staging")
    else:
        durable_directory(output_root / "staging")
        write_new(output_root / "staging/observation.json", ev.canonical(snapshot).encode())


def _output_result(kind, directory, snapshot):
    if kind == "snapshot-brief":
        receipt = brief.verify(directory)
        if ev.parse(ev.read_local(directory, "snapshot.json")) != snapshot:
            raise WorkspaceError("SHARED_OUTPUT_INPUT_CONFLICT", 409)
        return {"status": "SUCCEEDED", "output_hash": receipt["files"]["report.md"],
                "snapshot_hash": receipt["snapshot_hash"], "report_sha256": receipt["files"]["report.md"]}
    observation = ev.verify(ev.parse(ev.read_local(directory, "observation.json")))
    if observation != snapshot:
        raise WorkspaceError("SHARED_OUTPUT_INPUT_CONFLICT", 409)
    return {"status": "SUCCEEDED", "output_hash": observation["snapshot_hash"],
            "snapshot_hash": observation["snapshot_hash"]}


def _files(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise WorkspaceError("SHARED_OUTPUT_PATH_INVALID", 409)
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            result[name] = ev.sha(ev.read_local(directory, name))
    return result


def verify_seal(output_root: Path, job: dict, attempt: dict, envelope: dict, *, publish=False) -> dict:
    output_root = Path(output_root)
    seal = ev.parse(ev.read_local(output_root, "seal.json"))
    expected_binding = {key: job[key] for key in BINDING_FIELDS}
    expected_binding.update(attempt_id=attempt["attempt_id"], token_hash=attempt["token_hash"])
    if (set(seal) != {"schema", "binding", "files", "result", "seal_hash"}
            or seal["schema"] != SEAL_SCHEMA or seal["binding"] != expected_binding
            or seal["seal_hash"] != ev.sealed({k: v for k, v in seal.items() if k != "seal_hash"})):
        raise WorkspaceError("SHARED_OUTPUT_SEAL_CONFLICT", 409)
    if envelope["input_hash"] != job["input_hash"] or envelope["schema"] != job["input_schema"]:
        raise WorkspaceError("SHARED_OUTPUT_INPUT_CONFLICT", 409)
    staging, final = output_root / "staging", output_root / "result"
    if staging.exists() == final.exists():
        raise WorkspaceError("SHARED_OUTPUT_PUBLICATION_CONFLICT", 409)
    directory = final if final.exists() else staging
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise WorkspaceError("SHARED_OUTPUT_PATH_INVALID", 409)
    actual_result = _output_result(job["kind"], directory, envelope["snapshot"])
    # governance-mutation: WORKBENCH_SHARED_RECOVERY_SEAL
    if _files(directory) != seal["files"] or actual_result != seal["result"]:
        raise WorkspaceError("SHARED_OUTPUT_SEAL_CONFLICT", 409)
    if publish and directory == staging:
        os.rename(staging, final)
        fsync_directory(output_root)
    return {**actual_result, "seal_hash": seal["seal_hash"]}


def run_attempt(claim: dict) -> dict:
    try:
        if claim.get("kind") not in KINDS:
            raise WorkspaceError("SHARED_RENDERER_DISABLED", 403)
        output = Path(claim["output_root"])
        if output.exists() or output.is_symlink():
            raise WorkspaceError("SHARED_ATTEMPT_DIRECTORY_EXISTS", 409)
        durable_directory(output)
        spec = {"kind": claim["kind"], "snapshot": claim["envelope"]["snapshot"], "input_hash": claim["input_hash"]}
        write_new(output / "input.json", ev.canonical(spec).encode())
        script = Path(claim["code_root"]) / "scripts/llm/workbench_shared_worker.py"
        result = run_bounded([sys.executable, "-I", "-B", str(script), "--render", claim["kind"],
                              str(claim["frozen_root"]), str(output)],
                             {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}, output)
        if result["status"] != "SUCCEEDED": return result
        directory = output / "staging"
        result = _output_result(claim["kind"], directory, claim["envelope"]["snapshot"])
        catalog = _files(directory)
        for name in catalog:
            fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW)
            try: os.fsync(fd)
            finally: os.close(fd)
        for path in sorted((p for p in directory.rglob("*") if p.is_dir()), reverse=True): fsync_directory(path)
        fsync_directory(directory)
        binding = {key: claim[key] for key in BINDING_FIELDS}
        binding.update(attempt_id=claim["attempt_id"], token_hash=ev.sha(claim["token"].encode()))
        seal = {"schema": SEAL_SCHEMA, "binding": binding, "files": catalog, "result": result}
        seal["seal_hash"] = ev.sealed(seal)
        write_new(output / "seal.json", ev.canonical(seal).encode())
        return verify_seal(output, claim, {"attempt_id": claim["attempt_id"], "token_hash": binding["token_hash"]}, claim["envelope"], publish=True)
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "STOP", "error": "WORKER_OUTPUT_INVALID"}


class SharedWorker:
    def __init__(self, queue):
        self.queue = queue
        self.stopping = threading.Event()
        self.threads = []

    def start(self) -> None:
        if self.threads: return
        self.queue.recover()
        self.threads = [threading.Thread(target=self._work, name=f"shared-render-{slot}", daemon=True) for slot in range(2)]
        for thread in self.threads: thread.start()

    def _work(self):
        claim, result = None, None
        while not self.stopping.is_set():
            try:
                if claim is None: claim = self.queue.claim()
                if claim is None:
                    self.stopping.wait(.2); continue
                if result is None: result = run_attempt(claim)
                self.queue.finish(claim, result)
                claim, result = None, None
            except sqlite3.Error:
                # Keep the sealed result while a backup or writer owns SQLite.
                self.stopping.wait(.2)
            except (OSError, ValueError):
                claim, result = None, None
                self.stopping.wait(.2)

    def stop(self) -> None:
        self.stopping.set()
        for thread in self.threads: thread.join()


if __name__ == "__main__":
    try:
        if len(sys.argv) != 5 or sys.argv[1] != "--render": raise ValueError
        _arm_deadline()
        _render_child(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    except Exception:
        raise SystemExit(2)
