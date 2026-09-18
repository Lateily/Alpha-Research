"""Three independent draft workflows. No inference is promoted to human approval."""
import math

from .evidence import TrialError, date8, exact, identifier, substantive, text, timestamp, unique

SMC_PARAMETERS = ("market", "timeframe", "pivot_left", "pivot_right", "sweep_tolerance", "reclaim_window", "range_anchor", "invalidation", "cooldown", "cost_model")


def brief(payload, evidence, as_of):
    exact(payload, {"focus_version", "coverage_note", "items"}, "brief")
    identifier(payload["focus_version"])
    unique(payload["items"], "id")
    if not payload["coverage_note"]:
        raise TrialError("brief coverage note required")
    report = ["# 每日变化简报", f"关注版本：{text(payload['focus_version'])}", f"覆盖边界：{text(payload['coverage_note'])}"]
    rows = []
    for item in payload["items"]:
        exact(item, {"id", "company", "title", "before", "after", "thesis_link", "draft_comment"}, "brief item")
        after = evidence.cite(item["after"], item["company"])
        before = evidence.cite(item["before"], item["company"]) if item["before"] is not None else None
        if before and before["published_on"] > after["published_on"]:
            raise TrialError("reversed comparison dates")
        change = "NO_BASELINE" if before is None else ("UNCHANGED" if before["value"] == after["value"] else "CHANGED")
        if not substantive(after["value"]) or (before is not None and not substantive(before["value"])):
            change = "DATA_BLOCKED"
        rows.append({"id": item["id"], "company": item["company"], "change": change, "before": before, "after": after, "draft_comment": item["draft_comment"], "thesis_link": item["thesis_link"]})
        report += [f"## {text(item['company'])} · {text(item['title'])}", f"机械差异：{change}（不是投资判断，也不是涨跌归因）。", "此前：", evidence.display(before) if before else "没有可比基线，不宣称新增事件。", "本次：", evidence.display(after), f"关联命题（草稿）：{text(item['thesis_link'])}", f"解读草稿，未核验：{text(item['draft_comment'])}"]
    return {"rows": rows, "data_status": "PARTIAL" if any(r["change"] in {"NO_BASELINE", "DATA_BLOCKED"} for r in rows) else "COVERED_DECLARED_ITEMS_ONLY"}, report, [r["id"] for r in rows]


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
        row = {**response, "question": claim["question"], "citations": refs, "evidence_status": "CITED_NOT_HUMAN_VERIFIED" if evidence_complete else "DATA_BLOCKED"}
        rows.append(row)
        report += [f"## {text(claim['id'])} · {text(claim['question'])}", f"回应草稿：{assessment}；待人判断，不计命中。", *[evidence.display(ref) for ref in refs], f"理由草稿：{text(response['draft_comment'])}", f"缺少证据：{text(response['missing_evidence'])}"]
    report.insert(2, f"预登记状态：{status}。源日期和哈希不是审批凭据；本试用不计算预测正确率。")
    return {"registration_status": status, "rows": rows, "data_status": "PARTIAL" if any(r["evidence_status"] == "DATA_BLOCKED" for r in rows) else "CITED_NOT_HUMAN_VERIFIED"}, report, claim_ids


def smc(payload, evidence, as_of):
    exact(payload, {"rule_version", "setup", "parameters", "samples"}, "SMC preparation")
    identifier(payload["rule_version"])
    if payload["setup"] not in {"SWEEP_RECLAIM", "BOS_RETEST", "CHOCH_RECLAIM", "NONE"}:
        raise TrialError("invalid SMC vocabulary")
    exact(payload["parameters"], SMC_PARAMETERS, "SMC parameters")
    sample_ids = unique(payload["samples"], "id")
    missing = [key for key in SMC_PARAMETERS if payload["parameters"][key] is None]
    samples = []
    report = ["# SMC 规则与样本准备", f"规则版本：{text(payload['rule_version'])}；形态提案：{payload['setup']}", "规则尚未批准；没有自动识别、择时 PASS、入场价格或 paper 权限。", "## 必须先冻结的参数", *[f"- {key}: {text(payload['parameters'][key])}" for key in SMC_PARAMETERS], "## 人工标注方法", "逐根已收盘 bar 观察；记录参考点形成时间与确认时间；只在收回发生后记为候选结构。未来走势隐藏，不按后验盈利挑例。缺日历或公司行动核验时仅做图形练习。", "必留反例：穿越未收回、收回超时、只有未收盘确认、缺量、缺日历、除权跳空、重复事件、NONE。参数未冻结时不判这些市场样本通过与否。"]
    for sample in payload["samples"]:
        exact(sample, {"id", "company", "bars", "window_start", "cutoff", "price_basis", "calendar_audited", "corporate_actions_audited", "cluster_id", "split"}, "SMC sample")
        start, cutoff = date8(sample["window_start"]), date8(sample["cutoff"])
        if not start <= cutoff <= as_of:
            raise TrialError("SMC window outside cutoff")
        if sample["split"] != "DEVELOPMENT" or sample["price_basis"] not in {"raw", "adjusted"}:
            raise TrialError("pilot samples must be development with a price basis")
        if not sample["cluster_id"] or type(sample["calendar_audited"]) is not bool or type(sample["corporate_actions_audited"]) is not bool:
            raise TrialError("SMC provenance flags required")
        ref = evidence.cite(sample["bars"], sample["company"])
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
        result.update({"bars": window, "source_sha256": ref["sha256"], "source_pointer": ref["locator"], "human_label": None, "human_reason": None, "sample_purpose": "WORKFLOW_DEBUG", "sample_eligible": False, "quality": "DATA_BLOCKED" if not sample["calendar_audited"] or not sample["corporate_actions_audited"] or any(b["volume_shares"] is None for b in window) else "UNVALIDATED"})
        samples.append(result)
        report += [f"## {text(sample['id'])} · {text(sample['company'])}", f"窗口 {start} 至 {cutoff}；{len(window)} 根；{result['quality']}；人工标签：PENDING。", "日期 | 开 | 高 | 低 | 收 | 成交股数", "--- | --- | --- | --- | --- | ---", *[" | ".join(text(bar[k]) for k in ("trade_date", "open", "high", "low", "close", "volume_shares")) for bar in window], f"核验源 hash：{ref['sha256']}；窗口已封存于 samples/{sample['id']}.json。"]
    return {"method_status": "SPEC_BLOCKED" if missing else "UNAPPROVED", "missing_parameters": missing, "rule_version": payload["rule_version"], "parameters": payload["parameters"], "samples": samples, "data_status": "UNVALIDATED"}, report, sample_ids
