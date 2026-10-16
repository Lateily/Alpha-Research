"""Deterministic operational brief from a frozen, local read-only observation."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import workbench_evidence as evidence
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from team_ai_workspace import SECRET_PATTERNS


class SnapshotBriefError(ValueError):
    pass


def reject_credentials(value):
    # Redaction is not byte-identical freezing; refuse instead.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            # Inspect decoded values and common log escapes, never rewritten originals.
            text = item.replace("\\t", "\t").replace("\\n", "\n").replace("\\r", "\r")
            if any(pattern.search(text.encode()) for _name, pattern in SECRET_PATTERNS):
                raise SnapshotBriefError("CREDENTIAL_SHAPED_CONTENT_REFUSED")
            if re.search(r"(?i)(authorization\s*:\s*bearer\s+\S+|\bbearer\s+[A-Za-z0-9_.-]{8,}|\bsk-[A-Za-z0-9_-]{12,}|\bAKIA[A-Z0-9]{16})", text):
                raise SnapshotBriefError("CREDENTIAL_SHAPED_CONTENT_REFUSED")


def render(snapshot):
    evidence.verify(snapshot)
    reject_credentials(snapshot)
    rid, date = snapshot.get("published_run_id"), snapshot.get("target_trade_date")
    if not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
        raise SnapshotBriefError("PUBLICATION_DATE_INVALID")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise SnapshotBriefError("PUBLICATION_DATE_INVALID") from None
    modules = evidence.module_sources(snapshot)
    if modules[0]["identity_status"] != "BOUND_TO_PUBLISHED_RUN":
        raise SnapshotBriefError("PUBLICATION_IDENTITY_REQUIRED")
    # governance-mutation: WORKBENCH_SNAPSHOT_BRIEF_BINDING
    if any(row.get("binding") == "MISMATCH" for row in snapshot["records"].values()):
        raise SnapshotBriefError("FROZEN_SOURCE_HASH_MISMATCH")
    if any(row["identity_status"] in {"RUN_MISMATCH", "DATE_MISMATCH"} for row in modules):
        raise SnapshotBriefError("FROZEN_MODULE_IDENTITY_MISMATCH")
    for path, record in snapshot["records"].items():
        if record.get("binding") != "MATCH":
            continue
        payload = record.get("payload") or {}
        source_run = payload.get("run_id")
        source_date = payload.get("target_trade_date")
        if source_date is None and re.fullmatch(r"\d{8}", str(payload.get("as_of", ""))):
            source_date = payload["as_of"]
        if ((source_run is not None and source_run != rid)
                or (source_date is not None and source_date != date)):
            raise SnapshotBriefError("FROZEN_MODULE_IDENTITY_MISMATCH")
    citations = []

    def field(path, keys):
        record = snapshot["records"].get(path, {})
        value = record.get("payload")
        if record.get("binding") != "MATCH" and path != "experiments/execution_tracker/nightly_run.json":
            return "DATA_BLOCKED"
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            elif isinstance(value, list) and isinstance(key, int) and -len(value) <= key < len(value):
                value = value[key]
            else:
                value = None
                break
        if value is None:
            return "DATA_BLOCKED"
        citation = {"id": f"C{len(citations)+1:02d}", "path": path,
                    "json_pointer": "/" + "/".join(str(k) for k in keys),
                    "source_sha256": record.get("source_sha256"), "value": value,
                    "evidence_kind": "LOCAL_MODEL_ARTIFACT_NOT_ISSUER_DISCLOSURE"}
        citations.append(citation)
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return f"{text} [{citation['id']}]"

    public = "public/data/v2/"
    attempt = "experiments/execution_tracker/nightly_run.json"
    paper = public + "model_portfolio_state.json"
    health = public + "funnel_health.json"
    macro = public + "macro/"
    input_line = f"输入快照 SHA256 `{snapshot['snapshot_hash']}`；取得时间 {snapshot['observed_at']}"
    if "frozen_input_hash" in snapshot:
        if not isinstance(snapshot["frozen_input_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot["frozen_input_hash"]):
            raise SnapshotBriefError("FROZEN_INPUT_IDENTITY_INVALID")
        input_line = f"输入封套 SHA256 `{snapshot['frozen_input_hash']}`；按原件内容绑定，取得时间保留于封套。"
    lines = [f"# 研究运行简报 · {date}",
             f"WORKFLOW_DEBUG · 人工核验 PENDING · 冻结 run `{rid}`",
             input_line,
             "## 运行与展示身份",
             f"最新尝试：{field(attempt, ['run_id'])}；状态 {field(attempt, ['report'])}。",
             f"最后发布与本次展示：`{rid}`，发布交易日 `{date}`。最新尝试不是最后发布。",
             "## 模拟组合与交易",
             f"现金：{field(paper, ['data', 'cash'])}；未平仓：{field(paper, ['data', 'open_positions'])}。",
             f"最近 NAV：{field(paper, ['data', 'nav_latest'])}；源端数据质量：{field(paper, ['data_quality'])}。",
             f"历史平仓数量：{field(paper, ['data', 'closed_trades_n'])}。费用及当日逐单结果未在本简报独立核验；不补为 0。",
             "## 市场与板块",
             f"轮动观察窗口：{field(public+'rotation_panel.json', ['data', 'days'])}。",
             f"覆盖板块数量：{field(public+'rotation_panel.json', ['data', 'n_sectors'])}（不是信号胜率）。",
             "资金方向不等于价格预测，也不能据此归因为组合盈亏。",
             "## Macro 与候选",
             f"宏观来源状态：{field(macro+'source_health.json', ['source_health'])}。",
             f"事件实际值及预期差状态：{field(macro+'macro_events.json', ['source_health'])}。",
             f"候选电池覆盖：{field(health, ['battery_coverage'])}；漏斗状态：{field(health, ['status'])}。",
             "## 策略变化与人工核查",
             "本任务没有改变策略、U4 决定或 paper 规则。市场如何影响本组合：NOT_EVALUATED，需持仓暴露及可检验归因证据。",
             "请核查来源绑定、Macro 缺口、逐票缺维及模拟 NAV 数据质量；运行完成不等于研究合格。",
             "## 模块来源",
             "|模块|源 run_id|发布交易日|源日期/时点|绑定|数据质量|",
             "|---|---|---|---|---|---|"]
    for row in modules:
        values = [row["module"], row["run_id"], row["published_trade_date"],
                  row["source_trade_date"] or row["source_as_of"], row["identity_status"], row["data_quality"]]
        lines.append("|" + "|".join(str(v or "UNAVAILABLE").replace("|", "\\|").replace("\n", " ") for v in values) + "|")
    lines += ["## 原始工件引用", *[f"- [{c['id']}] `{c['path']}` `{c['json_pointer']}` · SHA256 `{c['source_sha256']}`" for c in citations],
              "引用指向冻结的模型原始工件，不表示已核验发行人原文。", "不是买卖指令；研究信号，human executes。"]
    return {"report": "\n\n".join(lines)+"\n", "citations": citations, "module_sources": modules}


def verify(output):
    output = Path(output)
    receipt_raw = evidence.read_local(output, "receipt.json")
    receipt = evidence.parse(receipt_raw)
    # governance-mutation: WORKBENCH_SNAPSHOT_BRIEF_AUTHORITY
    if (receipt.get("human_review") != "PENDING" or receipt.get("production_authority") is not False
            or receipt.get("trade_authority") is not False or receipt.get("sample_purpose") != "WORKFLOW_DEBUG"):
        raise SnapshotBriefError("FROZEN_BRIEF_AUTHORITY_INVALID")
    snapshot = evidence.parse(evidence.read_local(output, "snapshot.json"))
    if (receipt.get("schema") != "ar.workbench-snapshot-brief.v1"
            or receipt.get("status") != "COMPLETED_WITH_GAPS"
            or receipt.get("run_id") != snapshot.get("published_run_id")
            or receipt.get("target_trade_date") != snapshot.get("target_trade_date")):
        raise SnapshotBriefError("FROZEN_BRIEF_RECEIPT_BINDING_INVALID")
    sources = evidence.parse(evidence.read_local(output, "source-manifest.json"))
    source_files = [item.get("file") for item in sources.values() if isinstance(item, dict)]
    if (len(source_files) != len(sources) or len(set(source_files)) != len(source_files)
            or any(not isinstance(name, str) or not re.fullmatch(r"sources/\d{3}\.json", name) for name in source_files)):
        raise SnapshotBriefError("FROZEN_BRIEF_INVENTORY_INVALID")
    allowed = {"snapshot.json", "report.md", "citations.json", "source-manifest.json"} | set(source_files)
    if not isinstance(receipt.get("files"), dict) or set(receipt["files"]) != allowed:
        raise SnapshotBriefError("FROZEN_BRIEF_INVENTORY_INVALID")
    for name, expected in receipt["files"].items():
        # governance-mutation: WORKBENCH_SNAPSHOT_BRIEF_OUTPUT_HASH
        if evidence.sha(evidence.read_local(output, name)) != expected:
            raise SnapshotBriefError("FROZEN_BRIEF_OUTPUT_CHANGED")
    sums = {}
    for line in evidence.read_local(output, "SHA256SUMS").decode("utf-8").splitlines():
        parts = line.split("  ")
        if len(parts) != 2 or parts[1] in sums or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise SnapshotBriefError("FROZEN_BRIEF_CHECKSUM_INVENTORY_INVALID")
        sums[parts[1]] = parts[0]
    if sums != {**receipt["files"], "receipt.json": evidence.sha(receipt_raw)}:
        raise SnapshotBriefError("FROZEN_BRIEF_CHECKSUM_INVENTORY_INVALID")
    if receipt.get("snapshot_hash") != snapshot.get("snapshot_hash"):
        raise SnapshotBriefError("FROZEN_BRIEF_RECEIPT_BINDING_INVALID")
    expected_paths = {p for p, row in snapshot["records"].items()
                      if row.get("status") == "OBSERVED" and not p.startswith("experiments/")}
    if set(sources) != expected_paths:
        raise SnapshotBriefError("FROZEN_SOURCE_COVERAGE_INVALID")
    for path, item in sources.items():
        raw = evidence.read_local(output, item["file"])
        record = snapshot["records"].get(path, {})
        if (item.get("sha256") != record.get("source_sha256")
                or evidence.sha(raw) != record.get("source_sha256")
                or evidence.parse(raw) != record.get("payload")):
            raise SnapshotBriefError("FROZEN_SOURCE_REPLAY_MISMATCH")
    expected = render(snapshot)
    if (evidence.read_local(output, "report.md") != expected["report"].encode()
            or evidence.read_local(output, "citations.json") != evidence.canonical(expected["citations"]).encode()):
        raise SnapshotBriefError("FROZEN_BRIEF_REPLAY_MISMATCH")
    return receipt


def run(source_root, output):
    snapshot = evidence.capture(Path(source_root))
    return _run_snapshot(snapshot, source_root, output)


def run_frozen(snapshot: dict, frozen_root: Path, output: Path) -> dict:
    from workbench_shared_inputs import validate_snapshot
    # governance-mutation: WORKBENCH_SHARED_FROZEN_INPUT
    validate_snapshot(snapshot, frozen_root, sealed_originals=True)
    return _run_snapshot(snapshot, frozen_root, output)


def _run_snapshot(snapshot, source_root, output):
    rendered = render(snapshot)
    output = Path(output)
    if output.is_symlink() or output.parent.is_symlink():
        raise SnapshotBriefError("FROZEN_BRIEF_PATH_INVALID")
    output.mkdir(mode=0o700, exist_ok=False)
    files = {"snapshot.json": evidence.canonical(snapshot).encode(),
             "report.md": rendered["report"].encode(),
             "citations.json": evidence.canonical(rendered["citations"]).encode()}
    # Freeze original bytes as well as the sanitized operational projection.
    # Never copy raw nightly stdout, which can contain credential-shaped output.
    sources = {}
    for index, (path, record) in enumerate(sorted(snapshot["records"].items())):
        if record.get("status") != "OBSERVED" or path.startswith("experiments/"):
            continue
        raw = evidence.read_local(Path(source_root), path)
        if evidence.sha(raw) != record["source_sha256"]:
            raise SnapshotBriefError("FROZEN_SOURCE_CHANGED")
        files[f"sources/{index:03d}.json"] = raw
        sources[path] = {"file": f"sources/{index:03d}.json", "sha256": evidence.sha(raw)}
    pointer_path = "public/data/v2/current_run.json"
    if evidence.sha(evidence.read_local(Path(source_root), pointer_path)) != snapshot["records"][pointer_path]["source_sha256"]:
        raise SnapshotBriefError("FROZEN_SOURCE_CHANGED")
    files["source-manifest.json"] = evidence.canonical(sources).encode()
    for name, raw in files.items():
        path = output / name
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(raw)
    receipt = {"schema": "ar.workbench-snapshot-brief.v1", "status": "COMPLETED_WITH_GAPS",
               "run_id": snapshot["published_run_id"], "target_trade_date": snapshot["target_trade_date"],
               "snapshot_hash": snapshot["snapshot_hash"], "human_review": "PENDING",
               "sample_purpose": "WORKFLOW_DEBUG", "production_authority": False, "trade_authority": False,
               "files": {name: evidence.sha(raw) for name, raw in files.items()}}
    (output / "receipt.json").write_text(evidence.canonical(receipt), encoding="utf-8")
    sums = {**receipt["files"], "receipt.json": evidence.sha((output / "receipt.json").read_bytes())}
    (output / "SHA256SUMS").write_text("".join(f"{h}  {name}\n" for name,h in sorted(sums.items())), encoding="utf-8")
    verify(output)
    return {**{k:v for k,v in receipt.items() if k!="files"}, **rendered,
            "report_sha256": receipt["files"]["report.md"], "log": ["INPUT_CAPTURED", "BINDINGS_CHECKED", "SOURCES_FROZEN", "REPORT_RENDERED", "OUTPUT_REOPENED_AND_VERIFIED"]}
