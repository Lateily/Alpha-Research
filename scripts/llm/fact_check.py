#!/usr/bin/env python3
"""Offline adapter for the canonical JavaScript fact-check core.

Python owns repository evidence discovery and file IO only. All claim parsing,
identity matching, PIT enforcement, and receipt construction run in
``fact_check_core.mjs``, which is also imported by the production APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CORE_PATH = Path(__file__).with_name("fact_check_core.mjs")
_TICKER_PATTERN = r"^(?:\d{6}\.(?:SZ|SH|BJ)|\d{1,5}\.HK)$"


def _canonical_hash_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_json_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _canonical_hash_bytes(raw)


def _source_document(
    payload: Any,
    *,
    label: str,
    tier: str,
    entity: str,
    source_date: str = "",
    content_hash: str = "",
) -> dict[str, Any]:
    return {
        "payload": payload,
        "label": label,
        "tier": tier,
        "entity": entity,
        "source_date": source_date,
        "content_hash": content_hash or _canonical_json_hash(payload),
    }


def _load_json_bytes(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), raw


def _decision_sheet_document(
    repo_root: Path,
    path: Path,
    payload: Any,
    raw: bytes,
    ticker: str,
) -> dict[str, Any]:
    relative = path.relative_to(repo_root).as_posix()
    evidence = payload.get("evidence", {}) if isinstance(payload, Mapping) else {}
    items = evidence.get("items", []) if isinstance(evidence, Mapping) else []
    safe_items = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping) or not isinstance(item.get("claim"), str):
            continue
        safe_items.append(
            {
                "claim": item["claim"],
                "source": item.get("source"),
                "tier": item.get("tier", "UNSPECIFIED"),
                "source_date": item.get("source_date"),
            }
        )
    return _source_document(
        {"evidence": {"items": safe_items}},
        label=relative,
        tier="LANDED",
        entity=ticker,
        content_hash=_canonical_hash_bytes(raw),
    )


def load_repo_sources(repo_root: Path, ticker: str) -> list[dict[str, Any]]:
    """Load committed evidence documents without treating generated theses as evidence."""

    import re

    if not re.fullmatch(_TICKER_PATTERN, ticker):
        raise ValueError(f"unsupported ticker shape: {ticker}")
    public_data = repo_root / "public" / "data"
    ticker_under = ticker.replace(".", "_")
    candidates: set[Path] = set(public_data.glob(f"*/{ticker}.json"))
    candidates.update(public_data.glob(f"*{ticker_under}*.json"))
    decision_sheet = public_data / "decision_sheets" / f"{ticker_under}.json"
    if decision_sheet.exists():
        candidates.add(decision_sheet)

    documents: list[dict[str, Any]] = []
    for path in sorted(candidates):
        if "api_generated" in path.parts:
            continue
        try:
            payload, raw = _load_json_bytes(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if path == decision_sheet:
            documents.append(
                _decision_sheet_document(repo_root, path, payload, raw, ticker)
            )
        else:
            documents.append(
                _source_document(
                    payload,
                    label=path.relative_to(repo_root).as_posix(),
                    tier="LANDED",
                    entity=ticker,
                    content_hash=_canonical_hash_bytes(raw),
                )
            )

    market_data = public_data / "market_data.json"
    if market_data.exists():
        try:
            market_payload, raw = _load_json_bytes(market_data)
            ticker_payload = market_payload.get("yahoo", {}).get(ticker)
        except (AttributeError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            ticker_payload = None
            raw = b""
        if ticker_payload:
            documents.append(
                _source_document(
                    ticker_payload,
                    label="public/data/market_data.json",
                    tier="LANDED",
                    entity=ticker,
                    content_hash=_canonical_hash_bytes(raw),
                )
            )
    return documents


def _run_core(request: Mapping[str, Any]) -> dict[str, Any]:
    completed = subprocess.run(
        # governance-mutation: FACT_CHECK_PYTHON_CANONICAL_CORE
        ["node", str(CORE_PATH)],
        input=json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "canonical fact-check core failed"
        raise ValueError(detail)
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("canonical fact-check core returned invalid JSON") from error
    if not isinstance(receipt, dict):
        raise ValueError("canonical fact-check receipt must be an object")
    return receipt


def fact_check(
    thesis: Mapping[str, Any],
    *,
    ticker: str = "",
    cutoff: str,
    source_payloads: Sequence[tuple[Any, str, str]] = (),
    source_facts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Run the one canonical matcher with a frozen cutoff and evidence set."""

    documents = [dict(item) for item in source_facts]
    documents.extend(
        _source_document(payload, label=label, tier=tier, entity=ticker)
        for payload, label, tier in source_payloads
    )
    return _run_core(
        {
            "thesis": dict(thesis),
            "ticker": ticker,
            "cutoff": cutoff,
            "source_documents": documents,
        }
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="thesis JSON or API response")
    parser.add_argument("--output", type=Path, help="write deterministic receipt here")
    parser.add_argument("--cutoff", required=True, help="frozen ISO-8601 evidence cutoff")
    parser.add_argument("--extras", action="append", default=[], type=Path, help="additional field-level source JSON")
    parser.add_argument("--source", action="append", default=[], type=Path, help="additional source JSON")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--no-repo-sources", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    payload, _ = _load_json_bytes(args.input)
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON root must be an object")
    thesis = payload.get("data", payload)
    if not isinstance(thesis, Mapping):
        raise ValueError("thesis payload must be an object")
    ticker = str(payload.get("ticker") or thesis.get("ticker") or "")

    source_documents: list[dict[str, Any]] = []
    for path in [*args.extras, *args.source]:
        source_payload, raw = _load_json_bytes(path)
        source_documents.append(
            _source_document(
                source_payload,
                label=path.as_posix(),
                tier="SUPPLIED",
                entity=ticker,
                content_hash=_canonical_hash_bytes(raw),
            )
        )
    if not args.no_repo_sources and ticker:
        source_documents.extend(load_repo_sources(args.repo_root, ticker))
    receipt = fact_check(
        thesis,
        ticker=ticker,
        cutoff=args.cutoff,
        source_facts=source_documents,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
