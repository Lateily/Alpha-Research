"""Run the existing earnings renderer over operator-frozen historical requests."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path


class EarningsTrialError(ValueError):
    pass


MAX_REQUESTS = 5
MAX_REQUEST_BYTES = 1_000_000
MAX_REPORT_BYTES = 128_000
REQUEST_NAME = re.compile(r"earnings-([0-9]{6}\.(?:SZ|SH|BJ))\.json")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EarningsTrialError("EARNINGS_REQUEST_DUPLICATE_FIELD")
        result[key] = value
    return result


def _nonfinite(_):
    raise EarningsTrialError("EARNINGS_REQUEST_NONFINITE")


def run(pack_root: Path, output_root: Path) -> dict:
    """HTTP supplies no ticker or path; the operator fixes one pack at startup."""
    pack_root = Path(pack_root)
    requests_root = pack_root / "requests"
    inputs_root = pack_root / "inputs"
    if (pack_root.is_symlink() or requests_root.is_symlink() or inputs_root.is_symlink()
            or not requests_root.is_dir() or not inputs_root.is_dir()):
        raise EarningsTrialError("FROZEN_EARNINGS_PACK_UNAVAILABLE")
    paths = sorted(requests_root.glob("earnings-*"))
    if not 1 <= len(paths) <= MAX_REQUESTS:
        raise EarningsTrialError("FROZEN_EARNINGS_REQUEST_COUNT_INVALID")

    module_root = str(Path(__file__).resolve().parents[2])
    if module_root not in sys.path:
        sys.path.insert(0, module_root)
    from experiments.research_workflows import trial

    prepared = []
    for path in paths:
        match = REQUEST_NAME.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise EarningsTrialError("FROZEN_EARNINGS_REQUEST_INVALID")
        raw = path.read_bytes()
        if len(raw) > MAX_REQUEST_BYTES:
            raise EarningsTrialError("FROZEN_EARNINGS_REQUEST_TOO_LARGE")
        try:
            request = json.loads(raw, object_pairs_hook=_object, parse_constant=_nonfinite)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise EarningsTrialError("FROZEN_EARNINGS_REQUEST_INVALID") from exc
        code = match.group(1)
        if (not isinstance(request, dict) or request.get("workflow") != "earnings"
                or request.get("mode") != "HISTORICAL_REPLAY"
                or not isinstance(request.get("as_of"), str)
                or not isinstance(request.get("payload"), dict)
                or request["payload"].get("company") != code):
            raise EarningsTrialError("ONLY_BOUND_HISTORICAL_EARNINGS_ALLOWED")
        prepared.append((code, path, hashlib.sha256(raw).hexdigest(), request))
    if len({request["as_of"] for _, _, _, request in prepared}) != 1:
        raise EarningsTrialError("FROZEN_EARNINGS_CUTOFF_MISMATCH")

    # Preflight all source hashes and citations before publishing any case directory.
    try:
        for _, _, _, request in prepared:
            trial.build(request, inputs_root)
    except (trial.TrialError, OSError, ValueError, KeyError, TypeError) as exc:
        raise EarningsTrialError("FROZEN_EARNINGS_EVIDENCE_INVALID") from exc

    reports = []
    for code, path, request_hash, request in prepared:
        output = Path(output_root) / code
        try:
            receipt = trial.write_trial(request, inputs_root, output)
            trial.verify_trial(request, inputs_root, output)
            if hashlib.sha256(path.read_bytes()).hexdigest() != request_hash:
                raise EarningsTrialError("FROZEN_EARNINGS_REQUEST_CHANGED")
            raw_report = (output / "report.md").read_bytes()
            if len(raw_report) > MAX_REPORT_BYTES:
                raise EarningsTrialError("FROZEN_EARNINGS_REPORT_TOO_LARGE")
            artifact = json.loads((output / "artifact.json").read_bytes())
        except (trial.TrialError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, EarningsTrialError):
                raise
            raise EarningsTrialError("FROZEN_EARNINGS_EVIDENCE_INVALID") from exc
        reports.append({
            "company": code, "as_of": receipt["as_of"], "data_status": receipt["data_status"],
            "registration_status": artifact["registration_status"], "human_review": receipt["human_review"],
            "report": raw_report.decode("utf-8"), "report_sha256": hashlib.sha256(raw_report).hexdigest(),
            "request_sha256": request_hash,
            "receipt_sha256": hashlib.sha256((output / "receipt.json").read_bytes()).hexdigest(),
        })
    return {"status": "COMPLETED_HISTORICAL_EARNINGS", "sample_purpose": "WORKFLOW_DEBUG",
            "as_of": prepared[0][3]["as_of"], "coverage": "FROZEN_REQUESTS_ONLY",
            "human_review": "PENDING", "production_authority": False, "u4_authority": False,
            "paper_authority": False, "trade_authority": False, "reports": reports}
