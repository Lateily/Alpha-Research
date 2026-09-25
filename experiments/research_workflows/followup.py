#!/usr/bin/env python3
"""Local-only follow-up snapshots. No collector, scheduler or approval endpoint."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from research_workflows import trial
    from research_workflows.evidence import Evidence, TrialError, canonical, date8, exact, sha, text, timestamp
else:
    from . import trial
    from .evidence import Evidence, TrialError, canonical, date8, exact, sha, text, timestamp

FAILED = {"SOURCE_FAILED", "DATA_BLOCKED"}
AUTHORITY = dict(trial.AUTHORITY)


def _plain_path(value):
    path = Path(os.path.abspath(value))
    if any(p.is_symlink() for p in (path, *path.parents)):
        # Permit the OS /var alias, but not a mutable link in the supplied tree.
        links = [p for p in (path, *path.parents) if p.is_symlink()]
        if any(str(p) not in {"/var", "/tmp"} for p in links):
            raise TrialError("symlink refused")
    return path


def _destination(output, protected):
    output = _plain_path(output)
    if output.exists() or any(output.resolve().is_relative_to(Path(root).resolve()) for root in protected):
        raise TrialError("output must be new and outside inputs/previous package")
    return output


def _inventory(root):
    root = _plain_path(root)
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise TrialError("package symlink or special file refused")
        if path.is_file() and path != root / "SHA256SUMS":
            result[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    return result


def _seal_inventory(root):
    raw = "".join(f"{digest}  {name}\n" for name, digest in sorted(_inventory(root).items()))
    (Path(root) / "SHA256SUMS").write_text(raw, encoding="utf-8")


def _check_request(request, checked_at, previous):
    exact(request, {"schema", "workflow", "as_of", "generated_at", "mode", "sources", "authoring", "payload"}, "request")
    if request["schema"] != "ar.workflow-trial.v1" or request["mode"] not in {"HISTORICAL_REPLAY", "SYNTHETIC"}:
        raise TrialError("only offline replay modes allowed")
    date8(request["as_of"])
    if request.get("workflow") not in {"brief", "earnings"}:
        raise TrialError("only brief and earnings follow-up allowed")
    now = timestamp(checked_at)
    if now < timestamp(request["generated_at"]):
        raise TrialError("check time precedes generation")
    if previous:
        if previous["mode"] != request["mode"] or request["as_of"] < previous["as_of"]:
            raise TrialError("mode cannot change and cutoff cannot regress")
        if previous["workflow"] != request["workflow"]:
            raise TrialError("workflow cannot change within follow-up history")
        if previous["subjects"] != _subjects(request):
            raise TrialError("subject cannot change within follow-up history")
        if now < timestamp(previous["checked_at"]):
            raise TrialError("check time precedes previous attempt")
    for source in request.get("sources", {}).values():
        observed = source.get("observed_at")
        if observed is not None and timestamp(observed) > now:
            raise TrialError("source observation is in the future")


def _subjects(request):
    if request["workflow"] == "earnings":
        return [request["payload"]["company"]]
    return sorted({row["company"] for row in request["payload"]["items"]})


def _last_success(previous):
    if not previous:
        return None
    if previous["status"] in FAILED:
        return previous["last_success"]
    keys = ("workflow", "checked_at", "as_of", "source_versions", "question_version", "draft_version", "report_sha256")
    return {**{key: previous[key] for key in keys}, "receipt_sha256": sha(canonical(previous))}


def _questions(result):
    artifact = result["artifact"]
    if artifact["workflow"] == "earnings":
        return [{"id": row["claim_id"], "question": row["question"], **row["original_criteria"]} for row in artifact["rows"]]
    return []


def _derive(request, result, checked_at, previous, failure):
    last = _last_success(previous)
    questions = _questions(result) if result else []
    question_version = sha(canonical(questions)) if result else None
    draft_version = sha(canonical({"payload": request["payload"], "authoring": request["authoring"]}))
    versions = {name: {k: v for k, v in source.items() if k not in {"path", "observed_at"}}
                for name, source in request["sources"].items()}
    old = last["source_versions"] if last else {}
    changed = sorted(name for name in set(old) | set(versions) if old.get(name) != versions.get(name))
    if failure:
        status, reason = failure
    else:
        reason = None
        if not last:
            status = "INITIAL_SNAPSHOT"
        elif question_version != last["question_version"]:
            status = "QUESTION_CHANGED_REVIEW_REQUIRED"
        elif changed:
            status = "NEW_EVIDENCE_REVIEW_REQUIRED"
        elif draft_version != last["draft_version"]:
            status = "DRAFT_CHANGED_REVIEW_REQUIRED"
        else:
            status = "NO_NEW_EVIDENCE"
    return {"schema": "ar.workflow-followup.v1", "workflow": request["workflow"],
            "mode": request["mode"], "as_of": request["as_of"], "subjects": _subjects(request), "checked_at": checked_at,
            "input_hash": sha(canonical(request)), "status": status, "failure_reason": reason,
            "previous": None if previous is None else {"receipt_sha256": sha(canonical(previous)),
                "status": previous["status"], "checked_at": previous["checked_at"]},
            "last_success": last, "source_versions": versions if result else {},
            "question_version": question_version, "draft_version": draft_version,
            "changed_sources": changed if result else [],
            "report_sha256": sha(result["files"]["report.md"]) if result else None,
            "data_status": result["receipt"]["data_status"] if result else "DATA_BLOCKED",
            "human_review": "PENDING", "authority": dict(AUTHORITY), "claim_allowed": False,
            "sample_purpose": "WORKFLOW_DEBUG", "network_calls": 0, "model_calls": 0,
            "scheduler_enabled": False}


def _status_report(receipt, questions):
    labels = {"INITIAL_SNAPSHOT": "初次冻结，待核验", "NO_NEW_EVIDENCE": "输入证据没有变化",
              "NEW_EVIDENCE_REVIEW_REQUIRED": "输入证据有变化，需要重新回应",
              "QUESTION_CHANGED_REVIEW_REQUIRED": "研究问题或判据已变更，必须单独审核",
              "DRAFT_CHANGED_REVIEW_REQUIRED": "只有草稿变化，不是新增证据",
              "SOURCE_FAILED": "本次读取失败，没有生成报告", "DATA_BLOCKED": "本次输入被拒，没有生成报告"}
    lines = ["# 简报 / 财报持续跟踪", f"状态：{labels[receipt['status']]} (`{receipt['status']}`)",
             f"本次资料完整度：{receipt['data_status']}；完成检查不代表证据齐全。",
             f"检查时间：{text(receipt['checked_at'])}；资料截止：{receipt['as_of']}；{receipt['mode']} / WORKFLOW_DEBUG。",
             "这是本地文件检查，不是已扫描全部公告或新闻；没有新输入不能证明市场没有新消息。",
             "人工核验：PENDING；不计预测命中，不授予研究或交易批准。"]
    if receipt["failure_reason"]:
        lines += [f"失败原因：{text(receipt['failure_reason'])}", "历史成功版本只供追溯，未作为本次结果。"]
    else:
        lines += ["[查看本次报告](report/report.md)", "[查看待填写核验表](report/human-review.md)",
                  f"变更来源：{text(receipt['changed_sources'])}", f"命题版本：{receipt['question_version']}"]
    if receipt["last_success"]:
        lines += [f"上次成功资料截止：{receipt['last_success']['as_of']}；回执 SHA256：{receipt['last_success']['receipt_sha256']}"]
    for question in questions:
        missing = [key for key, value in question.items() if value is None or value == ""]
        lines += [f"## {text(question['id'])} · {text(question['question'])}",
                  f"待补字段：{text(missing)}；机器不代填、不改考题。"]
    return "\n\n".join([*lines, "不是买卖指令；研究信号，human executes。", ""]).encode()


def capture(request, inputs, output, checked_at, previous=None):
    """Read only supplied inputs. Freeze successes; retain visible failed attempts."""
    prior = verify(previous) if previous is not None else None
    _check_request(request, checked_at, prior)
    output = _destination(output, [inputs] + ([previous] if previous else []))
    # Freeze first, then render those very bytes, avoiding a read/copy time-of-use gap.
    result, failure, source_bytes = None, None, {}
    try:
        _plain_path(inputs)
        source_bytes = Evidence(request["sources"], inputs, request["as_of"]).raw
    except (json.JSONDecodeError, UnicodeError) as exc:
        failure = ("DATA_BLOCKED", type(exc).__name__)
    except OSError as exc:
        failure = ("SOURCE_FAILED", type(exc).__name__)
    except TrialError as exc:
        # A missing local file is an availability failure, not a successful empty check.
        failure = ("SOURCE_FAILED" if str(exc) == "source path missing or aliased" else "DATA_BLOCKED", str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".followup-", dir=output.parent))
    try:
        if failure is None:
            for name, raw in source_bytes.items():
                target = temporary / "inputs" / request["sources"][name]["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            try:
                result = trial.build(request, temporary / "inputs")
            except (TrialError, KeyError, TypeError, ValueError) as exc:
                failure = ("DATA_BLOCKED", str(exc) if isinstance(exc, TrialError) else type(exc).__name__)
            if result:
                for name, raw in result["files"].items():
                    target = temporary / "report" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
        receipt = _derive(request, result, checked_at, prior, failure)
        questions = _questions(result) if result else []
        files = {"request.json": canonical(request), "check.json": canonical(receipt),
                 "previous.json": canonical(prior), "questions.json": canonical(questions),
                 "status.md": _status_report(receipt, questions)}
        for name, raw in files.items():
            (temporary / name).write_bytes(raw)
        _seal_inventory(temporary)
        verify(temporary)
        output.mkdir()  # Exclusive reservation; never replace another run.
        for item in temporary.iterdir():
            shutil.move(str(item), str(output / item.name))
        return receipt
    finally:
        shutil.rmtree(temporary)


def verify(output):
    """Verify local package and replay success from frozen bytes, never its claims."""
    output = _plain_path(output)
    actual = _inventory(output)
    expected = "".join(f"{digest}  {name}\n" for name, digest in sorted(actual.items()))
    if (output / "SHA256SUMS").read_text(encoding="utf-8") != expected:
        raise TrialError("package inventory hash mismatch")
    request = json.loads((output / "request.json").read_bytes())
    receipt = json.loads((output / "check.json").read_bytes())
    prior = json.loads((output / "previous.json").read_bytes())
    _check_request(request, receipt["checked_at"], prior)
    result, failure = None, None
    if receipt["status"] in FAILED:
        if receipt["failure_reason"] is None or (output / "report").exists():
            raise TrialError("failed attempt must not contain a report")
        failure = (receipt["status"], receipt["failure_reason"])
    else:
        result = trial.build(request, output / "inputs")
        trial.verify_trial(request, output / "inputs", output / "report")
    derived = _derive(request, result, receipt["checked_at"], prior, failure)
    if canonical(derived) != canonical(receipt):
        raise TrialError("check receipt differs from reopened inputs")
    questions = _questions(result) if result else []
    if (output / "questions.json").read_bytes() != canonical(questions):
        raise TrialError("question version differs from source")
    if (output / "status.md").read_bytes() != _status_report(receipt, questions):
        raise TrialError("status report differs from check")
    allowed = {"request.json", "check.json", "previous.json", "questions.json", "status.md"}
    if (output / "inputs").exists():
        allowed |= {"inputs/" + source["path"] for source in request["sources"].values()}
    if result:
        allowed |= {"report/" + name for name in result["files"]}
    if set(actual) != allowed:
        raise TrialError("unexpected package file set")
    return receipt


def _nonempty(value):
    if not isinstance(value, str) or not value.strip():
        raise TrialError("non-empty human text required")


def record_review(package, draft, output, supersedes=None):
    receipt = verify(package)
    if receipt["status"] in FAILED:
        raise TrialError("cannot review a failed attempt as a report")
    output = _destination(output, [package])
    exact(draft, {"reviewer", "reviewed_at", "report_sha256", "artifact_sha256", "items", "usefulness", "feedback"}, "human review")
    for key in ("reviewer", "feedback"):
        _nonempty(draft[key])
    if timestamp(draft["reviewed_at"]) < timestamp(receipt["checked_at"]):
        raise TrialError("review precedes check")
    template = json.loads((Path(package) / "report/human-review-template.json").read_bytes())
    if any(draft[key] != template[key] for key in ("report_sha256", "artifact_sha256")):
        raise TrialError("review binding differs from report version")
    wanted = [item["id"] for item in template["items"]]
    if not isinstance(draft["items"], list) or sorted(item.get("id", "") for item in draft["items"]) != sorted(wanted):
        raise TrialError("review item coverage must be exact")
    for item in draft["items"]:
        exact(item, {"id", "status", "source_checked", "comment"}, "review item")
        if item["status"] not in {"PASS", "REVISE", "EVIDENCE_MISSING"} or type(item["source_checked"]) is not bool:
            raise TrialError("invalid review outcome")
        if item["status"] == "PASS" and not item["source_checked"]:
            raise TrialError("PASS requires a source check")
        _nonempty(item["comment"])
    if draft["usefulness"] not in {"USEFUL", "NEEDS_CHANGE", "NOT_USEFUL"}:
        raise TrialError("invalid usefulness outcome")
    old_hash = None
    if supersedes is not None:
        old = json.loads(_plain_path(supersedes).read_bytes())
        unsigned = {key: value for key, value in old.items() if key != "record_hash"}
        if old.get("record_hash") != sha(canonical(unsigned)) or any(old.get(key) != draft[key] for key in ("report_sha256", "artifact_sha256", "reviewer")):
            raise TrialError("correction must bind same report and reviewer")
        if timestamp(draft["reviewed_at"]) < timestamp(old["reviewed_at"]):
            raise TrialError("correction precedes original")
        old_hash = sha(canonical(old))
    record = {**draft, "schema": "ar.workflow-review.v1", "status": "RECORDED_NOT_APPROVAL",
              "identity_status": "SELF_REPORTED_NOT_AUTHENTICATED", "authority": dict(AUTHORITY),
              "claim_allowed": False, "sample_purpose": "WORKFLOW_DEBUG", "supersedes": old_hash}
    record["record_hash"] = sha(canonical(record))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(canonical(record))
        handle.flush()
        os.fsync(handle.fileno())
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    for flag in ("request", "inputs", "output"):
        check.add_argument("--" + flag, type=Path, required=True)
    check.add_argument("--checked-at", required=True)
    check.add_argument("--previous", type=Path)
    reopen = sub.add_parser("verify")
    reopen.add_argument("--package", type=Path, required=True)
    review = sub.add_parser("review")
    for flag in ("package", "draft", "output"):
        review.add_argument("--" + flag, type=Path, required=True)
    review.add_argument("--supersedes", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            result = capture(json.loads(args.request.read_bytes()), args.inputs, args.output, args.checked_at, args.previous)
        elif args.command == "verify":
            result = verify(args.package)
        else:
            result = record_review(args.package, json.loads(args.draft.read_bytes()), args.output, args.supersedes)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result["status"] in FAILED else 0
    except (TrialError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
