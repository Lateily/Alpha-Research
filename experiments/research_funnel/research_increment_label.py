#!/usr/bin/env python3
"""Research-increment labels: two human axes on addressable announcements (contract L v1.0).

"Relevant" and "adds to our research" are different questions. This CLI lets a
named human reviewer record both, per announcement item (announcement_feed.json)
or per E1 evidence row (e1_event_layer.json), into a dedicated R-015 ledger:

  propose  list new, in-window items for tickers with a live thesis (blind: never
           shows existing labels); capped at 20; prints a template with null
           human axes that ``record`` refuses until a human fills them.
  record   validate a human-written batch, bind it to one authorization text that
           quotes the batch hash, and append intent → label(s) → closure.
  verify   replay the chain, anchor, payload contract and batch structure.
  report   descriptive counts only; any rate below its minimum sample is null.

Only two axes are human (thesis_relevance, research_increment). provenance_tier
is machine-filled. Labels never carry a posture, never enter U3/U4/paper/
execution, and are never written by a model or by the nightly chain.

Ledger: data_history/research_advisory/research_increment_labels/label_events.jsonl
(+ .anchor.json, .lock), gitignored runtime data, local only, no backup.

不是买卖指令；研究信号，human executes。
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.execution_tracker import event_ledger  # noqa: E402
from experiments.research_funnel import announcement_feed as feed_contract  # noqa: E402

DEFAULT_LEDGER = (REPO_ROOT / "data_history" / "research_advisory"
                  / "research_increment_labels" / "label_events.jsonl")
DEFAULT_U4_LEDGER = (REPO_ROOT / "data_history" / "research_advisory"
                     / "u4_decision_ledger" / "u4_decision_events.jsonl")
DEFAULT_DECISION_SHEETS = REPO_ROOT / "docs" / "research" / "decision_sheets"
DEFAULT_WATCHLIST = REPO_ROOT / "experiments" / "execution_tracker" / "watch_dynamic.json"

SCHEMA = "ar.research_increment_label"
SCHEMA_VERSION = "1.0"
INTENT_SCHEMA = "ar.research_increment_label_intent"
CLOSURE_SCHEMA = "ar.research_increment_label_closure"
INPUT_SCHEMA = "ar.research_increment_label_input"
PROPOSAL_SCHEMA = "ar.research_increment_label_proposal"
REPORT_SCHEMA = "ar.research_increment_label_report"
INTENT_KIND = "research_increment_label_intent"
LABEL_KIND = "research_increment_label"
CLOSURE_KIND = "research_increment_label_closure"
LEDGER_KINDS = (INTENT_KIND, LABEL_KIND, CLOSURE_KIND)

TARGET_KINDS = ("ANNOUNCEMENT", "E1_EVENT")
THESIS_KINDS = ("U4_RESEARCH_QUESTION", "DECISION_SHEET", "NONE")
RELEVANCE = ("THESIS_RELEVANT", "WRONG_IF_RELEVANT", "NOT_RELEVANT", "NO_LIVE_THESIS")
RELEVANT = ("THESIS_RELEVANT", "WRONG_IF_RELEVANT")
INCREMENTS = ("CHANGES_POSTURE", "RESOLVES_WAIT", "TRIGGERS_WRONG_IF", "NONE", "DATA_BLOCKED")
CHANGE_INCREMENTS = ("CHANGES_POSTURE", "RESOLVES_WAIT", "TRIGGERS_WRONG_IF")
PROVENANCE_TIERS = ("E1", "DATA_BLOCKED")
CLAIMED_REVIEWERS = ("Junyan",)
BARS_BASIS = "UNAVAILABLE_NO_EXCHANGE_CALENDAR"
WINDOW_DAYS = 2
PROPOSAL_CAP = 20
MIN_N = 20
AUTHORITY = {"posture_authority": False, "gate_authority": False}
DISCLAIMER = "不是买卖指令；研究信号，human executes。"
EVIDENCE_REF_RE = re.compile(r"^(conversation|pr|commit):.+$")
DECISION_ID_RE = re.compile(r"^u4d_[0-9a-f]{32}$")
SHEET_RE = re.compile(r"^(?P<code>[0-9]{6})_(?P<ex>SH|SZ|BJ)(?:_DEEP)?_(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\.md$")
TICKER_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")
BATCH_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

HUMAN_DECISION_KEYS = {"claimed_reviewer", "identity_verification", "decided_at",
                       "authorization_text", "authorization_evidence_ref"}
INPUT_KEYS = {"schema", "schema_version", "as_of", "run_id", "human_decision", "labels"}
INPUT_LABEL_KEYS = {"item_id", "target_kind", "thesis_ref", "thesis_relevance",
                    "research_increment", "increment_ref", "note", "labeled_at",
                    "future_seen", "saw_other_label"}
LABEL_KEYS = {"schema", "schema_version", "batch_id", "item_id", "target_kind", "ts_code",
              "snapshot", "source", "thesis_ref", "provenance_tier", "thesis_relevance",
              "research_increment", "increment_ref", "note", "exposure", "human_decision",
              "authority", "record_hash"}
INTENT_KEYS = {"schema", "schema_version", "batch_id", "batch_hash", "as_of", "run_id",
               "feed_rows_hash", "e1_rows_hash", "item_ids", "human_decision",
               "registered_at", "authority", "record_hash"}
CLOSURE_KEYS = {"schema", "schema_version", "batch_id", "batch_hash", "label_record_hashes",
                "registered_at", "record_hash"}
ANNOUNCEMENT_SNAPSHOT_KEYS = {"source_channel", "notice_date", "title", "captured_at",
                              "eligibility", "same_day_as_as_of", "news_status",
                              "news_display_verdict"}
E1_SNAPSHOT_KEYS = {"kind", "source", "evidence_grade", "ann_date", "period", "triggered", "rule"}
NEWS_DISPLAY_VERDICTS = ("SPIKE", "NORMAL", None)
# The labeler never sees the machine display signal the report cross-tabs against.
PROPOSAL_HIDDEN_SNAPSHOT_KEYS = ("news_display_verdict", "news_status")
LATE_CAPTURE_DAYS = 2
VERIFIED = "VERIFIED_AGAINST_SOURCE"
MISMATCH = "SOURCE_MISMATCH"
SNAPSHOT_ONLY = "SOURCE_UNAVAILABLE_SNAPSHOT_ONLY"
PARTIAL = "PARTIALLY_VERIFIED_REST_SNAPSHOT_ONLY"


class LabelError(RuntimeError):
    pass


# ── primitives ────────────────────────────────────────────────────────────

def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _record_hash(payload: Mapping[str, Any]) -> str:
    return "sha256:" + _hash({k: v for k, v in payload.items() if k != "record_hash"})


def _exact(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        extra = sorted(set(value) - keys) if isinstance(value, Mapping) else []
        missing = sorted(keys - set(value)) if isinstance(value, Mapping) else sorted(keys)
        raise LabelError(f"{label} keys differ from contract (missing {missing}, extra {extra})")
    return value


def _aware(value: Any, label: str) -> _dt.datetime:
    try:
        parsed = _dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise LabelError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise LabelError(f"{label} must be timezone-aware")
    return parsed


def _r015(ts: str) -> _dt.datetime:
    """The R-015 clock is naive Asia/Shanghai; make that explicit before comparing."""
    parsed = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=event_ledger.OPERATIONAL_TIMEZONE)
    return parsed


def _registered_at(ts: str) -> str:
    return _r015(ts).astimezone(event_ledger.OPERATIONAL_TIMEZONE).isoformat(timespec="microseconds")


def _date8(value: str) -> _dt.date:
    try:
        return _dt.datetime.strptime(str(value).replace("-", "")[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise LabelError(f"date must be YYYYMMDD: {value!r}") from exc


def _shanghai_date(moment: _dt.datetime) -> _dt.date:
    return moment.astimezone(event_ledger.OPERATIONAL_TIMEZONE).date()


# ── live-thesis scope (read-only) ─────────────────────────────────────────

def _u4_select_refs(path: Path, as_of: _dt.date) -> tuple[str, dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Live U4 SELECTs as the ledger stood at the end of as_of (Asia/Shanghai).

    The whole ledger is verified first (a broken ledger is never "no thesis"),
    then only the record prefix registered on or before as_of is replayed, so a
    later revision (REJECT/DEFER or a re-SELECT) cannot remove or add a thesis
    retroactively and a closure committed after as_of does not count.
    """
    if not os.path.lexists(path):
        return "ABSENT", {}, {}
    from experiments.research_funnel import u4_decision_ledger
    path = Path(path)
    try:
        with u4_decision_ledger._ledger_read_snapshot(path):
            u4_decision_ledger._snapshot_state(path)
            records = u4_decision_ledger._read_outer_records(path)
        prefix = []
        for outer in records:
            # governance-mutation: RESEARCH_INCREMENT_U4_SCOPE_AS_OF_REPLAY
            if _shanghai_date(_r015(outer.get("ts"))) > as_of:
                break  # R-015 is append-only in time order: the rest is later still
            prefix.append(outer)
        state = u4_decision_ledger._replay_records(prefix)
    except Exception as exc:  # a broken U4 ledger is never read as "no thesis"
        raise LabelError(f"U4 decision ledger is unreadable: {exc}") from exc
    refs: dict[str, list[dict[str, Any]]] = {}
    dates: dict[str, str] = {}
    for event in state["current"].values():
        if event.get("decision") != "SELECT":
            continue
        registered = _aware(event.get("registered_at"), "U4 registered_at")
        code = event["candidate"]["ts_code"]
        refs.setdefault(code, []).append({"kind": "U4_RESEARCH_QUESTION",
                                          "ref": event["decision_id"]})
        dates[event["decision_id"]] = _shanghai_date(registered).isoformat()
    return "OK", refs, dates


def _decision_sheet_refs(directory: Path, as_of: _dt.date) -> tuple[str, dict[str, list[dict[str, Any]]], dict[str, str]]:
    if not Path(directory).is_dir():
        return "ABSENT", {}, {}
    refs: dict[str, list[dict[str, Any]]] = {}
    dates: dict[str, str] = {}
    for path in sorted(Path(directory).iterdir()):
        match = SHEET_RE.fullmatch(path.name)
        if not match or not path.is_file():
            continue
        if _dt.date.fromisoformat(match.group("date")) > as_of:
            continue
        code = f"{match.group('code')}.{match.group('ex')}"
        try:
            ref = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            ref = f"docs/research/decision_sheets/{path.name}"
        refs.setdefault(code, []).append({"kind": "DECISION_SHEET", "ref": ref})
        # Sheets never expire in V1; their age is shown so a stale thesis is visible.
        dates[ref] = match.group("date")
    return "OK", refs, dates


def _watchlist(path: Path) -> tuple[str, list[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "ABSENT", []
    except (OSError, ValueError):
        return "DATA_BLOCKED", []
    watch = data.get("watch") if isinstance(data, Mapping) else None
    # governance-mutation: RESEARCH_INCREMENT_WATCHLIST_CORRUPT_BLOCKED
    if not isinstance(watch, list):
        return "DATA_BLOCKED", []
    tickers = [row.get("ticker") for row in watch
               if isinstance(row, Mapping) and isinstance(row.get("ticker"), str)]
    return "OK", sorted({code for code in tickers if TICKER_RE.fullmatch(code)})


def live_scope(as_of: str, *, u4_ledger: Path, decision_sheets: Path,
               watchlist: Path) -> dict[str, Any]:
    cutoff = _date8(as_of)
    u4_status, u4, u4_dates = _u4_select_refs(u4_ledger, cutoff)
    sheet_status, sheets, sheet_dates = _decision_sheet_refs(decision_sheets, cutoff)
    ref_dates = dict(u4_dates, **sheet_dates)
    watch_status, watch = _watchlist(watchlist)
    tickers: dict[str, dict[str, Any]] = {}
    for source, mapping in (("U4_SELECT", u4), ("DECISION_SHEET", sheets)):
        for code, refs in mapping.items():
            entry = tickers.setdefault(code, {"ts_code": code, "sources": [], "thesis_refs": []})
            entry["sources"].append(source)
            entry["thesis_refs"].extend(refs)
    for code in watch:
        entry = tickers.setdefault(code, {"ts_code": code, "sources": [], "thesis_refs": []})
        entry["sources"].append("EXECUTION_WATCHLIST")
    for entry in tickers.values():
        entry["sources"] = sorted(set(entry["sources"]))
        entry["thesis_refs"] = sorted({(r["kind"], r["ref"]) for r in entry["thesis_refs"]})
        entry["thesis_refs"] = [{"kind": k, "ref": r} for k, r in entry["thesis_refs"]]
        entry["thesis_ref_dates"] = {r["ref"]: ref_dates[r["ref"]] for r in entry["thesis_refs"]}
    return {
        "tickers": {code: tickers[code] for code in sorted(tickers)},
        "source_status": {"U4_SELECT": u4_status, "DECISION_SHEET": sheet_status,
                          "EXECUTION_WATCHLIST": watch_status},
    }


# ── addressable items (machine side) ─────────────────────────────────────

def e1_item_id(ts_code: str, kind: str, source: str, ann_date: str, period: str) -> str:
    return "sha256:" + _hash({"ts_code": ts_code, "kind": kind, "source": source,
                              "ann_date": ann_date, "period": period})


def has_content(target_kind: str, snapshot: Mapping[str, Any], as_of: str) -> bool:
    """Whether a human could have read real content at as_of (NONE needs this)."""
    if target_kind == "ANNOUNCEMENT":
        return (isinstance(snapshot.get("title"), str) and bool(snapshot["title"].strip())
                and snapshot.get("eligibility") == "AT_OR_BEFORE_AS_OF")
    if target_kind == "E1_EVENT":
        fields = [snapshot.get(key) for key in ("kind", "period", "ann_date")]
        if not all(isinstance(value, str) and value.strip() for value in fields):
            return False
        try:
            return _date8(snapshot["ann_date"]) <= _date8(as_of)
        except LabelError:
            return False
    return False


def _news_verdict(row: Mapping[str, Any] | None) -> Any:
    news = ((row or {}).get("dims") or {}).get(feed_contract.NEWS_DIMENSION)
    if not isinstance(news, Mapping):
        return None
    verdict = news.get("verdict_v0_unvalidated")
    return verdict if verdict in ("SPIKE", "NORMAL") else None


def announcement_items(feed: Mapping[str, Any], battery: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    per_ticker = {entry["ts_code"]: entry for entry in feed["per_ticker"]}
    battery_rows = {row.get("ts_code"): row for row in battery.get("results", [])}
    items: dict[str, dict[str, Any]] = {}
    for row in feed["rows"]:
        snapshot = {
            "source_channel": row["source_channel"], "notice_date": row["notice_date"],
            "title": row["title"], "captured_at": row["captured_at"],
            "eligibility": row["eligibility"], "same_day_as_as_of": row["same_day_as_as_of"],
            "news_status": per_ticker[row["ts_code"]]["status"],
            "news_display_verdict": _news_verdict(battery_rows.get(row["ts_code"])),
        }
        items[row["item_id"]] = {
            "item_id": row["item_id"], "target_kind": "ANNOUNCEMENT", "ts_code": row["ts_code"],
            "snapshot": snapshot,
            "source": {"as_of": feed["as_of"], "run_id": feed["run_id"],
                       "feed_rows_hash": feed["rows_hash"]},
        }
    return items


def load_e1_layer(path: Path | None, as_of: str) -> tuple[str, dict[str, Any] | None]:
    if path is None:
        return "NOT_REQUESTED", None
    try:
        layer = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "E1_UNAVAILABLE", None
    rows = layer.get("rows") if isinstance(layer, Mapping) else None
    if not isinstance(rows, list) or layer.get("rows_hash") != _hash(rows):
        return "E1_UNAVAILABLE", None
    # governance-mutation: RESEARCH_INCREMENT_E1_SAME_AS_OF
    if layer.get("as_of") != as_of:
        return "E1_OTHER_AS_OF_REFUSED", None
    return "SAME_AS_OF", layer


def e1_items(layer: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Triggered E1 evidence rows. The E1 layer has no run binding (basis SAME_AS_OF),
    so an E1 label's source.run_id is null rather than the funnel run's id."""
    items: dict[str, dict[str, Any]] = {}
    if layer is None:
        return items
    for row in layer["rows"]:
        code = row.get("ts_code")
        for evidence in row.get("evidence") or []:
            # governance-mutation: RESEARCH_INCREMENT_E1_TRIGGERED_ONLY
            if not isinstance(evidence, Mapping) or evidence.get("triggered") is not True:
                continue
            snapshot = {key: evidence.get(key) for key in sorted(E1_SNAPSHOT_KEYS)}
            identity = e1_item_id(code, str(snapshot["kind"]), str(snapshot["source"]),
                                  str(snapshot["ann_date"]), str(snapshot["period"]))
            items[identity] = {
                "item_id": identity, "target_kind": "E1_EVENT", "ts_code": code,
                "snapshot": snapshot,
                "source": {"as_of": layer["as_of"], "run_id": None,
                           "feed_rows_hash": layer["rows_hash"]},
            }
    return items


def _item_date(item: Mapping[str, Any]) -> _dt.date | None:
    snapshot = item["snapshot"]
    raw = snapshot.get("notice_date") if item["target_kind"] == "ANNOUNCEMENT" else snapshot.get("ann_date")
    try:
        return _date8(str(raw))
    except LabelError:
        return None


def _machine_view(item: Mapping[str, Any]) -> dict[str, Any]:
    content = has_content(item["target_kind"], item["snapshot"], item["source"]["as_of"])
    return dict(item, provenance_tier="E1" if content else "DATA_BLOCKED", has_content=content)


def _capture_lag_days(item: Mapping[str, Any]) -> int | None:
    """Calendar days from as_of to the capture (catch-up runs capture days later)."""
    if item["target_kind"] != "ANNOUNCEMENT":
        return None
    try:
        captured = _aware(item["snapshot"].get("captured_at"), "captured_at")
        return (_shanghai_date(captured) - _date8(item["source"]["as_of"])).days
    except LabelError:
        return None


def _proposal_view(item: Mapping[str, Any]) -> dict[str, Any]:
    """What the labeler sees: machine view minus the display signal the report scores."""
    view = _machine_view(item)
    # governance-mutation: RESEARCH_INCREMENT_PROPOSE_BLIND_TO_DISPLAY_VERDICT
    view["snapshot"] = {k: v for k, v in view["snapshot"].items() if k not in PROPOSAL_HIDDEN_SNAPSHOT_KEYS}
    view["capture_lag_days"] = _capture_lag_days(item)
    return view


def _e1_after_as_of(snapshot: Mapping[str, Any], as_of: str) -> bool:
    try:
        return _date8(str(snapshot.get("ann_date"))) > _date8(as_of)
    except LabelError:
        return False


# ── ledger replay ─────────────────────────────────────────────────────────

def _validate_human_decision(human: Any, batch_hash: str) -> Mapping[str, Any]:
    human = _exact(human, HUMAN_DECISION_KEYS, "human_decision")
    # governance-mutation: RESEARCH_INCREMENT_REVIEWER_BOUNDARY
    if (human.get("claimed_reviewer") not in CLAIMED_REVIEWERS
            or human.get("identity_verification") != "UNAVAILABLE"):
        raise LabelError("reviewer identity boundary changed")
    text = human.get("authorization_text")
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise LabelError("authorization_text must preserve substantive verbatim text")
    # governance-mutation: RESEARCH_INCREMENT_BATCH_AUTHORIZATION
    if batch_hash[:12] not in text or not ("离线" in text or "offline" in text.casefold()):
        raise LabelError("authorization_text is not batch-bound and offline-scoped")
    ref = human.get("authorization_evidence_ref")
    if not isinstance(ref, str) or EVIDENCE_REF_RE.fullmatch(ref) is None:
        raise LabelError("authorization_evidence_ref is not externally anchored")
    _aware(human.get("decided_at"), "decided_at")
    return human


def validate_label_semantics(label: Mapping[str, Any], as_of: str) -> None:
    """Two human axes, orthogonal; no posture; content before NONE."""
    kind = label.get("target_kind")
    if kind not in TARGET_KINDS:
        raise LabelError("target_kind is outside the closed taxonomy")
    thesis = _exact(label.get("thesis_ref"), {"kind", "ref"}, "thesis_ref")
    relevance = label.get("thesis_relevance")
    increment = label.get("research_increment")
    # governance-mutation: RESEARCH_INCREMENT_HUMAN_AXES_REQUIRED
    if relevance not in RELEVANCE or increment not in INCREMENTS:
        raise LabelError("both human axes are required and must be in the closed taxonomy")
    if thesis["kind"] not in THESIS_KINDS:
        raise LabelError("thesis_ref.kind is outside the closed taxonomy")
    if thesis["kind"] == "NONE":
        if thesis["ref"] is not None:
            raise LabelError("thesis_ref NONE carries no ref")
    elif not isinstance(thesis["ref"], str) or not thesis["ref"].strip():
        raise LabelError("thesis_ref needs a ref")
    if thesis["kind"] == "U4_RESEARCH_QUESTION" and not DECISION_ID_RE.fullmatch(thesis["ref"]):
        raise LabelError("U4 thesis_ref must be a u4d_ decision id")
    # governance-mutation: RESEARCH_INCREMENT_NO_LIVE_THESIS_IFF_NONE
    if (relevance == "NO_LIVE_THESIS") != (thesis["kind"] == "NONE"):
        raise LabelError("NO_LIVE_THESIS if and only if thesis_ref.kind is NONE")
    increment_ref = label.get("increment_ref")
    if increment in CHANGE_INCREMENTS:
        # governance-mutation: RESEARCH_INCREMENT_REQUIRES_RELEVANCE
        if relevance not in RELEVANT:
            raise LabelError("an increment requires a thesis-relevant item")
        if increment == "TRIGGERS_WRONG_IF" and relevance != "WRONG_IF_RELEVANT":
            raise LabelError("TRIGGERS_WRONG_IF requires WRONG_IF_RELEVANT")
        if not isinstance(increment_ref, str) or not increment_ref.strip():
            raise LabelError("an increment must point at the human record it changes")
    elif increment_ref is not None:
        raise LabelError("NONE/DATA_BLOCKED carries no increment_ref")
    # governance-mutation: RESEARCH_INCREMENT_NONE_REQUIRES_CONTENT
    if increment != "DATA_BLOCKED" and not has_content(kind, label.get("snapshot") or {}, as_of):
        raise LabelError("unreadable, undated or after-as-of content can only be DATA_BLOCKED")
    note = label.get("note")
    if not isinstance(note, str) or len(note.strip()) < 4:
        raise LabelError("note must be the reviewer's own words (>= 4 chars)")
    snapshot = label.get("snapshot") or {}
    if note.strip() in {str(snapshot.get("title") or "").strip(), str(snapshot.get("rule") or "").strip()}:
        raise LabelError("note cannot copy a machine string")


def _validate_label_payload(payload: Mapping[str, Any]) -> None:
    _exact(payload, LABEL_KEYS, "label payload")
    if payload["schema"] != SCHEMA or payload["schema_version"] != SCHEMA_VERSION:
        raise LabelError("label schema mismatch")
    if payload["record_hash"] != _record_hash(payload):
        raise LabelError("label record_hash mismatch")
    if payload["authority"] != AUTHORITY:
        raise LabelError("label authority changed")
    source = _exact(payload["source"], {"as_of", "run_id", "feed_rows_hash"}, "source")
    snapshot_keys = (ANNOUNCEMENT_SNAPSHOT_KEYS if payload["target_kind"] == "ANNOUNCEMENT"
                     else E1_SNAPSHOT_KEYS)
    _exact(payload["snapshot"], snapshot_keys, "snapshot")
    if payload["target_kind"] == "ANNOUNCEMENT":
        if payload["item_id"] != feed_contract.item_id(
                payload["ts_code"], payload["snapshot"]["source_channel"],
                payload["snapshot"]["notice_date"], payload["snapshot"]["title"]):
            raise LabelError("label item_id does not bind its announcement snapshot")
        # governance-mutation: RESEARCH_INCREMENT_NO_AFTER_AS_OF_LABEL
        if payload["snapshot"]["eligibility"] == "AFTER_AS_OF_EXCLUDED":
            raise LabelError("an item published after as_of cannot be labeled for as_of")
    else:
        snap = payload["snapshot"]
        if payload["item_id"] != e1_item_id(payload["ts_code"], str(snap["kind"]), str(snap["source"]),
                                            str(snap["ann_date"]), str(snap["period"])):
            raise LabelError("label item_id does not bind its E1 snapshot")
        if source["run_id"] is not None:
            raise LabelError("an E1 label has no run binding (basis SAME_AS_OF): run_id must be null")
        # governance-mutation: RESEARCH_INCREMENT_NO_AFTER_AS_OF_E1_LABEL
        if _e1_after_as_of(snap, source["as_of"]):
            raise LabelError("an E1 event announced after as_of cannot be labeled for as_of")
    validate_label_semantics(payload, source["as_of"])
    content = has_content(payload["target_kind"], payload["snapshot"], source["as_of"])
    # governance-mutation: RESEARCH_INCREMENT_PROVENANCE_MACHINE_FILLED
    if payload["provenance_tier"] != ("E1" if content else "DATA_BLOCKED"):
        raise LabelError("provenance_tier is machine-derived, not a human choice")
    exposure = _exact(payload["exposure"], {"labeled_at", "future_seen", "saw_other_label",
                                            "bars_basis"}, "exposure")
    if (type(exposure["future_seen"]) is not bool or type(exposure["saw_other_label"]) is not bool
            or exposure["bars_basis"] != BARS_BASIS):
        raise LabelError("exposure must declare future_seen/saw_other_label; bars are unavailable")
    labeled_at = _aware(exposure["labeled_at"], "labeled_at")
    decided_at = _aware(payload["human_decision"].get("decided_at"), "decided_at")
    if labeled_at > decided_at:
        raise LabelError("a label cannot postdate the batch decision")
    if payload["target_kind"] == "ANNOUNCEMENT":
        # governance-mutation: RESEARCH_INCREMENT_LABEL_AFTER_CAPTURE
        if labeled_at < _aware(payload["snapshot"]["captured_at"], "captured_at"):
            raise LabelError("a label cannot predate the capture of its item")


def _input_projection(label: Mapping[str, Any]) -> dict[str, Any]:
    exposure = label["exposure"]
    return {"item_id": label["item_id"], "target_kind": label["target_kind"],
            "thesis_ref": label["thesis_ref"], "thesis_relevance": label["thesis_relevance"],
            "research_increment": label["research_increment"],
            "increment_ref": label["increment_ref"], "note": label["note"],
            "labeled_at": exposure["labeled_at"], "future_seen": exposure["future_seen"],
            "saw_other_label": exposure["saw_other_label"]}


def batch_hash_for(as_of: str, run_id: str, reviewer: str, labels: Sequence[Mapping[str, Any]]) -> str:
    """Bare-hex hash the reviewer quotes (first 12) in the authorization text."""
    ordered = sorted((dict(label) for label in labels), key=lambda label: label["item_id"])
    return _hash({"as_of": as_of, "run_id": run_id, "claimed_reviewer": reviewer,
                  "labels": ordered})


def replay(path: Path) -> dict[str, Any]:
    """Replay the whole ledger. Returns closed/abandoned batches; raises on corruption."""
    path = Path(path)
    if not os.path.lexists(path):
        _anchor, status = event_ledger.read_anchor(str(path))
        if status != "absent":
            raise LabelError("label ledger is missing but its anchor exists")
        return {"closed": [], "abandoned": [], "open": None}
    if path.is_symlink() or not path.is_file():
        raise LabelError("label ledger must be a regular file")
    chain = event_ledger.verify(str(path))
    anchor = event_ledger.verify_anchor(str(path))
    if not chain["ok"] or not anchor["ok"]:
        raise LabelError(f"label ledger chain/anchor invalid: {(chain['errors'] + anchor['errors'])[:3]}")
    closed: list[dict[str, Any]] = []
    abandoned: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    batch_ids: set[str] = set()
    labeled: set[tuple[str, str]] = set()
    for line in event_ledger._read_lines(str(path)):
        outer = json.loads(line)
        kind, payload = outer.get("kind"), outer.get("payload")
        if kind not in LEDGER_KINDS or not isinstance(payload, Mapping):
            raise LabelError(f"unexpected kind in the label ledger: {kind}")
        if payload.get("record_hash") != _record_hash(payload):
            raise LabelError(f"{kind} record_hash mismatch")
        if payload.get("registered_at", _registered_at(outer["ts"])) != _registered_at(outer["ts"]):
            raise LabelError(f"{kind} is not bound to its R-015 timestamp")
        if kind == INTENT_KIND:
            _exact(payload, INTENT_KEYS, "intent payload")
            if (payload["schema"] != INTENT_SCHEMA or payload["authority"] != AUTHORITY
                    or outer["id"] != payload["batch_id"] or payload["batch_id"] in batch_ids
                    or payload["batch_id"] != "rilb_" + payload["batch_hash"][:32]):
                raise LabelError("intent identity is invalid or duplicated")
            _validate_human_decision(payload["human_decision"], payload["batch_hash"])
            if (not isinstance(payload["item_ids"], list) or not payload["item_ids"]
                    or payload["item_ids"] != sorted(set(payload["item_ids"]))):
                raise LabelError("intent item_ids must be sorted and unique")
            if _aware(payload["human_decision"]["decided_at"], "decided_at") > _r015(outer["ts"]):
                raise LabelError("intent registered before its human decision")
            if current is not None:  # the previous batch never closed
                abandoned.append(current)
            batch_ids.add(payload["batch_id"])
            current = {"intent": copy.deepcopy(dict(payload)), "labels": []}
        elif kind == LABEL_KIND:
            if current is None:
                raise LabelError("label without an open batch intent")
            _validate_label_payload(payload)
            intent = current["intent"]
            if (payload["batch_id"] != intent["batch_id"]
                    or payload["human_decision"] != intent["human_decision"]
                    or payload["source"]["as_of"] != intent["as_of"]
                    or payload["source"]["run_id"] != (
                        intent["run_id"] if payload["target_kind"] == "ANNOUNCEMENT" else None)
                    or payload["item_id"] not in intent["item_ids"]
                    or payload["item_id"] in {l["item_id"] for l in current["labels"]}
                    or payload["source"]["feed_rows_hash"] != (
                        intent["feed_rows_hash"] if payload["target_kind"] == "ANNOUNCEMENT"
                        else intent["e1_rows_hash"])
                    or outer["id"] != "ril_" + payload["record_hash"][7:39]):
                raise LabelError("label does not belong to its open batch")
            current["labels"].append(copy.deepcopy(dict(payload)))
        else:
            if current is None:
                raise LabelError("closure without an open batch")
            _exact(payload, CLOSURE_KEYS, "closure payload")
            intent = current["intent"]
            labels = current["labels"]
            reviewer = intent["human_decision"]["claimed_reviewer"]
            if (payload["schema"] != CLOSURE_SCHEMA or payload["batch_id"] != intent["batch_id"]
                    or payload["batch_hash"] != intent["batch_hash"]
                    or outer["id"] != "rilc_" + intent["batch_hash"][:32]
                    or sorted(l["item_id"] for l in labels) != sorted(intent["item_ids"])
                    or payload["label_record_hashes"] != [l["record_hash"] for l in labels]):
                raise LabelError("closure does not seal exactly its intent's labels")
            # governance-mutation: RESEARCH_INCREMENT_BATCH_HASH_REPLAY
            if batch_hash_for(intent["as_of"], intent["run_id"], reviewer,
                              [_input_projection(l) for l in labels]) != intent["batch_hash"]:
                raise LabelError("closed labels differ from the authorized batch")
            for label in labels:
                key = (label["item_id"], reviewer)
                # governance-mutation: RESEARCH_INCREMENT_ONE_LABEL_PER_REVIEWER
                if key in labeled:
                    raise LabelError("an item was labeled twice by the same reviewer")
                labeled.add(key)
            closed.append(current)
            current = None
    return {"closed": closed, "abandoned": abandoned, "open": current}


def labeled_item_ids(state: Mapping[str, Any]) -> set[str]:
    """Items with a closed label. Abandoned/open batches never labelled anything,
    so their items come back to propose (and are counted separately)."""
    # governance-mutation: RESEARCH_INCREMENT_NOVELTY_CLOSED_ONLY
    batches = list(state["closed"])
    return {label["item_id"] for batch in batches for label in batch["labels"]}


def unclosed_item_ids(state: Mapping[str, Any]) -> set[str]:
    batches = list(state["abandoned"]) + ([state["open"]] if state.get("open") else [])
    return {item for batch in batches for item in batch["intent"]["item_ids"]}


def _overall_source_status(statuses: set[str]) -> str:
    # governance-mutation: RESEARCH_INCREMENT_VERIFY_EVERY_LABEL_COMPARED
    if MISMATCH in statuses:
        return MISMATCH
    if statuses == {VERIFIED}:
        return VERIFIED
    return PARTIAL if VERIFIED in statuses else SNAPSHOT_ONLY


def verify(path: Path, *, bundle_root: Path | None = None,
           e1_layer: Path | None = None) -> dict[str, Any]:
    """Replay the ledger; compare each closed label with its source when still available.

    VERIFIED_AGAINST_SOURCE is reported only when every label in the batch was
    re-derived from its source: announcements from the bundle feed (same run,
    same rows_hash), E1 events from an --e1-layer with the same as_of and the
    batch's e1 rows_hash. Anything not compared stays SNAPSHOT_ONLY.
    """
    try:
        state = replay(path)
    except (LabelError, ValueError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        return {"ok": False, "batches_closed": 0, "labels_closed": 0, "errors": [str(exc)]}
    sources = []
    ok = True
    for batch in state["closed"]:
        intent = batch["intent"]
        per_kind: dict[str, dict[str, Any]] = {}
        announcements = [l for l in batch["labels"] if l["target_kind"] == "ANNOUNCEMENT"]
        if announcements:
            status = SNAPSHOT_ONLY
            bundle = (Path(bundle_root) / intent["as_of"] / intent["run_id"]) if bundle_root else None
            if bundle is not None and bundle.is_dir():
                try:
                    feed, _manifest, battery = feed_contract.load_bundle_feed(bundle)
                    items = announcement_items(feed, battery)
                    mismatched = feed["rows_hash"] != intent["feed_rows_hash"] or any(
                        items.get(l["item_id"], {}).get("snapshot") != l["snapshot"]
                        for l in announcements)
                    status = MISMATCH if mismatched else VERIFIED
                except feed_contract.AnnouncementFeedError:
                    status = MISMATCH
            per_kind["ANNOUNCEMENT"] = {"labels": len(announcements), "source_status": status}
        events = [l for l in batch["labels"] if l["target_kind"] == "E1_EVENT"]
        if events:
            status = SNAPSHOT_ONLY
            _basis, layer = load_e1_layer(e1_layer, intent["as_of"])
            # A layer with another rows_hash is not this batch's source: not compared.
            if layer is not None and layer["rows_hash"] == intent["e1_rows_hash"]:
                items = e1_items(layer)
                mismatched = any(items.get(l["item_id"], {}).get("snapshot") != l["snapshot"]
                                 for l in events)
                status = MISMATCH if mismatched else VERIFIED
            per_kind["E1_EVENT"] = {"labels": len(events), "source_status": status}
        overall = _overall_source_status({entry["source_status"] for entry in per_kind.values()})
        if overall == MISMATCH:
            ok = False
        sources.append({"batch_id": intent["batch_id"], "as_of": intent["as_of"],
                        "run_id": intent["run_id"], "source_status": overall,
                        "per_kind": per_kind})
    return {
        "ok": ok,
        "batches_closed": len(state["closed"]),
        "labels_closed": sum(len(batch["labels"]) for batch in state["closed"]),
        "batches_abandoned": [batch["intent"]["batch_id"] for batch in state["abandoned"]],
        "batch_open": state["open"]["intent"]["batch_id"] if state["open"] else None,
        "sources": sources,
        "errors": [],
    }


# ── propose (blind, capped, novelty-filtered) ─────────────────────────────

def _context(bundle: Path, e1_layer: Path | None, *, u4_ledger: Path, decision_sheets: Path,
             watchlist: Path) -> dict[str, Any]:
    try:
        feed, _manifest, battery = feed_contract.load_bundle_feed(Path(bundle))
    except feed_contract.AnnouncementFeedError as exc:
        raise LabelError(f"bundle announcement feed is unavailable: {exc}") from exc
    scope = live_scope(feed["as_of"], u4_ledger=u4_ledger, decision_sheets=decision_sheets,
                       watchlist=watchlist)
    e1_status, layer = load_e1_layer(e1_layer, feed["as_of"])
    items = announcement_items(feed, battery)
    items.update(e1_items(layer))
    return {"feed": feed, "scope": scope, "items": items, "e1_status": e1_status,
            "e1_rows_hash": layer["rows_hash"] if layer else None}


def _thesis_options(scope: Mapping[str, Any], code: str) -> list[dict[str, Any]]:
    refs = scope["tickers"].get(code, {}).get("thesis_refs") or []
    return list(refs) if refs else [{"kind": "NONE", "ref": None}]


def _thesis_ref_age_days(scope: Mapping[str, Any], code: str, as_of: str) -> dict[str, int]:
    dates = scope["tickers"].get(code, {}).get("thesis_ref_dates") or {}
    cutoff = _date8(as_of)
    return {ref: (cutoff - _dt.date.fromisoformat(day)).days for ref, day in dates.items()}


def _announcement_coverage(feed: Mapping[str, Any], code: str) -> str:
    status = {entry["ts_code"]: entry["status"] for entry in feed["per_ticker"]}.get(code)
    if status is None:
        # The feed only covers the night's candidates; silence here is not "no news".
        return "NOT_CAPTURED_NOT_A_CANDIDATE"
    return "CAPTURED_OK" if status == "OK" else "DATA_BLOCKED"


def propose(bundle: Path, *, ledger: Path, e1_layer: Path | None = None,
            u4_ledger: Path = DEFAULT_U4_LEDGER, decision_sheets: Path = DEFAULT_DECISION_SHEETS,
            watchlist: Path = DEFAULT_WATCHLIST, window_days: int = WINDOW_DAYS,
            cap: int = PROPOSAL_CAP) -> dict[str, Any]:
    if type(window_days) is not int or not 1 <= window_days <= WINDOW_DAYS:
        raise LabelError("window_days must be 1..2")
    if type(cap) is not int or not 1 <= cap <= PROPOSAL_CAP:
        raise LabelError("cap must be 1..20")
    context = _context(bundle, e1_layer, u4_ledger=u4_ledger, decision_sheets=decision_sheets,
                       watchlist=watchlist)
    feed, scope = context["feed"], context["scope"]
    cutoff = _date8(feed["as_of"])
    start = cutoff - _dt.timedelta(days=window_days - 1)
    state = replay(ledger)
    already = labeled_item_ids(state)
    unclosed = unclosed_item_ids(state) - already
    excluded = {"already_labelled": 0, "outside_window": 0, "after_as_of": 0,
                "date_unverifiable": 0, "out_of_scope": 0}
    eligible = []
    for item in context["items"].values():
        if item["ts_code"] not in scope["tickers"]:
            excluded["out_of_scope"] += 1
            continue
        # governance-mutation: RESEARCH_INCREMENT_PROPOSE_NOVELTY
        if item["item_id"] in already:
            excluded["already_labelled"] += 1
            continue
        if item["target_kind"] == "ANNOUNCEMENT" and item["snapshot"]["eligibility"] != "AT_OR_BEFORE_AS_OF":
            key = ("after_as_of" if item["snapshot"]["eligibility"] == "AFTER_AS_OF_EXCLUDED"
                   else "date_unverifiable")
            excluded[key] += 1
            continue
        observed = _item_date(item)
        if observed is None:
            excluded["date_unverifiable"] += 1
            continue
        if observed > cutoff:
            excluded["after_as_of"] += 1
            continue
        # governance-mutation: RESEARCH_INCREMENT_PROPOSE_WINDOW
        if not start <= observed <= cutoff:
            excluded["outside_window"] += 1
            continue
        eligible.append(item)
    eligible.sort(key=lambda item: (-_item_date(item).toordinal(), item["ts_code"], item["item_id"]))
    chosen, over_cap = eligible[:cap], eligible[cap:]
    blocked_in_scope = [entry["ts_code"] for entry in feed["per_ticker"]
                        if entry["ts_code"] in scope["tickers"] and entry["status"] != "OK"]
    scope_entries = []
    for code, entry in scope["tickers"].items():
        # governance-mutation: RESEARCH_INCREMENT_SCOPE_COVERAGE_DISCLOSED
        scope_entries.append(dict(entry, announcement_coverage=_announcement_coverage(feed, code)))
    not_in_feed = [entry["ts_code"] for entry in scope_entries
                   if entry["announcement_coverage"] == "NOT_CAPTURED_NOT_A_CANDIDATE"]
    items = []
    for item in chosen:
        view = _proposal_view(item)
        view["thesis_ref_options"] = _thesis_options(scope, item["ts_code"])
        view["thesis_ref_age_days"] = _thesis_ref_age_days(scope, item["ts_code"], feed["as_of"])
        items.append(view)
    template = [{
        "item_id": item["item_id"], "target_kind": item["target_kind"],
        "thesis_ref": item["thesis_ref_options"][0] if len(item["thesis_ref_options"]) == 1 else None,
        "thesis_relevance": None, "research_increment": None, "increment_ref": None,
        "note": None, "labeled_at": None, "future_seen": None, "saw_other_label": None,
    } for item in items]
    return {
        "schema": PROPOSAL_SCHEMA, "schema_version": SCHEMA_VERSION,
        "as_of": feed["as_of"], "run_id": feed["run_id"], "feed_rows_hash": feed["rows_hash"],
        "e1_basis": context["e1_status"],
        "window": {"start": start.isoformat(), "end": cutoff.isoformat(), "calendar_days": window_days},
        "cap": cap, "blind": True,
        "blind_to": ["existing_labels", *PROPOSAL_HIDDEN_SNAPSHOT_KEYS],
        "scope": {"tickers": scope_entries, "source_status": scope["source_status"]},
        "scope_tickers_news_blocked": blocked_in_scope,
        "scope_tickers_not_in_feed": not_in_feed,
        "items": items,
        "not_reviewed_over_cap": [item["item_id"] for item in over_cap],
        "excluded_counts": excluded,
        "reproposed_from_unclosed_batch": sum(item["item_id"] in unclosed for item in chosen),
        "input_template": {"schema": INPUT_SCHEMA, "schema_version": SCHEMA_VERSION,
                           "as_of": feed["as_of"], "run_id": feed["run_id"],
                           "human_decision": {"claimed_reviewer": None,
                                              "identity_verification": "UNAVAILABLE",
                                              "decided_at": None, "authorization_text": None,
                                              "authorization_evidence_ref": None},
                           "labels": template},
        "note": ("Blind proposal: existing labels and the machine news display verdict are never "
                 "shown. Human axes are null and record refuses nulls. same_day_as_as_of items "
                 "may postdate the as_of close. Scope tickers that were not candidates tonight "
                 "have no announcement capture (NOT_CAPTURED_NOT_A_CANDIDATE), which is not "
                 "the same as having no announcements."),
        "disclaimer": DISCLAIMER,
    }


# ── record (one authorization per batch) ──────────────────────────────────

@contextlib.contextmanager
def _batch_lock(path: Path) -> Iterator[None]:
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".batch.lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def prepare_batch(bundle: Path, raw: Any, *, e1_layer: Path | None = None,
                  u4_ledger: Path = DEFAULT_U4_LEDGER,
                  decision_sheets: Path = DEFAULT_DECISION_SHEETS,
                  watchlist: Path = DEFAULT_WATCHLIST) -> dict[str, Any]:
    """Validate a human batch against the bundle; return labels minus registration."""
    raw = _exact(raw, INPUT_KEYS, "label input")
    if raw["schema"] != INPUT_SCHEMA or raw["schema_version"] != SCHEMA_VERSION:
        raise LabelError("label input schema mismatch")
    context = _context(bundle, e1_layer, u4_ledger=u4_ledger, decision_sheets=decision_sheets,
                       watchlist=watchlist)
    feed, scope, items = context["feed"], context["scope"], context["items"]
    if raw["as_of"] != feed["as_of"] or raw["run_id"] != feed["run_id"]:
        raise LabelError("label input belongs to another bundle")
    human = raw["human_decision"]
    _exact(human, HUMAN_DECISION_KEYS, "human_decision")
    reviewer = human.get("claimed_reviewer")
    if reviewer not in CLAIMED_REVIEWERS:
        raise LabelError("reviewer identity boundary changed")
    if not isinstance(raw["labels"], list) or not raw["labels"]:
        raise LabelError("a batch needs at least one label")
    if len(raw["labels"]) > PROPOSAL_CAP:
        raise LabelError("a batch holds at most 20 labels")
    projections, labels, seen = [], [], set()
    for entry in raw["labels"]:
        entry = _exact(entry, INPUT_LABEL_KEYS, "label")
        item = items.get(entry["item_id"])
        if item is None or item["target_kind"] != entry["target_kind"]:
            raise LabelError(f"item is not in this bundle's feed/E1 layer: {entry['item_id']}")
        if item["item_id"] in seen:
            raise LabelError("an item appears twice in one batch")
        seen.add(item["item_id"])
        if item["ts_code"] not in scope["tickers"]:
            raise LabelError(f"{item['ts_code']} has no live thesis scope")
        options = _thesis_options(scope, item["ts_code"])
        # governance-mutation: RESEARCH_INCREMENT_THESIS_REF_IN_SCOPE
        if entry["thesis_ref"] not in options:
            raise LabelError("thesis_ref is not a live thesis for this ticker at as_of")
        if type(entry["future_seen"]) is not bool or type(entry["saw_other_label"]) is not bool:
            raise LabelError("future_seen and saw_other_label must be declared explicitly")
        view = _machine_view(item)
        label = {
            "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "batch_id": None,
            "item_id": item["item_id"], "target_kind": item["target_kind"],
            "ts_code": item["ts_code"], "snapshot": copy.deepcopy(item["snapshot"]),
            "source": dict(item["source"]), "thesis_ref": dict(entry["thesis_ref"]),
            "provenance_tier": view["provenance_tier"],
            "thesis_relevance": entry["thesis_relevance"],
            "research_increment": entry["research_increment"],
            "increment_ref": entry["increment_ref"], "note": entry["note"],
            "exposure": {"labeled_at": entry["labeled_at"], "future_seen": entry["future_seen"],
                         "saw_other_label": entry["saw_other_label"], "bars_basis": BARS_BASIS},
            "human_decision": None, "authority": dict(AUTHORITY),
        }
        if label["target_kind"] == "ANNOUNCEMENT" and \
                label["snapshot"]["eligibility"] == "AFTER_AS_OF_EXCLUDED":
            raise LabelError("an item published after as_of cannot be labeled for as_of")
        if label["target_kind"] == "E1_EVENT" and _e1_after_as_of(label["snapshot"], feed["as_of"]):
            raise LabelError("an E1 event announced after as_of cannot be labeled for as_of")
        validate_label_semantics(label, feed["as_of"])
        labels.append(label)
        projections.append(dict(entry))
    batch_hash = batch_hash_for(feed["as_of"], feed["run_id"], reviewer, projections)
    return {"as_of": feed["as_of"], "run_id": feed["run_id"], "feed_rows_hash": feed["rows_hash"],
            "e1_rows_hash": context["e1_rows_hash"], "generated_at": feed["generated_at"],
            "human_decision": human, "labels": labels, "batch_hash": batch_hash}


def record(bundle: Path, raw: Any, *, ledger: Path, e1_layer: Path | None = None,
           u4_ledger: Path = DEFAULT_U4_LEDGER, decision_sheets: Path = DEFAULT_DECISION_SHEETS,
           watchlist: Path = DEFAULT_WATCHLIST, dry_run: bool = False) -> dict[str, Any]:
    prepared = prepare_batch(bundle, raw, e1_layer=e1_layer, u4_ledger=u4_ledger,
                             decision_sheets=decision_sheets, watchlist=watchlist)
    batch_hash = prepared["batch_hash"]
    batch_id = "rilb_" + batch_hash[:32]
    if dry_run:
        return {"dry_run": True, "batch_id": batch_id, "batch_hash": batch_hash,
                "authorization_must_contain": [batch_hash[:12], "离线|offline"],
                "labels": len(prepared["labels"]), "disclaimer": DISCLAIMER}
    human = _validate_human_decision(prepared["human_decision"], batch_hash)
    decided_at = _aware(human["decided_at"], "decided_at")
    if decided_at < _aware(prepared["generated_at"], "feed generated_at"):
        raise LabelError("a decision cannot predate the feed it labels")
    payloads = []
    for label in prepared["labels"]:
        payload = dict(label, batch_id=batch_id, human_decision=dict(human))
        payload["record_hash"] = _record_hash(payload)
        # Every label is proven valid before the first event reaches the ledger.
        _validate_label_payload(payload)
        payloads.append(payload)
    ledger = Path(ledger)
    with _batch_lock(ledger):
        state = replay(ledger)
        reviewer = human["claimed_reviewer"]
        done = {(l["item_id"], b["intent"]["human_decision"]["claimed_reviewer"])
                for b in state["closed"] for l in b["labels"]}
        if any((label["item_id"], reviewer) in done for label in prepared["labels"]):
            raise LabelError("an item in this batch is already labeled by this reviewer")
        if batch_id in {b["intent"]["batch_id"] for b in state["closed"] + state["abandoned"]} or (
                state["open"] and state["open"]["intent"]["batch_id"] == batch_id):
            raise LabelError("this exact batch was already registered")

        def build_intent(ts: str) -> tuple[str, dict[str, Any]]:
            if decided_at > _r015(ts):
                raise LabelError("decided_at is in the future of the ledger clock")
            payload = {
                "schema": INTENT_SCHEMA, "schema_version": SCHEMA_VERSION,
                "batch_id": batch_id, "batch_hash": batch_hash, "as_of": prepared["as_of"],
                "run_id": prepared["run_id"], "feed_rows_hash": prepared["feed_rows_hash"],
                "e1_rows_hash": prepared["e1_rows_hash"],
                "item_ids": sorted(label["item_id"] for label in prepared["labels"]),
                "human_decision": dict(human), "registered_at": _registered_at(ts),
                "authority": dict(AUTHORITY),
            }
            payload["record_hash"] = _record_hash(payload)
            return batch_id, payload

        event_ledger.append_stamped(INTENT_KIND, build_intent, path=str(ledger))
        hashes = []
        for payload in payloads:
            hashes.append(payload["record_hash"])
            event_ledger.append_stamped(
                LABEL_KIND, lambda _ts, p=payload: ("ril_" + p["record_hash"][7:39], p),
                path=str(ledger))

        def build_closure(ts: str) -> tuple[str, dict[str, Any]]:
            payload = {"schema": CLOSURE_SCHEMA, "schema_version": SCHEMA_VERSION,
                       "batch_id": batch_id, "batch_hash": batch_hash,
                       "label_record_hashes": hashes, "registered_at": _registered_at(ts)}
            payload["record_hash"] = _record_hash(payload)
            return "rilc_" + batch_hash[:32], payload

        event_ledger.append_stamped(CLOSURE_KIND, build_closure, path=str(ledger))
        final = replay(ledger)
        if not final["closed"] or final["closed"][-1]["intent"]["batch_id"] != batch_id:
            raise LabelError("batch did not replay as closed after writing")
    return {"dry_run": False, "batch_id": batch_id, "batch_hash": batch_hash,
            "labels": len(hashes), "disclaimer": DISCLAIMER}


# ── report (descriptive only) ─────────────────────────────────────────────

def _rate(numerator: int, denominator: int, min_n: int = MIN_N) -> dict[str, Any]:
    # governance-mutation: RESEARCH_INCREMENT_RATE_WITHHELD_BELOW_MIN
    withheld = denominator < min_n
    return {"numerator": numerator, "denominator": denominator, "min_n": min_n,
            "rate": None if withheld else round(numerator / denominator, 4),
            "level": "RATE_WITHHELD_N_BELOW_MIN" if withheld else "DESCRIPTIVE"}


def report(ledger: Path) -> dict[str, Any]:
    state = replay(ledger)
    labels = [dict(label, reviewer=batch["intent"]["human_decision"]["claimed_reviewer"])
              for batch in state["closed"] for label in batch["labels"]]
    # Labels made after seeing the post-as_of path are counted, never evaluated.
    # governance-mutation: RESEARCH_INCREMENT_REPORT_EXCLUDES_FUTURE_SEEN
    evaluable = [l for l in labels if l["exposure"]["future_seen"] is False]
    relevant = [l for l in evaluable if l["thesis_relevance"] in RELEVANT]
    relevant_readable = [l for l in relevant if l["research_increment"] != "DATA_BLOCKED"]
    no_increment = [l for l in relevant_readable if l["research_increment"] == "NONE"]
    crosstab = {row: {"ANY_INCREMENT": 0, "NO_INCREMENT": 0, "ONLY_DATA_BLOCKED": 0}
                for row in ("SPIKE", "NORMAL", "BLOCKED")}
    nights: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for label in evaluable:
        if label["target_kind"] == "ANNOUNCEMENT":
            nights.setdefault((label["source"]["as_of"], label["ts_code"]), []).append(label)
    for group in nights.values():
        verdicts = {l["snapshot"]["news_display_verdict"] for l in group}
        # A blocked or missing display verdict is its own row, never NORMAL.
        # governance-mutation: RESEARCH_INCREMENT_CROSSTAB_BLOCKED_ROW
        row = verdicts.pop() if len(verdicts) == 1 and None not in verdicts else "BLOCKED"
        increments = {l["research_increment"] for l in group}
        if increments & set(CHANGE_INCREMENTS):
            column = "ANY_INCREMENT"
        elif increments == {"DATA_BLOCKED"}:
            column = "ONLY_DATA_BLOCKED"
        else:
            column = "NO_INCREMENT"
        crosstab[row][column] += 1
    by_item: dict[str, list[dict[str, Any]]] = {}
    for label in evaluable:
        by_item.setdefault(label["item_id"], []).append(label)
    pairs, excluded_pairs = [], 0
    for group in by_item.values():
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if first["reviewer"] == second["reviewer"]:
                    continue
                # governance-mutation: RESEARCH_INCREMENT_BLIND_PAIRS_ONLY
                if first["exposure"]["saw_other_label"] or second["exposure"]["saw_other_label"]:
                    excluded_pairs += 1
                    continue
                pairs.append((first, second))
    agreement = {axis: _rate(sum(a[axis] == b[axis] for a, b in pairs), len(pairs))
                 for axis in ("thesis_relevance", "research_increment")}
    return {
        "schema": REPORT_SCHEMA, "schema_version": SCHEMA_VERSION,
        "labels_closed": len(labels),
        "batches_closed": len(state["closed"]),
        "batches_abandoned": len(state["abandoned"]),
        "counts": {
            "by_relevance": {key: sum(l["thesis_relevance"] == key for l in labels) for key in RELEVANCE},
            "by_increment": {key: sum(l["research_increment"] == key for l in labels) for key in INCREMENTS},
            "future_seen": sum(l["exposure"]["future_seen"] for l in labels),
            "same_day_as_as_of": sum(bool(l["snapshot"].get("same_day_as_as_of")) for l in labels),
            "late_capture": sum((_capture_lag_days(l) or 0) >= LATE_CAPTURE_DAYS for l in labels),
        },
        "evaluation_basis": {"evaluable_labels": len(evaluable),
                             "future_seen_excluded": len(labels) - len(evaluable),
                             "note": "shares, crosstab and agreement use future_seen=false labels only"},
        "relevant_but_no_increment_share": dict(
            _rate(len(no_increment), len(relevant_readable)),
            data_blocked_excluded=len(relevant) - len(relevant_readable)),
        "no_live_thesis_share": _rate(sum(l["thesis_relevance"] == "NO_LIVE_THESIS" for l in evaluable),
                                      len(evaluable)),
        "news_display_vs_increment_crosstab": {
            "unit": "ticker_night", "rows": crosstab,
            "note": "SPIKE/NORMAL is an unvalidated display label; BLOCKED = no display verdict."},
        "inter_reviewer_agreement": {"blind_pairs": len(pairs),
                                     "excluded_pairs_saw_other_label": excluded_pairs,
                                     "per_axis": agreement},
        "claim_status": "DESCRIPTIVE_ONLY",
        "authority": {"claim_allowed": False, "posture_authority": False, "gate_authority": False},
        "retention_status": "LOCAL_ONLY_UNBACKED",
        "disclaimer": DISCLAIMER,
    }


# ── CLI ──────────────────────────────────────────────────────────────────

def _load_json_file(path: Path) -> Any:
    def strict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise LabelError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=strict)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("propose", "record", "verify", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        if name in ("propose", "record"):
            cmd.add_argument("--bundle", type=Path, required=True)
            cmd.add_argument("--e1-layer", type=Path)
            cmd.add_argument("--u4-ledger", type=Path, default=DEFAULT_U4_LEDGER)
            cmd.add_argument("--decision-sheets", type=Path, default=DEFAULT_DECISION_SHEETS)
            cmd.add_argument("--watchlist", type=Path, default=DEFAULT_WATCHLIST)
        if name == "propose":
            cmd.add_argument("--window-days", type=int, default=WINDOW_DAYS)
            cmd.add_argument("--cap", type=int, default=PROPOSAL_CAP)
        if name == "record":
            cmd.add_argument("--labels", type=Path, required=True)
            cmd.add_argument("--dry-run", action="store_true")
        if name == "verify":
            cmd.add_argument("--bundle-root", type=Path)
            cmd.add_argument("--e1-layer", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "propose":
            out = propose(args.bundle, ledger=args.ledger, e1_layer=args.e1_layer,
                          u4_ledger=args.u4_ledger, decision_sheets=args.decision_sheets,
                          watchlist=args.watchlist, window_days=args.window_days, cap=args.cap)
        elif args.command == "record":
            out = record(args.bundle, _load_json_file(args.labels), ledger=args.ledger,
                         e1_layer=args.e1_layer, u4_ledger=args.u4_ledger,
                         decision_sheets=args.decision_sheets, watchlist=args.watchlist,
                         dry_run=args.dry_run)
        elif args.command == "verify":
            out = verify(args.ledger, bundle_root=args.bundle_root, e1_layer=args.e1_layer)
        else:
            out = report(args.ledger)
    except (LabelError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}, ensure_ascii=False))
        print(DISCLAIMER)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print(DISCLAIMER)
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
