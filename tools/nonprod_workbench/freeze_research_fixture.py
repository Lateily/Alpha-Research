"""Developer-only generation of synthetic inputs from the existing test suite.

The workbench runner never imports tests or generates decisions at runtime.
This script never reads a production tree. Regeneration requires review/re-pin.
"""

import hashlib
import json
import sys
import tempfile
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "tests"))
import test_research_cycle as fixtures
import test_research_closure_experiment as closure_fixtures
import test_research_funnel_closure as funnel_fixtures
import test_research_method as method_fixtures
import test_five_axis_attribution as attribution_fixtures


def normalized(value):
    return json.loads(json.dumps(value, sort_keys=True))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, original_battery, codes = closure_fixtures.build_bundle(root)
        registry, features, _, _ = funnel_fixtures.build_candidates(n=90)
        battery = normalized(original_battery)
        packet = fixtures.closure.build_review_packet(bundle_dir=source, battery=battery, generated_at=closure_fixtures.GENERATED_AT)
        receipt = normalized(closure_fixtures.receipt_for(packet, codes[:3]))
        rejected_receipt = copy.deepcopy(receipt)
        rejected_receipt["selections"] = rejected_receipt["selections"][:1]
        rejected_receipt.pop("receipt_hash")
        rejected_receipt["receipt_hash"] = closure_fixtures.funnel._hash(rejected_receipt)
        queue, report = fixtures.closure.run_offline_replay(bundle_dir=source, battery=battery,
            packet=packet, receipt=receipt, generated_at="2026-08-13T10:06:00+00:00")
        closure = root / "closure"
        fixtures.closure._write_replay_outputs(closure, source, battery, packet, receipt, queue, report)
        case_draft = normalized(fixtures.build_case_draft(closure, codes[0]))
        case = fixtures.cycle.seal_case(case_draft, closure)
        bars_draft = normalized(fixtures.build_bar_draft(case["ticker"]))
        bars = fixtures.cycle.seal_bars(bars_draft, case)
        outcomes_draft = normalized(method_fixtures.outcome_draft(case["method_registration"]))
        outcomes = fixtures.method.seal_outcomes(outcomes_draft, case["method_registration"])
        outputs = fixtures.cycle.run_cycle(bundle_dir=closure, case=case, bars=bars, outcomes=outcomes,
            generated_at="2026-08-17T16:10:00+00:00")
        payload = {
            "schema": "ar-workbench-frozen-research.v1",
            "sample_purpose": "WORKFLOW_DEBUG",
            "evidence_grade": "SYNTHETIC_NOT_RESEARCH_EVIDENCE",
            "not_human_approval": True,
            "origin": "tests/test_research_cycle.py and its existing fixture builders",
            "registry": registry, "features": features,
            "e1": funnel_fixtures.e1_fixture(registry),
            "rotation": funnel_fixtures.rotation_fixture(),
            "battery": battery,
            "expected_bundle": {p.name: json.loads(p.read_text()) for p in source.glob("*.json")},
            "receipt": receipt,
            "rejected_receipt": rejected_receipt,
            "case_draft": case_draft,
            "bars_draft": bars_draft,
            "outcomes_draft": outcomes_draft,
            "review_draft": fixtures.build_review_draft(outputs[0], outputs[3]),
            "market_draft": attribution_fixtures.complete_market_draft(case["ticker"]),
            "execution_draft": attribution_fixtures.complete_execution_draft(),
            "params": {
                "as_of": funnel_fixtures.TRADE_DATE,
                "scan_at": funnel_fixtures.GENERATED_AT,
                "packet_at": closure_fixtures.GENERATED_AT,
                "closure_at": "2026-08-13T10:06:00+00:00",
                "cycle_at": "2026-08-17T16:10:00+00:00",
                "attribution_at": "2026-08-17T16:30:00+00:00",
                "expected_packet_hash": packet["packet_hash"],
            },
        }
    target = Path(__file__).parent / "fixtures/research.json"
    target.parent.mkdir(exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    target.write_bytes(raw)
    print(f"{hashlib.sha256(raw).hexdigest()}  {target.name}  {len(raw)} bytes")


if __name__ == "__main__":
    main()
