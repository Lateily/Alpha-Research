#!/usr/bin/env python3
"""Render/verify independent WORKFLOW_DEBUG artifacts; no network or ledger APIs."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_workflows import renderers
    from research_workflows.evidence import Evidence, TrialError, canonical, date8, exact, sha, text, timestamp
else:
    from . import renderers
    from .evidence import Evidence, TrialError, canonical, date8, exact, sha, text, timestamp

SMC_PARAMETERS = renderers.SMC_PARAMETERS
AUTHORITY = {"production": False, "u4_selection": False, "paper_registration": False, "trade": False}


def build(request, input_root):
    exact(request, {"schema", "workflow", "as_of", "generated_at", "mode", "sources", "authoring", "payload"}, "request")
    if request["schema"] != "ar.workflow-trial.v1" or request["workflow"] not in {"brief", "earnings", "smc"}:
        raise TrialError("unknown workflow or schema")
    if request["mode"] not in {"HISTORICAL_REPLAY", "SYNTHETIC"}:
        raise TrialError("trial accepts historical or synthetic input only")
    as_of = date8(request["as_of"])
    if timestamp(request["generated_at"]).strftime("%Y%m%d") < as_of:
        raise TrialError("generation precedes cutoff")
    exact(request["authoring"], {"kind", "model", "prompt_version"}, "authoring")
    if request["authoring"]["kind"] not in {"AI_DRAFT", "HUMAN_DRAFT", "DETERMINISTIC"} or not request["authoring"]["prompt_version"]:
        raise TrialError("draft authorship required")
    evidence = Evidence(request["sources"], input_root, as_of)
    artifact, lines, review_ids = getattr(renderers, request["workflow"])(request["payload"], evidence, as_of)
    common = {"schema": "ar.workflow-trial-result.v1", "workflow": request["workflow"], "as_of": as_of, "generated_at": request["generated_at"], "mode": request["mode"], "sample_purpose": "WORKFLOW_DEBUG", "claim_allowed": False, "authority": dict(AUTHORITY), "input_hash": sha(canonical(request)), "authoring": request["authoring"], "human_review": "PENDING"}
    artifact.update(common)
    banner = [f"截止日：{as_of}；生成：{request['generated_at']}；{request['mode']} / WORKFLOW_DEBUG。", "历史/合成试用，不是今日资讯、正式研究封存或批准。原文内容可能有误，哈希只证明引用字节未变。", "人工核验：PENDING；AI 不签署，不替代人工判断。"]
    origins = [f"- {text(name)}：{text(source['origin'])}；披露/源日期 {source['published_on']}；实际取得时间 {text(source['observed_at'])}；SHA256 {source['sha256']}。" for name, source in sorted(request["sources"].items())]
    report = "\n\n".join([lines[0], *banner, *lines[1:], "## 来源登记", *origins, "取得时间未知的资料不得用于证明当时已经知悉；本轮只做历史回放。", "## 人工核验", "逐条核对公司、期间、单位、原文定位与解释是否相符。另存核验记录，绑定本报告及 artifact 的 SHA256；不得修改已封存报告。", "不是买卖指令；研究信号，human executes。", ""])
    review = {"schema": "ar.workflow-trial-review-template.v1", "sample_purpose": "WORKFLOW_DEBUG", "status": "PENDING", "reviewer": None, "reviewed_at": None, "identity_status": "NOT_AUTHENTICATED", "report_sha256": sha(report.encode()), "artifact_sha256": sha(canonical(artifact)), "authority": dict(AUTHORITY), "items": [{"id": item, "status": "PENDING", "source_checked": None, "comment": None} for item in review_ids], "instructions": "Save a separate human review record; this template grants no authority. Signing verifies this exact artifact only, not SMC PASS or paper approval."}
    files = {"report.md": report.encode(), "artifact.json": canonical(artifact), "human-review-template.json": canonical(review), "source-manifest.json": canonical(request["sources"])}
    review_lines = ["# 人工核验记录（待本人填写）", "状态：PENDING。未有人类签署；本表不授予任何权限。", f"报告 SHA256：{review['report_sha256']}", f"机器工件 SHA256：{review['artifact_sha256']}", "核验人：未填写；时间（含时区）：未填写。", "另存填写后的记录；不要覆盖这份封存模板。"]
    for item in review_ids:
        review_lines += [f"## {text(item)}", "- 原文、公司、日期、单位：待核验", "- 同意 / 修改 / 缺证据：待填写", "- 判断依据与缺口：待填写"]
    review_lines += ["签署只表示核验本版本，不保证盈利，不等于选股、SMC PASS 或 paper 批准。", "不是买卖指令；研究信号，human executes。", ""]
    files["human-review.md"] = "\n\n".join(review_lines).encode()
    if request["workflow"] == "smc":
        for sample in artifact["samples"]:
            files[f"samples/{sample['id']}.json"] = canonical(sample)
    else:
        for name, source in request["sources"].items():
            files["evidence/" + source["path"]] = evidence.raw[name]
    receipt = {**common, "execution_status": "COMPLETED", "data_status": artifact["data_status"], "human_review": "PENDING", "network_calls": 0, "model_calls": 0, "outputs": {name: sha(raw) for name, raw in sorted(files.items())}}
    files["receipt.json"] = canonical(receipt)
    files["SHA256SUMS"] = "".join(f"{sha(raw)}  {name}\n" for name, raw in sorted(files.items())).encode()
    return {"artifact": artifact, "report": report, "review": review, "receipt": receipt, "files": files}


def write_trial(request, input_root, output):
    result = build(request, input_root)
    output = Path(output).absolute()
    root = Path(input_root).resolve()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(root):
        raise TrialError("output must be new and outside inputs")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".workflow-trial-", dir=output.parent))
    try:
        for name, raw in result["files"].items():
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        # mkdir is the exclusive reservation; a racing or pre-existing target is never overwritten.
        output.mkdir()
        for child in temporary.iterdir():
            shutil.move(str(child), str(output / child.name))
    finally:
        shutil.rmtree(temporary)
    return result["receipt"]


def verify_trial(request, input_root, output):
    expected = build(request, input_root)["files"]
    output = Path(output)
    inventory = list(output.rglob("*")) if not output.is_symlink() else []
    if output.is_symlink() or any(p.is_symlink() for p in inventory):
        raise TrialError("output symlink refused")
    if any(not p.is_file() and not p.is_dir() for p in inventory):
        raise TrialError("unexpected special output")
    actual = {str(p.relative_to(output)): p for p in inventory if p.is_file()}
    if set(actual) != set(expected):
        raise TrialError("output file set changed")
    for name, raw in expected.items():
        if actual[name].is_symlink() or actual[name].read_bytes() != raw:
            raise TrialError(f"output bytes changed: {name}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_bytes())
        result = verify_trial(request, args.inputs, args.output) if args.verify else write_trial(request, args.inputs, args.output)
        print(json.dumps({"sample_purpose": "WORKFLOW_DEBUG", "result": result}, ensure_ascii=False))
        return 0
    except (TrialError, ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
