"""Default-off shared attribution and verified read-only projections."""
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
    "scripts/llm/workbench_shared_inputs.py", "scripts/llm/workbench_shared_state.py",
    "scripts/llm/workbench_backup.py", "scripts/llm/workbench_backup_chunks.py",
    "scripts/llm/workbench_shared_jobs.py", "scripts/llm/workbench_shared_worker.py",
    "scripts/llm/workbench_shared_sync.py",
    "scripts/llm/workbench_data_catalog.py", "config/data-source-catalog.v1.json",
    "experiments/data_governance/__init__.py", "experiments/data_governance/catalog.py",
    "experiments/data_governance/call_receipts.py", "experiments/data_governance/health.py",
    "scripts/llm/workbench_earnings_trial.py", "scripts/llm/workbench_research.py",
    "scripts/llm/foundation_research.py", "scripts/llm/foundation_materials.py", "scripts/llm/foundation_cli.py",
    "scripts/llm/foundation_results.py",
    "scripts/llm/workbench_shared_material.py",
    "scripts/llm/foundation_local_store.py", "scripts/llm/foundation_preservation.py",
    "scripts/llm/foundation_sources.py",
    "scripts/llm/workbench_research_library.py",
    "experiments/research_workflows/trial.py", "experiments/research_workflows/evidence.py",
    "experiments/research_workflows/renderers.py", "experiments/research_workflows/smc_annotation.py",
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
    def __init__(self, system: Workspace, *, governance_evidence_enabled=False,
                 research_library_root=None, research_library_hash=None, materials_enabled=False):
        if not system.store.shared_v1 or not system.private_mode:
            raise WorkspaceError("SHARED_PRIVATE_MODE_REQUIRED", 403)
        self.system, self.store = system, system.store
        self._execution_identity = execution_identity(CODE_ROOT)
        self.queue = None
        self.sync = None
        if type(materials_enabled) is not bool:
            raise WorkspaceError('MATERIAL_CONFIGURATION_INVALID', 400)
        self.materials_enabled = materials_enabled
        if type(governance_evidence_enabled) is not bool:
            raise WorkspaceError("GOVERNANCE_CONFIGURATION_INVALID", 400)
        self.governance_evidence_enabled = governance_evidence_enabled
        if (research_library_root is None) != (research_library_hash is None):
            raise WorkspaceError("RESEARCH_LIBRARY_CONFIGURATION_REQUIRED", 400)
        from workbench_research_library import ResearchLibrary
        self.research_library = (ResearchLibrary(research_library_root, research_library_hash)
                                 if research_library_root is not None else None)

    def research_results(self, actor, *, industry_key=None, industry_taxonomy=None,
                         taxonomy_version=None, research_date=None, ts_code=None, page=0):
        from workbench_research_library import projection, ResearchLibrary
        owner = self.identity(actor)
        query = dict(industry_key=industry_key, industry_taxonomy=industry_taxonomy,
                     taxonomy_version=taxonomy_version, research_date=research_date, ts_code=ts_code)
        if not self.materials_enabled:
            return projection(self.research_library, owner=owner,
            code_sha=self._execution_identity['code_sha'], page=page, industry_key=industry_key,
            industry_taxonomy=industry_taxonomy, taxonomy_version=taxonomy_version,
            research_date=research_date, ts_code=ts_code)
        from workbench_shared_jobs import _output_root
        libraries = [self.research_library] if self.research_library else []
        if self.queue:
            archived = 0
            for job in self.queue.jobs():
                if job['kind'] != 'earnings-review' or job['status'] != 'SUCCEEDED': continue
                archived += 1
                if archived > 100: raise WorkspaceError('RESEARCH_LIBRARY_QUERY_CAPACITY', 409)
                detail = self.queue.job(job['job_id'])
                if detail['status'] != 'SUCCEEDED':
                    raise WorkspaceError('RESEARCH_LIBRARY_EVIDENCE_INVALID', 409)
                output = _output_root(self.store.path.parent, job, {'attempt_id': job['attempt_id']}) / 'result'
                libraries.append(ResearchLibrary(output / 'archive', detail['research']['archive_library_hash']))
        class Collection:
            def read(self, **filters):
                views = [library.read(**filters) for library in libraries]
                rows = [row for view in views for row in view['results']]
                return {'results': rows, 'status': 'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED' if rows else 'EMPTY',
                        'library_hash': evidence.sealed([view['library_hash'] for view in views])}
        return projection(Collection(), owner=owner, code_sha=self._execution_identity['code_sha'], page=page, **query)

    def research_inputs(self, actor):
        from workbench_shared_inputs import FrozenInputs
        from workbench_shared_material import SCHEMA
        owner = self.identity(actor)
        if not self.materials_enabled or self.queue is None:
            return {'schema': 'ar.shared-research-inputs.v1', 'enabled': False, 'inputs': [], 'my_workspace': owner}
        with self.store.connect() as db:
            rows = db.execute('SELECT snapshot_id FROM shared_inputs ORDER BY rowid LIMIT 101').fetchall()
        if len(rows) > 100: raise WorkspaceError('MATERIAL_INDEX_CAPACITY', 409)
        inputs, result = FrozenInputs(self.store), []
        for row in rows:
            entry = inputs.verify(row[0])
            if entry['schema'] != SCHEMA: continue
            value = entry['snapshot']
            result.append({key: entry[key] for key in ('snapshot_id', 'input_hash')} | {
                key: value[key] for key in ('company', 'research_date', 'source_cutoff_at', 'pack_hash',
                                            'human_review', 'content_sharing_allowed')})
        return {'schema': 'ar.shared-research-inputs.v1', 'enabled': True, 'inputs': result,
                'my_workspace': owner, 'consumer_code_sha': self._execution_identity['code_sha']}

    @staticmethod
    def _snapshot_id(value):
        try:
            if not isinstance(value, str) or str(uuid.UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError):
            raise WorkspaceError("MATERIAL_SNAPSHOT_INVALID", 400) from None
        return value

    def input_card(self, snapshot_id, actor):
        import workbench_data_catalog as dc
        from workbench_shared_inputs import FrozenInputs
        from experiments.data_governance.catalog import load_catalog
        self._snapshot_id(snapshot_id)
        owner = self.identity(actor)
        try:
            # Per-request verification, never a cached verified projection.
            envelope = FrozenInputs(self.store).verify(snapshot_id)
            root = self.store.path.parent / "governance-evidence"
            registry = dc.load_governance_registry(root) if self.governance_evidence_enabled else None
            health = dc.verify_governance_attachment(envelope, registry=registry,
                                                      root=root if self.governance_evidence_enabled else None)
            card = dc.build_input_card(envelope, catalog=load_catalog(CODE_ROOT / "config/data-source-catalog.v1.json"),
                                       health=health, execution_identity=self._execution_identity)
        except WorkspaceError:
            raise
        except (ValueError, OSError, KeyError, TypeError):
            raise WorkspaceError("DATA_CATALOG_EVIDENCE_INVALID", 409) from None
        return {**card, "my_workspace": owner}

    def materials(self, actor, *, snapshot_id=None, industry_key=None, trade_date=None, ts_code=None, page=0):
        import workbench_data_catalog as dc
        from workbench_shared_inputs import FrozenInputs
        filters = dict(industry_key=industry_key, trade_date=trade_date, ts_code=ts_code, page=page)
        try:
            dc.query_materials({"rows": []}, **filters)
        except (ValueError, TypeError):
            raise WorkspaceError("MATERIAL_QUERY_INVALID", 400) from None
        if snapshot_id is not None: self._snapshot_id(snapshot_id)
        owner = self.identity(actor)
        with self.store.connect() as db:
            registered = [row[0] for row in db.execute("SELECT snapshot_id FROM shared_inputs ORDER BY snapshot_id LIMIT 101")]
        if len(registered) > 100:
            raise WorkspaceError("MATERIAL_INDEX_CAPACITY", 409)
        ids = [snapshot_id] if snapshot_id is not None else registered
        inputs = FrozenInputs(self.store)
        index = {"schema": "ar.material-index.v1", "scope": dc.SCOPE, "rows": [], "issues": [],
                 "missing_material_types": dc.MISSING_TYPES[:], "missing_material_basis": "NOT_INDEXED_IN_THIS_SCOPE"}
        jobs = self._jobs()
        try:
            for sid in ids:
                envelope = inputs.verify(sid)
                if envelope['schema'] != 'ar.shared-input.v1': continue
                verified_jobs = []
                if (trade_date is None or trade_date == envelope["source_trade_date"]) and industry_key is None and ts_code is None:
                    for job in jobs:
                        if job.get("snapshot_id") == sid and job.get("status") == "SUCCEEDED" and job.get("kind") == "snapshot-brief":
                            detail = self.job(job["job_id"], actor)
                            if detail.get("status") != "SUCCEEDED":
                                raise WorkspaceError("MATERIAL_REPORT_UNAVAILABLE", 409)
                            verified_jobs.append(detail)
                part = dc.build_material_index([envelope], verified_jobs)
                index["rows"].extend(part["rows"]); index["issues"].extend(part["issues"])
                if len(index["rows"]) > 50000:
                    raise WorkspaceError("MATERIAL_INDEX_CAPACITY", 409)
            result = dc.query_materials(index, **filters)
        except WorkspaceError:
            raise
        except (ValueError, OSError, KeyError, TypeError):
            raise WorkspaceError("DATA_CATALOG_EVIDENCE_INVALID", 409) from None
        return {**result, "my_workspace": owner, "consumer_code_sha": self._execution_identity["code_sha"],
                "production_authority": False, "trading_authority": False}

    def identity(self, actor: str) -> dict:
        if not isinstance(actor, str) or not actor or len(actor) > 254 or any(ord(c) <= 32 for c in actor):
            raise WorkspaceError("SHARED_ACTOR_REQUIRED", 403)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO shared_workspaces VALUES (?, ?)", (actor, str(uuid.uuid4())))
            row = db.execute("SELECT workspace_id FROM shared_workspaces WHERE login=?", (actor,)).fetchone()
        return {"login": actor, "workspace_id": row[0]}

    def dispatch(self, payload: dict, actor: str) -> dict:
        if self.queue is not None:
            return self.queue.enqueue(payload, actor)
        exact(payload, {"command_id", "kind"})
        identifier(payload["command_id"])
        if not isinstance(payload["kind"], str) or payload["kind"] not in {"observe", "snapshot-brief"}:
            raise WorkspaceError("PRIVATE_OPERATION_DISABLED", 403)
        owner = self.identity(actor)
        with self.store.connect() as db:
            prior = any(event["command_id"] == payload["command_id"] for event in self.system.events(db))
        # Existing requests only reach the executor's actor-bound idempotency check.
        if not prior:
            current = execution_identity(CODE_ROOT)
            # governance-mutation: WORKBENCH_SHARED_EXECUTOR_REVISION
            if current["source_tree_hash"] != self._execution_identity["source_tree_hash"]:
                raise WorkspaceError("EXECUTION_CODE_CHANGED_RESTART_REQUIRED", 409)
        code = self._execution_identity
        binding = {**code, "workspace_id": owner["workspace_id"], "schema_version": SCHEMA,
                   "submitted_at": self.system.clock(), "attempt_id": str(uuid.uuid4()),
                   "input_hash": None, "human_review": "PENDING", "trading_authority": False}
        # governance-mutation: WORKBENCH_SHARED_ACTOR_BINDING
        return self.system.start_job(payload, actor=actor, shared_binding=binding)

    def _legacy_jobs(self):
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
                job["status"] = "INTERRUPTED" if self.queue is not None or actor == "LEGACY_UNATTRIBUTED" else "RUNNING"
                if job["status"] == "INTERRUPTED": job["recovery"] = "LEGACY_NOT_RECOVERABLE"
        return jobs

    def _jobs(self):
        return self._legacy_jobs() + (self.queue.jobs() if self.queue is not None else [])

    def _views(self, jobs, *, verified_inputs=None):
        legacy = [job for job in jobs if not job.get("job_schema")]
        viewed = {job["job_id"]: job for job in self.system.brief_job_views(legacy)}
        if self.queue is not None:
            viewed.update({job["job_id"]: job for job in self.queue.views([job for job in jobs if job.get("job_schema")], verified_inputs=verified_inputs)})
        return [viewed.get(job["job_id"], job) for job in jobs]

    def _metadata(self, job):
        keys = ("job_id", "command_id", "workspace_id", "actor", "kind", "snapshot_id", "input_hash", "source_run_id", "source_trade_date",
                "submitted_at", "code_sha", "source_tree_hash", "schema_version", "status", "attempt_id", "output_hash")
        return {**{key: job.get(key) for key in keys}, "error": (job.get("result") or {}).get("error") or
                ("LEGACY_NOT_RECOVERABLE" if job.get("recovery") == "LEGACY_NOT_RECOVERABLE" else None),
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
            return sorted(rows, key=lambda j: j["submitted_at"], reverse=True)[start:start + PAGE_SIZE]
        my_window, team_window = window(mine), window(jobs)
        latest = [next((job for job in reversed(mine) if job["kind"] == kind), None)
                  for kind in ("observe", "snapshot-brief", "earnings-review")]
        latest = [job for job in latest if job is not None]
        # The memo exists only for this request, never across reads or actors.
        verified_inputs = {}
        selected = {job["job_id"]: job for job in [*my_window, *team_window, *latest]}
        viewed = {job["job_id"]: job for job in self._views(list(selected.values()), verified_inputs=verified_inputs)}
        def metadata(rows):
            return [self._metadata(viewed[job["job_id"]]) for job in rows]
        # Common data reuses the existing bounded observation verifier, without reports/events.
        current = self.system.snapshot()
        common = {"observation": current["observation"], "error": current["observation_error"],
                  "sync_status": "MANUAL_OBSERVE_ONLY", "automatic_sync": False}
        if self.queue is not None:
            common.update(sync_status="EXPLICIT_IMPORT_ONLY", current_snapshot_id=None)
            with self.store.connect() as db:
                latest_input = db.execute("SELECT snapshot_id FROM shared_inputs WHERE json_extract(body, '$.schema')='ar.shared-input.v1' ORDER BY rowid DESC LIMIT 1").fetchone()
            if self.sync is not None:
                state = self.sync.state()
                common.update(sync=state, automatic_sync=True, sync_status=state["status"],
                              error=state["safe_error"], latest_attempt=state["latest_attempt"])
                latest_input = (state["current_snapshot_id"],) if state["current_snapshot_id"] else None
            if latest_input:
                try:
                    envelope = verified_inputs.get(latest_input[0]) or self.queue.inputs.verify(latest_input[0])
                    common.update(current_snapshot_id=envelope["snapshot_id"], input_hash=envelope["input_hash"],
                                  observation=evidence.view(envelope["snapshot"]), validation_scope=envelope["validation_scope"],
                                  source_run_id=envelope["source_run_id"], source_trade_date=envelope["source_trade_date"],
                                  full_nightly_acceptance="NOT_EVALUATED")
                    if self.sync is None: common["error"] = None
                    # governance-mutation: WORKBENCH_SHARED_ATTEMPT_SEPARATION
                    if self.sync is not None:
                        common["observation"]["run_identity"]["latest_attempt"] = state["latest_attempt"] or {
                            "run_id": None, "target_trade_date": None, "report": None, "published": None}
                except (OSError, ValueError):
                    common.update(observation=None, current_snapshot_id=None, error="FROZEN_INPUT_UNAVAILABLE")
            elif self.sync is not None:
                common.update(observation=None, error=common["error"] or "NO_FROZEN_PUBLICATION")
        return {"schema": SCHEMA, "my_workspace": owner, "my_jobs": metadata(my_window), "team_jobs": metadata(team_window),
                "latest_owned_jobs": metadata(latest),
                "owned_commands": {job["command_id"]: {"job_id": job["job_id"]} for job in mine if job.get("command_id")},
                "page": page, "page_size": PAGE_SIZE, "my_total": len(mine), "team_total": len(jobs),
                "common_data": common, "execution_identity": self._execution_identity,
                "sample_purpose": "WORKFLOW_DEBUG", "human_review": "PENDING",
                "production_authority": False, "trading_authority": False}

    def job(self, job_id: str, actor: str) -> dict:
        self.identity(actor)
        identifier(job_id)
        if self.queue is not None:
            with self.store.connect() as db:
                queued = db.execute("SELECT 1 FROM shared_jobs WHERE job_id=?", (job_id,)).fetchone()
            if queued: return self.queue.job(job_id)
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
