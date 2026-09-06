"""Fixed synthetic research replay; no model, production data or human approval.

The subprocess guard is defense in depth for trusted repository code, not an
OS sandbox for hostile code. Never expose this local service to a network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tools/nonprod_workbench/fixtures/research.json"
FIXTURE_SHA256 = "e3e7336a0e79d62e6141f7626144b875346820676cbf8ac5aa2688ed42d9815a"
SCENARIOS = {"complete-replay", "invalid-selection"}
STAGES = ("INPUT", "SCREEN", "PACKET", "U4_RECEIPT", "SEAL_CASE", "PAPER_REPLAY", "FIVE_AXIS", "REVIEW")
MAX_RUNS = 100


class ReplayError(ValueError):
    pass


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"command_id", "scenario"}:
        raise ReplayError("FIXED_REPLAY_FIELDS_REQUIRED")
    if not isinstance(payload["command_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", payload["command_id"]):
        raise ReplayError("REPLAY_ID_INVALID")
    if not isinstance(payload["scenario"], str) or payload["scenario"] not in SCENARIOS:
        raise ReplayError("ONLY_FROZEN_SYNTHETIC_SCENARIOS")


def load_fixture():
    raw = FIXTURE.read_bytes()
    if sha(raw) != FIXTURE_SHA256:
        raise ReplayError("FROZEN_INPUT_HASH_MISMATCH")
    return json.loads(raw)


def boundary():
    return {
        "sample_purpose": "WORKFLOW_DEBUG", "evidence_grade": "SYNTHETIC_NOT_RESEARCH_EVIDENCE",
        "human_approval": False, "claim_allowed": False, "production_authority": False,
        "no_trade_flag": True, "provider_contacted": False, "charged_cny": "0",
    }


def check_boundary(receipt):
    if any(receipt.get(k) != v or type(receipt.get(k)) is not type(v) for k, v in boundary().items()):
        raise ReplayError("REPLAY_AUTHORITY_CHANGED")


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def artifact_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReplayError("REPLAY_ARTIFACT_SYMLINK")
        if path.is_file() and path.name != "receipt.json":
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def install_guard(output):
    """Only this fresh run directory may be written; sockets/processes denied."""
    root = output.resolve()

    def fd_path(fd):
        identity = os.fstat(fd)
        for path in (root, *root.rglob("*")):
            stat = path.stat()
            if (stat.st_dev, stat.st_ino) == (identity.st_dev, identity.st_ino):
                return path
        raise PermissionError("SANDBOX_FD_WRITE_REFUSED")

    def writable(value, dir_fd=-1):
        if isinstance(value, int):
            path = fd_path(value)
        else:
            path = Path(os.fsdecode(value))
            if not path.is_absolute() and dir_fd not in {-1, None}:
                path = fd_path(dir_fd) / path
            path = path.resolve()
        if path != root and root not in path.parents:
            raise PermissionError("SANDBOX_WRITE_REFUSED")

    def audit(event, args):
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "os.fork", "os.posix_spawn"}:
            raise PermissionError("OFFLINE_REPLAY_NETWORK_OR_PROCESS_REFUSED")
        if event == "open":
            path, mode, flags = args
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                writable(path)
        if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
            index = 2 if event in {"os.mkdir", "os.chmod"} else 1
            writable(args[0], args[index] if event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod"} else -1)
        if event in {"os.rename", "os.link", "os.symlink"}:
            writable(args[0])
            writable(args[1])

    sys.addaudithook(audit)


def perform(output, payload):
    """Recompute every stage. Invalid frozen drafts stop, never get repaired."""
    validate_request(payload)
    receipt = {
        "schema": "ar-workbench-research-receipt.v1", **payload, **boundary(),
        "fixture_sha256": FIXTURE_SHA256, "status": "STOP", "stages": [],
    }
    stage = "INPUT"

    def passed(name, evidence):
        receipt["stages"].append({"stage": name, "status": "PASS", "evidence": evidence})

    try:
        frozen = load_fixture()
        params = frozen["params"]
        receipt["as_of"] = params["as_of"]
        passed(stage, {"sha256": FIXTURE_SHA256})
        sys.path.insert(0, str(ROOT / "experiments/research_funnel"))
        import funnel_pipeline as funnel
        import closure_experiment as closure
        import research_cycle as cycle
        import research_method as method
        import five_axis_attribution as attribution

        stage = "SCREEN"
        scan = funnel.build_all_market_scan(
            registry=frozen["registry"], e1_events=frozen["e1"], features=frozen["features"],
            rotation=frozen["rotation"], trade_date=params["as_of"], generated_at=params["scan_at"], channel_top_n=8,
        )
        candidates = funnel.build_candidate_review(
            registry=frozen["registry"], scan=scan, features=frozen["features"],
            trade_date=params["as_of"], generated_at=params["scan_at"], target_size=100,
            slow_bull_quota=3, contrarian_quota=3, control_quota=3,
        )
        queue = funnel.build_deep_research_queue(
            candidate_review=candidates, battery=frozen["battery"], selected_tickers=(),
            trade_date=params["as_of"], generated_at=params["packet_at"],
        )
        projected = funnel.advance_registry(
            registry=frozen["registry"], scan=scan, candidate_review=candidates,
            battery=frozen["battery"], deep_queue=queue, generated_at=params["packet_at"],
        )
        bundle = output / "funnel"
        computed = {"all_market_scan.json": scan, "candidate_review.json": candidates,
                    "deep_research_queue.json": queue, "security_registry_projected.json": projected}
        for name, value in computed.items():
            if value != frozen["expected_bundle"][name]:
                raise ReplayError("SCREEN_DIFFERS_FROM_FROZEN_EXPECTATION")
            write_json(bundle / name, value)
        artifacts = artifact_hashes(bundle)
        manifest = {
            "schema": "ar.research_funnel_bundle", "schema_version": funnel.SCHEMA_VERSION,
            "rule_version": funnel.RULE_VERSION, "as_of": params["as_of"],
            "generated_at": params["packet_at"], "artifacts": artifacts, "bundle_hash": funnel._hash(artifacts),
        }
        write_json(bundle / "manifest.json", manifest)
        closure.load_bundle(bundle)
        passed(stage, {"candidates": len(candidates["rows"]), "bundle_hash": manifest["bundle_hash"]})

        stage = "PACKET"
        packet = closure.build_review_packet(bundle_dir=bundle, battery=frozen["battery"], generated_at=params["packet_at"])
        if packet["packet_hash"] != params["expected_packet_hash"]:
            raise ReplayError("PACKET_DIFFERS_FROM_FROZEN_EXPECTATION")
        write_json(output / "packet.json", packet)
        passed(stage, {"packet_hash": packet["packet_hash"]})

        stage = "U4_RECEIPT"
        selected = frozen["receipt" if payload["scenario"] == "complete-replay" else "rejected_receipt"]
        closure.validate_review_receipt(selected, packet)
        queue, report = closure.run_offline_replay(
            bundle_dir=bundle, battery=frozen["battery"], packet=packet, receipt=selected, generated_at=params["closure_at"],
        )
        closure_dir = output / "closure"
        closure._write_replay_outputs(closure_dir, bundle, frozen["battery"], packet, selected, queue, report)
        closure.verify_result_bundle(closure_dir)
        passed(stage, {"selected_fixture_rows": len(selected["selections"]), "identity": "FIXTURE_NOT_HUMAN_APPROVAL"})

        stage = "SEAL_CASE"
        case = cycle.seal_case(frozen["case_draft"], closure_dir)
        write_json(output / "case.json", case)
        passed(stage, {"sealed_cases": 1, "unreplayed_selected_fixture_rows": len(selected["selections"]) - 1})

        stage = "PAPER_REPLAY"
        bars = cycle.seal_bars(frozen["bars_draft"], case)
        outcomes = method.seal_outcomes(frozen["outcomes_draft"], case["method_registration"])
        outputs = cycle.run_cycle(bundle_dir=closure_dir, case=case, bars=bars, outcomes=outcomes, generated_at=params["cycle_at"])
        cycle_dir = output / "cycle"
        cycle._write_cycle_outputs(cycle_dir, closure_dir, case, bars, outcomes, *outputs)
        verified = cycle.verify_cycle_bundle(cycle_dir, closure_dir)
        passed(stage, {"verification": verified, "settled_data": "FROZEN_SYNTHETIC_BARS_NOT_PROSPECTIVE"})

        stage = "FIVE_AXIS"
        market = attribution.seal_market_evidence(frozen["market_draft"], cycle_dir, closure_dir)
        execution = attribution.seal_execution_evidence(frozen["execution_draft"], cycle_dir, closure_dir)
        axes = attribution.build_attribution(cycle_dir, closure_dir, market_evidence=market,
                                             execution_evidence=execution, generated_at=params["attribution_at"])
        attribution.validate_attribution(axes, cycle_dir, closure_dir, market_evidence=market, execution_evidence=execution)
        write_json(output / "market-evidence.json", market)
        write_json(output / "execution-evidence.json", execution)
        write_json(output / "five-axis.json", axes)
        passed(stage, {"axes": {name: value["status"] for name, value in axes["axes"].items()},
                       "completeness": axes["completeness_status"]})

        stage = "REVIEW"
        review_receipt = cycle.seal_review_receipt(frozen["review_draft"], outputs[3])
        final = cycle.finalize_review(cycle_dir, closure_dir, review_receipt)
        cycle._write_final_outputs(output / "review", cycle_dir, closure_dir, review_receipt, final)
        verified = cycle.verify_final_bundle(output / "review", cycle_dir, closure_dir)
        passed(stage, {"verification": verified, "reviewer": "PREWRITTEN_TEST_FIXTURE_NOT_AUTHENTICATED"})
        receipt["status"] = "COMPLETED_SYNTHETIC_REPLAY"
    except Exception as exc:
        # Exception messages are from pinned inputs/engines, never live secrets.
        receipt["stages"].append({"stage": stage, "status": "STOP", "reason": str(exc)[:500], "error_type": type(exc).__name__})
    receipt["artifacts"] = artifact_hashes(output)
    check_boundary(receipt)
    receipt["receipt_hash"] = sha(encoded(receipt))
    write_json(output / "receipt.json", receipt)
    return receipt


def verify_receipt(directory, receipt):
    check_boundary(receipt)
    if receipt.get("fixture_sha256") != FIXTURE_SHA256:
        raise ReplayError("REPLAY_FIXTURE_BINDING_MISMATCH")
    unsigned = {k: v for k, v in receipt.items() if k != "receipt_hash"}
    if receipt.get("receipt_hash") != sha(encoded(unsigned)):
        raise ReplayError("REPLAY_RECEIPT_HASH_MISMATCH")
    if directory.is_symlink() or receipt.get("artifacts") != artifact_hashes(directory):
        raise ReplayError("REPLAY_ARTIFACT_HASH_MISMATCH")
    stages = receipt.get("stages", [])
    completed = receipt.get("status") == "COMPLETED_SYNTHETIC_REPLAY"
    if completed and ([s.get("stage") for s in stages] != list(STAGES) or any(s.get("status") != "PASS" for s in stages)):
        raise ReplayError("REPLAY_STAGE_RECEIPT_INCOMPLETE")
    if not completed and (receipt.get("status") != "STOP" or not stages or stages[-1].get("status") != "STOP"):
        raise ReplayError("REPLAY_TERMINAL_RECEIPT_INVALID")
    return receipt


def worker_environment(output):
    # Explicit allowlist: no inherited API keys, PYTHONPATH or provider config.
    return {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "AR_OFFLINE": "1",
            "HOME": str(output), "TMPDIR": str(output), "LANG": "C.UTF-8",
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" and "SystemRoot" in os.environ else {})}


def launch(output, payload):
    validate_request(payload)
    if output.is_symlink() or output.exists():
        raise ReplayError("INTERRUPTED_OR_EXISTING_RUN_REFUSED")
    output.mkdir(mode=0o700)
    try:
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--output", str(output),
             "--command-id", payload["command_id"], "--scenario", payload["scenario"]],
            cwd=str(ROOT), env=worker_environment(output), timeout=30,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ReplayError("REPLAY_TIMEOUT_STOP_NO_AUTO_RETRY") from None
    if result.returncode != 0 or not (output / "receipt.json").is_file():
        raise ReplayError("REPLAY_PROCESS_FAILED_STOP_NO_AUTO_RETRY")
    return verify_receipt(output, json.loads((output / "receipt.json").read_text()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    args = parser.parse_args()
    if args.output.is_symlink() or not args.output.is_dir() or any(args.output.iterdir()):
        raise ReplayError("EMPTY_PRIVATE_OUTPUT_DIRECTORY_REQUIRED")
    sys.dont_write_bytecode = True
    install_guard(args.output)
    perform(args.output, {"command_id": args.command_id, "scenario": args.scenario})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
