"""Default-off S1 attribution and read-only shared projections; no queue/sync."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import workbench_evidence as evidence
from workbench_workspace import Workspace, WorkspaceError, exact, identifier, projection

CODE_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "ar.shared-workspace.v1"
PAGE_SIZE = 50
EXECUTION_FILES = (
    "scripts/llm/nonprod_workbench.py", "scripts/llm/workbench_shared_workspace.py",
    "scripts/llm/workbench_workspace.py", "scripts/llm/workbench_evidence.py",
    "scripts/llm/workbench_snapshot_brief.py", "scripts/llm/workbench_brief_trial.py",
    "scripts/llm/workbench_earnings_trial.py", "scripts/llm/workbench_research.py",
    "scripts/llm/adapters/base.py", "scripts/llm/adapters/deepseek.py",
    "scripts/llm/adapters/__init__.py", "scripts/llm/adapters/deterministic.py",
    "scripts/llm/ai_os/__init__.py", "scripts/llm/ai_os/skill_registry.py",
    "scripts/team_ai_workspace.py", "experiments/research_funnel/research_trust_view.py",
    "experiments/macro_os/collectors.py", "experiments/macro_os/contracts.py",
    "experiments/macro_os/m1a.py",
    "experiments/macro_os/__init__.py", "experiments/macro_os/storage.py",
    "experiments/macro_os/official_releases.py",
)


def execution_identity(root: Path) -> dict:
    def git(*args):
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
        if result.returncode:
            raise WorkspaceError("EXECUTION_IDENTITY_UNAVAILABLE", 409)
        return result.stdout

    if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != root.resolve():
        raise WorkspaceError("EXECUTION_IDENTITY_UNAVAILABLE", 409)
    code_sha = git("rev-parse", "HEAD").decode().strip()
    hashes = {}
    for name in EXECUTION_FILES:
        path = root / name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise WorkspaceError("EXECUTION_SOURCE_INVALID", 409)
        raw = path.read_bytes()
        # governance-mutation: WORKBENCH_SHARED_EXECUTION_IDENTITY
        if raw != git("show", code_sha + ":" + name):
            raise WorkspaceError("EXECUTION_CODE_DIRTY", 409)
        hashes[name] = evidence.sha(raw)
    if git("rev-parse", "HEAD").decode().strip() != code_sha:
        raise WorkspaceError("EXECUTION_CODE_CHANGED", 409)
    return {"code_sha": code_sha, "source_tree_hash": evidence.sealed(hashes)}


class SharedWorkspace:
    def __init__(self, system: Workspace):
        if not system.store.shared_v1 or not system.private_mode:
            raise WorkspaceError("SHARED_PRIVATE_MODE_REQUIRED", 403)
        self.system, self.store = system, system.store

    def identity(self, actor: str) -> dict:
        if not isinstance(actor, str) or not actor or len(actor) > 254 or any(ord(c) <= 32 for c in actor):
            raise WorkspaceError("SHARED_ACTOR_REQUIRED", 403)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO shared_workspaces VALUES (?, ?)", (actor, str(uuid.uuid4())))
            row = db.execute("SELECT workspace_id FROM shared_workspaces WHERE login=?", (actor,)).fetchone()
        return {"login": actor, "workspace_id": row[0]}

    def dispatch(self, payload: dict, actor: str) -> dict:
        exact(payload, {"command_id", "kind"})
        identifier(payload["command_id"])
        if not isinstance(payload["kind"], str) or payload["kind"] not in {"observe", "snapshot-brief"}:
            raise WorkspaceError("PRIVATE_OPERATION_DISABLED", 403)
        owner = self.identity(actor)
        code = execution_identity(CODE_ROOT)
        binding = {**code, "workspace_id": owner["workspace_id"], "schema_version": SCHEMA,
                   "submitted_at": self.system.clock(), "attempt_id": str(uuid.uuid4()),
                   "input_hash": None, "human_review": "PENDING", "trading_authority": False}
        # governance-mutation: WORKBENCH_SHARED_ACTOR_BINDING
        return self.system.start_job(payload, actor=actor, shared_binding=binding)

    def _jobs(self):
        with self.store.connect() as db:
            events = self.system.events(db)
            identities = dict(db.execute("SELECT login, workspace_id FROM shared_workspaces"))
        jobs = projection(events)["jobs"]
        started = {e["data"]["job_id"]: e for e in events if e["kind"] == "JOB_STARTED"}
        for job in jobs:
            actor = job.get("actor", "LEGACY_UNATTRIBUTED")
            job.update(actor=actor, workspace_id=job.get("workspace_id", identities.get(actor)),
                       submitted_at=job.get("submitted_at", started[job["job_id"]]["at"]))
            if job["status"] == "STARTED":
                job["status"] = "INTERRUPTED" if actor == "LEGACY_UNATTRIBUTED" else "RUNNING"
        return jobs

    def _metadata(self, job):
        keys = ("job_id", "workspace_id", "actor", "kind", "input_hash", "source_run_id", "source_trade_date",
                "submitted_at", "code_sha", "source_tree_hash", "schema_version", "status", "attempt_id", "output_hash")
        return {**{key: job.get(key) for key in keys}, "error": (job.get("result") or {}).get("error"),
                "sample_purpose": "WORKFLOW_DEBUG", "human_review": "PENDING",
                "production_authority": False, "trading_authority": False}

    def snapshot(self, actor: str, *, page: int = 0) -> dict:
        owner = self.identity(actor)
        if type(page) is not int or not 0 <= page <= 999:
            raise WorkspaceError("SHARED_PAGE_INVALID")
        jobs = self._jobs()
        mine = [j for j in jobs if j["actor"] == actor]
        start = page * PAGE_SIZE
        def window(rows):
            selected = sorted(rows, key=lambda j: j["submitted_at"], reverse=True)[start:start + PAGE_SIZE]
            return [self._metadata(j) for j in self.system.brief_job_views(selected)]
        # Common data reuses the existing bounded observation verifier, without reports/events.
        current = self.system.snapshot()
        latest = [next((job for job in reversed(mine) if job["kind"] == kind), None)
                  for kind in ("observe", "snapshot-brief")]
        latest = self.system.brief_job_views([job for job in latest if job is not None])
        return {"schema": SCHEMA, "my_workspace": owner, "my_jobs": window(mine), "team_jobs": window(jobs),
                "latest_owned_jobs": [self._metadata(job) for job in latest],
                "page": page, "page_size": PAGE_SIZE, "my_total": len(mine), "team_total": len(jobs),
                "common_data": {"observation": current["observation"], "error": current["observation_error"],
                                "sync_status": "MANUAL_OBSERVE_ONLY", "automatic_sync": False},
                "sample_purpose": "WORKFLOW_DEBUG", "human_review": "PENDING",
                "production_authority": False, "trading_authority": False}

    def job(self, job_id: str, actor: str) -> dict:
        self.identity(actor)
        identifier(job_id)
        registered = next((j for j in self._jobs() if j["job_id"] == job_id), None)
        if registered is None:
            raise WorkspaceError("SHARED_JOB_NOT_FOUND", 404)
        job = self.system.brief_job_views([registered])[0]
        detail = {**self._metadata(job), "result": job.get("result")}
        if job["kind"] == "snapshot-brief" and job["status"] == "SUCCEEDED":
            import workbench_snapshot_brief as brief
            output = self.system.output_root(job) / "snapshot-briefs" / job_id
            receipt = brief.verify(output)
            report = evidence.read_local(output, "report.md")
            citations = evidence.read_local(output, "citations.json")
            if (evidence.sha(report) != receipt["files"]["report.md"]
                    or evidence.sha(citations) != receipt["files"]["citations.json"]):
                raise WorkspaceError("SHARED_REPORT_CHANGED", 409)
            detail.update(report=report.decode("utf-8"), citations=json.loads(citations))
        return detail
