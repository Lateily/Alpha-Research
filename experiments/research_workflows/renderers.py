"""Three independent draft workflows. No inference is promoted to human approval."""
import math

from .evidence import TrialError, canonical, date8, exact, identifier, substantive, text, timestamp, unique
from . import smc_annotation

SMC_PARAMETERS = ("market", "timeframe", "pivot_left", "pivot_right", "sweep_tolerance", "reclaim_window", "range_anchor", "invalidation", "cooldown", "cost_model")


def brief(payload, evidence, as_of):
    exact(payload, {"focus_version", "coverage_note", "comparison", "items"}, "brief")
    exact(payload["comparison"], {"before_date", "after_date"}, "comparison")
    before_date = payload["comparison"]["before_date"]
    after_date = date8(payload["comparison"]["after_date"])
    if after_date > as_of or (before_date is not None and date8(before_date) >= after_date):
        raise TrialError("invalid comparison dates")
    identifier(payload["focus_version"])
    unique(payload["items"], "id")
    if not payload["coverage_note"]:
        raise TrialError("brief coverage note required")
    report = ["# 每日变化简报", f"机器核对的比较日期：{before_date} → {after_date}", f"关注版本：{text(payload['focus_version'])}", f"覆盖边界：{text(payload['coverage_note'])}"]
    rows = []
    for item in payload["items"]:
        exact(item, {"id", "company", "title", "before", "after", "thesis_link", "draft_comment"}, "brief item")
        after = evidence.observation(item["after"], item["company"], after_date)
        before = evidence.observation(item["before"], item["company"], before_date) if item["before"] is not None else None
        if before and before["published_on"] > after["published_on"]:
            raise TrialError("reversed comparison dates")
        change = "NO_BASELINE" if before is None else ("UNCHANGED" if before["value"] == after["value"] else "CHANGED")
        if not substantive(after["value"]) or (before is not None and not substantive(before["value"])):
            change = "DATA_BLOCKED"
        rows.append({"id": item["id"], "company": item["company"], "change": change, "before": before, "after": after, "draft_comment": item["draft_comment"], "thesis_link": item["thesis_link"]})
        report += [f"## {text(item['company'])} · {text(item['title'])}", f"机械差异：{change}（不是投资判断，也不是涨跌归因）。", "此前：", evidence.display(before) if before else "没有可比基线，不宣称新增事件。", "本次：", evidence.display(after), f"关联命题（草稿）：{text(item['thesis_link'])}", f"解读草稿，未核验：{text(item['draft_comment'])}"]
    return {"comparison": payload["comparison"], "rows": rows, "data_status": "PARTIAL" if any(r["change"] in {"NO_BASELINE", "DATA_BLOCKED"} for r in rows) else "COVERED_DECLARED_ITEMS_ONLY"}, report, [r["id"] for r in rows]


def earnings(payload, evidence, as_of):
    exact(payload, {"company", "claims", "registered_at", "responses"}, "earnings")
    company = payload["company"]
    claims_ref = evidence.cite(payload["claims"], company)
    claims = claims_ref["value"]
    claim_ids = unique(claims, "id")
    responses = payload["responses"]
    response_ids = unique(responses, "claim_id")
    if set(response_ids) != set(claim_ids):
        raise TrialError("claim coverage must be exact")
    by_id = {row["id"]: row for row in claims}
    registered = timestamp(payload["registered_at"]) if payload["registered_at"] is not None else None
    if registered and registered.strftime("%Y%m%d") > as_of:
        raise TrialError("registration after cutoff")
    status = "NOT_PREREGISTERED" if registered is None else "REGISTRATION_ASSERTION_UNVERIFIED"
    rows, report = [], ["# 财报逐条回应 Thesis", f"对象：{text(company)}", f"旧命题清单：{text(claims_ref['source'])} / {text(claims_ref['locator'])}；文件 hash {claims_ref['sha256']}。原稿仅用于逐条回应，未升格为正式研究。"]
    for response in responses:
        claim = by_id[response["claim_id"]]
        if not isinstance(claim.get("question"), str) or not claim["question"].strip():
            raise TrialError("claim question required")
        exact(response, {"claim_id", "evidence", "draft_assessment", "draft_comment", "missing_evidence"}, "response")
        refs = [evidence.cite(ref, company) for ref in response["evidence"]]
        assessment = response["draft_assessment"]
        evidence_complete = bool(refs) and all(substantive(ref["value"]) for ref in refs)
        if assessment not in {"SUPPORTS", "CHALLENGES", "MIXED", "UNRESOLVED"}:
            raise TrialError("invalid assessment")
        if not evidence_complete and (assessment != "UNRESOLVED" or not response["missing_evidence"]):
            raise TrialError("unsupported assessment")
        if registered and any(registered.strftime("%Y%m%d") >= ref["published_on"] for ref in refs):
            status = "AFTER_DISCLOSURE_NOT_PROSPECTIVE"
        criteria = {key: claim.get(key) for key in ("metric", "operator", "threshold", "unit", "measurement", "due_at", "wrong_if")}
        row = {**response, "question": claim["question"], "original_criteria": criteria, "citations": refs, "evidence_status": "CITED_NOT_HUMAN_VERIFIED" if evidence_complete else "DATA_BLOCKED"}
        rows.append(row)
        report += [f"## {text(claim['id'])} · {text(claim['question'])}", f"回应草稿：{assessment}；待人判断，不计命中。", *[evidence.display(ref) for ref in refs], f"理由草稿：{text(response['draft_comment'])}", f"缺少证据：{text(response['missing_evidence'])}"]
        report += ["原命题阈值与证伪条件（逐字来自旧稿，缺失不补造）：", *[f"- {key}: {text(value) if value is not None else 'MISSING / 未登记'}" for key, value in criteria.items()]]
    report.insert(2, f"预登记状态：{status}。源日期和哈希不是审批凭据；本试用不计算预测正确率。")
    return {"registration_status": status, "rows": rows, "data_status": "PARTIAL" if any(r["evidence_status"] == "DATA_BLOCKED" for r in rows) else "CITED_NOT_HUMAN_VERIFIED"}, report, claim_ids


def smc(payload, evidence, as_of):
    exact(payload, {"rule_version", "setup", "parameters", "samples"}, "SMC preparation")
    identifier(payload["rule_version"])
    if payload["setup"] not in {"SWEEP_RECLAIM", "BOS_RETEST", "CHOCH_RECLAIM", "NONE"}:
        raise TrialError("invalid SMC vocabulary")
    exact(payload["parameters"], SMC_PARAMETERS, "SMC parameters")
    if payload["rule_version"] != smc_annotation.VERSION or payload["setup"] != "SWEEP_RECLAIM" or canonical(payload["parameters"]) != canonical(smc_annotation.PARAMETERS):
        raise TrialError("frozen annotation convention required; not strategy parameters")
    sample_ids = unique(payload["samples"], "id")
    if len(payload["samples"]) != 1:
        raise TrialError("one window per delivery; never co-deliver future windows")
    missing = [key for key in SMC_PARAMETERS if payload["parameters"][key] is None]
    samples = []
    report = ["# SMC 单窗口标注准备", f"标注规约：{text(payload['rule_version'])}；{payload['setup']}", "标注规约固定，不等于策略批准；没有自动识别、择时 PASS、入场价格或 paper 权限。", "## 仅供标注的固定参数", *[f"- {key}: {text(payload['parameters'][key])}" for key in SMC_PARAMETERS], "详见本包 annotation-rules.md。只有本包内没有未来 bar；不声称抹掉标注者已知走势。禁止连同父目录或同公司其它窗口发放。"]
    for sample in payload["samples"]:
        exact(sample, {"id", "company", "bars", "window_start", "cutoff", "price_basis", "calendar_audited", "corporate_actions_audited", "cluster_id", "split", "exposure_status"}, "SMC sample")
        if sample["exposure_status"] not in {"PREVIOUSLY_VIEWED", "NOT_KNOWN_VIEWED"}:
            raise TrialError("sample exposure declaration required")
        start, cutoff = date8(sample["window_start"]), date8(sample["cutoff"])
        if not start <= cutoff <= as_of:
            raise TrialError("SMC window outside cutoff")
        if sample["split"] != "DEVELOPMENT" or sample["price_basis"] not in {"raw", "adjusted"}:
            raise TrialError("pilot samples must be development with a price basis")
        if sample["price_basis"] != "raw":
            raise TrialError("annotation codebook requires raw price basis")
        if not sample["cluster_id"] or type(sample["calendar_audited"]) is not bool or type(sample["corporate_actions_audited"]) is not bool:
            raise TrialError("SMC provenance flags required")
        ref = evidence.cite(sample["bars"], sample["company"])
        source_document = evidence.loaded[sample["bars"]["source"]]
        warning = source_document.get("human_warning", "UNKNOWN_NOT_CLEARED")
        if warning is not None and (not isinstance(warning, str) or not warning.strip()):
            raise TrialError("invalid source human warning")
        bars = ref["value"]
        if not isinstance(bars, list) or not bars:
            raise TrialError("SMC bars required")
        previous = ""
        window = []
        for bar in bars:
            day = date8(bar["trade_date"])
            if bar["ts_code"] != sample["company"]:
                raise TrialError("bar company mismatch")
            if day <= previous:
                raise TrialError("bars duplicated or unsorted")
            previous = day
            prices = [bar[k] for k in ("open", "high", "low", "close")]
            if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in prices):
                raise TrialError("invalid OHLC values")
            if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
                raise TrialError("invalid OHLC range")
            volume = bar.get("volume_shares")
            if volume is not None and (type(volume) not in (int, float) or not math.isfinite(volume) or volume < 0):
                raise TrialError("invalid volume")
            if start <= day <= cutoff:
                window.append({k: bar.get(k) for k in ("trade_date", "ts_code", "open", "high", "low", "close", "volume_shares")})
        if not window or cutoff not in {bar["trade_date"] for bar in window}:
            raise TrialError("window has no cutoff bar")
        result = {key: value for key, value in sample.items() if key != "bars"}
        result.update({"human_warning": warning, "annotation_rule_hash": smc_annotation.rule_hash(), "annotation_scope": "RETIRED_EXPOSED_DEMONSTRATION" if sample["exposure_status"] == "PREVIOUSLY_VIEWED" else "ANNOTATION_ONLY", "clean_agreement_eligible": False})
        result.update({"bars": window, "source_sha256": ref["sha256"], "source_pointer": ref["locator"], "human_label": None, "human_reason": None, "sample_purpose": "WORKFLOW_DEBUG", "sample_eligible": False, "quality": "DATA_BLOCKED" if not sample["calendar_audited"] or not sample["corporate_actions_audited"] or any(b["volume_shares"] is None for b in window) else "UNVALIDATED"})
        samples.append(result)
        report += [f"人工警示（来自同一冻结来源，未解除）：{text(warning)}", f"曝光状态：{sample['exposure_status']}；{result['annotation_scope']}。"]
        report += [f"## {text(sample['id'])} · {text(sample['company'])}", f"窗口 {start} 至 {cutoff}；{len(window)} 根；{result['quality']}；人工标签：PENDING。", "日期 | 开 | 高 | 低 | 收 | 成交股数", "--- | --- | --- | --- | --- | ---", *[" | ".join(text(bar[k]) for k in ("trade_date", "open", "high", "low", "close", "volume_shares")) for bar in window], f"核验源 hash：{ref['sha256']}；窗口已封存于 samples/{sample['id']}.json。"]
    return {"method_status": "UNAPPROVED", "annotation_protocol": "FIXED_NOT_STRATEGY_PARAMETERS", "missing_parameters": missing, "rule_version": payload["rule_version"], "rule_hash": smc_annotation.rule_hash(), "parameters": payload["parameters"], "samples": samples, "data_status": "DATA_BLOCKED" if any(s["quality"] == "DATA_BLOCKED" for s in samples) else "UNVALIDATED"}, report, sample_ids
