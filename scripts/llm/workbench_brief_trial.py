"""Run the real daily-brief renderer against one operator-frozen local pack."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


class BriefTrialError(ValueError):
    pass


MAX_REQUEST_BYTES = 1_000_000
MAX_REPORT_BYTES = 128_000


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BriefTrialError("BRIEF_REQUEST_DUPLICATE_FIELD")
        result[key] = value
    return result


def run(pack_root: Path, output: Path) -> dict:
    """No request path comes from HTTP; the operator fixes the pack at startup."""
    pack_root = Path(pack_root)
    request_path = pack_root / "requests" / "brief.json"
    input_root = pack_root / "inputs"
    if (pack_root.is_symlink() or request_path.parent.is_symlink()
            or request_path.is_symlink() or input_root.is_symlink()
            or not request_path.is_file() or not input_root.is_dir()):
        raise BriefTrialError("FROZEN_BRIEF_PACK_UNAVAILABLE")
    raw = request_path.read_bytes()
    if len(raw) > MAX_REQUEST_BYTES:
        raise BriefTrialError("FROZEN_BRIEF_REQUEST_TOO_LARGE")
    request_hash = hashlib.sha256(raw).hexdigest()
    try:
        request = json.loads(raw, object_pairs_hook=_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(BriefTrialError("BRIEF_REQUEST_NONFINITE")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BriefTrialError("FROZEN_BRIEF_REQUEST_INVALID") from exc
    if not isinstance(request, dict) or request.get("workflow") != "brief" or request.get("mode") != "HISTORICAL_REPLAY":
        raise BriefTrialError("ONLY_HISTORICAL_BRIEF_ALLOWED")

    module_root = str(Path(__file__).resolve().parents[2])
    if module_root not in sys.path:
        sys.path.insert(0, module_root)
    from experiments.research_workflows import trial

    try:
        receipt = trial.write_trial(request, input_root, output)
        if hashlib.sha256(request_path.read_bytes()).hexdigest() != request_hash:
            raise BriefTrialError("FROZEN_BRIEF_REQUEST_CHANGED")
        trial.verify_trial(request, input_root, output)
    except (trial.TrialError, OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, BriefTrialError):
            raise
        raise BriefTrialError("FROZEN_BRIEF_EVIDENCE_INVALID") from exc
    report = (output / "report.md").read_text(encoding="utf-8")
    if len(report.encode("utf-8")) > MAX_REPORT_BYTES:
        raise BriefTrialError("FROZEN_BRIEF_REPORT_TOO_LARGE")
    return {
        "status": "COMPLETED_HISTORICAL_BRIEF", "workflow": "brief",
        "sample_purpose": "WORKFLOW_DEBUG", "human_review": "PENDING",
        "production_authority": False, "trade_authority": False,
        "request_sha256": request_hash, "receipt_sha256": hashlib.sha256((output / "receipt.json").read_bytes()).hexdigest(),
        "as_of": receipt["as_of"], "data_status": receipt["data_status"],
        "report": report,
    }
