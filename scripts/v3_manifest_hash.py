#!/usr/bin/env python3
"""v3_manifest_hash.py — compute and inject hypothesis_lock_hash into v3 manifests.

Per Junyan ratify #5 (v3 Phase A 2026-05-28 PM2):
  - The hash covers ONLY {hypothesis, design, test_plan} subtrees of the manifest.
  - Canonical JSON: json.dumps(payload, sort_keys=True, ensure_ascii=False,
                              separators=(',', ':')).
  - Hash = SHA256 over the UTF-8 bytes of the canonical JSON; hex digest.
  - The hash field `hypothesis_lock_hash` is itself EXCLUDED from the hashed
    payload (otherwise the hash would depend on itself).
  - `--inject` is REFUSED if the manifest already has a non-empty
    `hypothesis_lock_hash` — that prevents silently rewriting a locked hash.

Usage:
  python3 scripts/v3_manifest_hash.py --selftest
  python3 scripts/v3_manifest_hash.py --manifest <path>            # compute + print
  python3 scripts/v3_manifest_hash.py --manifest <path> --inject   # write back

Output JSON shape (printed when not --inject):
  {"manifest": "<path>", "hash": "<sha256 hex>", "lock_hash_field_present": bool,
   "lock_hash_field_value": str|None, "matches_stored": bool|None}

Exit codes:
  0 = OK (compute success, OR inject success, OR --selftest pass)
  1 = error (file missing, schema mismatch, already-locked refusal, selftest fail)
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional


# Subtrees that go into the hash. Order doesn't matter — sort_keys=True
# canonicalizes the JSON regardless.
HASHED_SUBTREES = ("hypothesis", "design", "test_plan")

# The hash field itself; excluded from the hash payload per Junyan #5.
HASH_FIELD_NAME = "hypothesis_lock_hash"


def _payload_for_hash(manifest: dict) -> dict:
    """Extract {hypothesis, design, test_plan} from a manifest.

    'hypothesis' may live at manifest.variant.hypothesis (current template) or
    at manifest.hypothesis (alternative). We accept both shapes and try to
    fall back gracefully. The `hypothesis_lock_hash` field is removed from any
    location it could appear in the captured subtrees.
    """
    variant = manifest.get("variant", {}) or {}

    # hypothesis: prefer manifest.hypothesis, else variant.hypothesis.
    hypothesis = manifest.get("hypothesis", variant.get("hypothesis"))
    design = manifest.get("design", {})
    test_plan = manifest.get("test_plan", {})

    payload = {
        "hypothesis": hypothesis,
        "design": copy.deepcopy(design),
        "test_plan": copy.deepcopy(test_plan),
    }
    # Defensive: remove HASH_FIELD_NAME anywhere it might appear in the
    # captured trees (it shouldn't, but normalize).
    def _strip(obj):
        if isinstance(obj, dict):
            obj.pop(HASH_FIELD_NAME, None)
            for v in obj.values():
                _strip(v)
        elif isinstance(obj, list):
            for v in obj:
                _strip(v)
    _strip(payload)
    return payload


def compute_hash(manifest: dict) -> str:
    """Compute SHA256 hex digest of canonical JSON of the hashed subtrees.

    Canonical JSON form per Junyan #5: sort_keys=True, ensure_ascii=False,
    separators=(',', ':').
    """
    payload = _payload_for_hash(manifest)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inject_hash(manifest: dict, expected_hash: Optional[str] = None) -> tuple[dict, str, bool]:
    """Inject hash into manifest.variant.hypothesis_lock_hash.

    Refuses to overwrite an existing non-empty hash (anti-lock-overwrite).

    Returns (mutated_manifest, hash, was_written).
    Raises RuntimeError if a non-empty hash already exists.
    """
    h = compute_hash(manifest)
    if expected_hash is not None and expected_hash != h:
        raise RuntimeError(
            f"expected_hash mismatch: caller said {expected_hash}, computed {h}"
        )
    variant = manifest.setdefault("variant", {})
    existing = variant.get(HASH_FIELD_NAME, "") or ""
    if existing.strip():
        raise RuntimeError(
            f"manifest.variant.{HASH_FIELD_NAME} already set ({existing!r}); "
            "refusing to overwrite a locked hash. Remove manually if intentional."
        )
    variant[HASH_FIELD_NAME] = h
    return manifest, h, True


# --------- CLI ---------

def _selftest() -> int:
    errors = []

    # Synthetic manifest minimal but realistic.
    synth = {
        "schema": "v3_variant_manifest",
        "schema_version": 2,
        "variant": {
            "variant_id": "v3c_test",
            "registered_at": "2026-05-28T18:00:00Z",
            "hypothesis": "Test hypothesis covering canonical JSON behavior.",
            "causal_logic_label": "Causal logic is unestablished: synthetic test.",
            "expected_failure_modes": ["a", "b"],
            "hypothesis_lock_hash": "",
        },
        "design": {
            "factor_inputs": [
                {"name": "momentum_5d", "direction": "inverse", "weight": 0.2},
            ],
            "portfolio": {"max_positions": 8, "max_gross": 0.5},
        },
        "test_plan": {
            "windows": [
                {"name": "wf_2022_2026", "start": "2022-01-04", "end": "2026-05-25"},
            ],
        },
    }

    # 1. Determinism: same input → same hash.
    h1 = compute_hash(synth)
    h2 = compute_hash(synth)
    if h1 != h2:
        errors.append(f"non-deterministic hash: {h1} vs {h2}")

    # 2. Different key insertion order → same hash (sort_keys).
    reordered = {
        "test_plan": synth["test_plan"],
        "design": synth["design"],
        "variant": synth["variant"],
        "schema": synth["schema"],
    }
    h3 = compute_hash(reordered)
    if h3 != h1:
        errors.append(f"sort_keys not honored: {h1} vs {h3} after reorder")

    # 3. Changing hypothesis content changes the hash.
    mutated = copy.deepcopy(synth)
    mutated["variant"]["hypothesis"] = synth["variant"]["hypothesis"] + " EXTRA"
    h4 = compute_hash(mutated)
    if h4 == h1:
        errors.append(f"mutating hypothesis didn't change hash: stayed {h1}")

    # 4. Hash field is excluded — setting it to a value should NOT change hash.
    with_lock = copy.deepcopy(synth)
    with_lock["variant"][HASH_FIELD_NAME] = "deadbeef" * 8
    h5 = compute_hash(with_lock)
    if h5 != h1:
        errors.append(
            f"hash field NOT excluded from payload: with_lock h={h5}, base h={h1}"
        )

    # 5. Inject works on empty field.
    injectable = copy.deepcopy(synth)
    _, h6, wrote = inject_hash(injectable)
    if not wrote:
        errors.append("inject_hash returned wrote=False on empty field")
    if injectable["variant"][HASH_FIELD_NAME] != h6:
        errors.append(
            f"inject_hash didn't write hash field: "
            f"field={injectable['variant'][HASH_FIELD_NAME]!r}, computed={h6}"
        )
    if h6 != h1:
        errors.append(f"inject_hash computed different hash {h6} vs {h1}")

    # 6. Re-inject on already-locked manifest must REFUSE.
    try:
        inject_hash(injectable)   # already has hash now
    except RuntimeError as e:
        if "refusing" not in str(e).lower():
            errors.append(f"inject refusal didn't mention 'refusing': {e}")
    else:
        errors.append("inject_hash on already-locked manifest should raise RuntimeError")

    # 7. Round-trip: compute, inject, recompute, must match.
    rt = copy.deepcopy(synth)
    expected = compute_hash(rt)
    inject_hash(rt)
    recomputed = compute_hash(rt)
    if recomputed != expected:
        errors.append(
            f"round-trip mismatch: pre-inject={expected}, post-inject={recomputed}"
        )

    # 8. Canonical JSON form — exact spec per Junyan #5.
    payload = _payload_for_hash(synth)
    canon = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    # spec: no spaces between separators, sort_keys, no ASCII escaping
    if " " in canon and '" "' not in canon:
        # space outside string literals → separators wrong
        # rough check: serialized form should not contain ", " or ": " in keys
        if ", " in canon or ": " in canon:
            errors.append(f"canonical JSON has wrong separators: {canon[:120]}...")

    # 9. SHA256 length sanity: 64 hex chars.
    if len(h1) != 64 or any(c not in "0123456789abcdef" for c in h1):
        errors.append(f"hash not 64-hex-char SHA256: {h1!r}")

    if errors:
        print("v3_manifest_hash SELFTEST FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("v3_manifest_hash SELFTEST PASSED")
    print(f"  deterministic hash: {h1}")
    print("  inject/refuse/round-trip verified.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute or inject hypothesis_lock_hash for v3 variant manifests.",
    )
    parser.add_argument("--manifest", type=str, help="Path to manifest JSON.")
    parser.add_argument("--inject", action="store_true",
                        help="Write the hash back into the manifest "
                             "(REFUSED if a non-empty hash already exists).")
    parser.add_argument("--selftest", action="store_true",
                        help="Run built-in self-tests and exit.")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    if not args.manifest:
        parser.error("--manifest required (or use --selftest)")

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    with open(manifest_path) as f:
        manifest = json.load(f)

    if manifest.get("schema") != "v3_variant_manifest":
        print(
            f"WARNING: manifest schema is {manifest.get('schema')!r}, expected "
            f"'v3_variant_manifest'; proceeding anyway.",
            file=sys.stderr,
        )

    h = compute_hash(manifest)
    variant = manifest.get("variant", {}) or {}
    stored = variant.get(HASH_FIELD_NAME, "") or None
    matches_stored = (stored == h) if stored else None

    if args.inject:
        try:
            inject_hash(manifest)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote hash {h} to {manifest_path}.variant.{HASH_FIELD_NAME}")
        return 0

    out = {
        "manifest": str(manifest_path),
        "hash": h,
        "lock_hash_field_present": bool(stored),
        "lock_hash_field_value": stored,
        "matches_stored": matches_stored,
    }
    print(json.dumps(out, indent=2))
    # If a stored hash mismatches, exit non-zero so CI can catch tampering.
    if stored and not matches_stored:
        print(
            f"WARNING: stored hash {stored!r} does NOT match computed {h!r}; "
            "manifest has been edited after locking.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
