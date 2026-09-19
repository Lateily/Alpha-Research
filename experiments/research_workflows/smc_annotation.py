"""Fixed annotation convention, not a strategy or a market-label generator."""
from .evidence import TrialError, canonical, exact, sha, timestamp

VERSION = "SMC-ANNOTATION-ONLY-1"
PARAMETERS = {
    "market": "CN_A_0.01_CNY_TICK",
    "timeframe": "DAILY_CLOSED_RAW",
    "pivot_left": 2,
    "pivot_right": 2,
    "sweep_tolerance": {"price_tick": "0.01", "minimum_ticks_below": 1},
    "reclaim_window": 3,
    "range_anchor": "MOST_RECENT_STRICT_CONFIRMED_LOW_BEFORE_SWEEP",
    "invalidation": "FIRST_POST_RECLAIM_CLOSE_BELOW_SWEEP_LOW",
    "cooldown": "FIRST_EVENT_ONLY_PER_WINDOW",
    "cost_model": "NOT_APPLICABLE_ANNOTATION_NOT_EXECUTION",
}
FIELDS = ("label", "reference_date", "reference_confirmed_at", "sweep_date", "reclaim_date", "invalidation_date", "reason")
LABELS = ("SWEEP_RECLAIM", "NONE", "WAIT", "DATA_BLOCKED", "AMBIGUOUS")
RULES = """# 临时标注规约 v1（不是策略参数）

用途：只统一人工标注语言；没有方法批准、入场位或盈利主张。
这些工程约定未按旧 9 个市场窗口的标签、收益或一致率选优。
改任何约定必须升版本，不能覆盖旧规则或混算一致率。

1. 仅 A 股 0.01 元最小报价、未复权日线已收盘 bar。缺日历、公司行动核验、
   量或足够上下文，标 DATA_BLOCKED；不能自行补假设。疑似停牌/除权也先阻断。
2. 参考低点 i 的 low 必须严格低于左 2 根和右 2 根的 low；等低点不是 pivot。
   确认时间为第 i+2 根收盘。窗口外的历史未知，禁止猜测。
3. 按时间正序找第一个 sweep。对每根 t，只取 t-1 收盘前已确认的最近一个 pivot；
   若从该 pivot 确认后到 t-1 已经穿过其 low，该 pivot 不再可用，不退选更旧点。
   low(t) <= pivot.low - 0.01 才是 sweep。记录参考日期、确认日期和 sweep 日期。
4. 从 t 当根至其后第 3 根（共最多 4 根）中，第一个 close >= pivot.low 是 reclaim。
   窗口结束前未收回且 3 根等待期未满：WAIT；等待期已满：NONE（理由写超时）。
   根本没有合格 sweep：NONE。只标首个事件，不搜索后来更漂亮的形态。
5. 已收回：SWEEP_RECLAIM；随后首个 close < sweep.low 的日期记 invalidation_date。
   后续失效不抹掉曾发生的形态。不得看窗口后的 bar。OHLC 无法解释的情况标 AMBIGUOUS。
6. 每人每公司本轮只领一个窗口。不要发送父目录、完整行情或同公司后续窗口。
   本地文件隔离不能抹掉记忆：看过走势须声明，不能再作盲法或干净一致性样本。
   已曝光的旧 9 窗口只作演示；新样本须在本规则冻结之后另行冻结和登记发放。

人工填 label、reference_date、reference_confirmed_at、sweep_date、reclaim_date、
invalidation_date、reason。同时记录身份、时间、是否已见未来及来源核验；允许 NONE/WAIT。
逐字段一致数/可比字段数只是标注一致性，不是策略胜率；DATA_BLOCKED/AMBIGUOUS 另列。
"""


def rule_hash():
    return sha(canonical({"version": VERSION, "parameters": PARAMETERS, "rules": RULES}))


def annotation_item(sample):
    return {"id": sample["id"], "status": "PENDING", "source_checked": None, "comment": None,
            "sample_sha256": sha(canonical(sample)), "rule_hash": rule_hash(),
            "human_warning": sample["human_warning"], "exposure_status": sample["exposure_status"],
            "future_seen": None, **{key: None for key in FIELDS}}


def compare_annotations(sample, left, right):
    """Compare human records only; typed identities are not authentication."""
    keys = {"reviewer", "reviewed_at", "sample_sha256", "rule_hash", "future_seen", *FIELDS}
    if sample["annotation_rule_hash"] != rule_hash() or sample["price_basis"] != "raw":
        raise TrialError("sample rule or price basis mismatch")
    days = [bar["trade_date"] for bar in sample["bars"]]
    for record in (left, right):
        exact(record, keys, "SMC annotation")
        if not isinstance(record["reviewer"], str) or not record["reviewer"].strip():
            raise TrialError("annotation reviewer required")
        timestamp(record["reviewed_at"])
        if record["sample_sha256"] != sha(canonical(sample)) or record["rule_hash"] != rule_hash():
            raise TrialError("annotation binding mismatch")
        if record["label"] not in LABELS or not isinstance(record["reason"], str) or not record["reason"].strip() or type(record["future_seen"]) is not bool:
            raise TrialError("annotation label/reason/exposure required")
        dates = [record[key] for key in FIELDS[1:-1]]
        if any(day is not None and day not in days for day in dates):
            raise TrialError("annotation date outside sample")
        if [d for d in dates if d is not None] != sorted(d for d in dates if d is not None):
            raise TrialError("annotation chronology invalid")
        if record["label"] == "SWEEP_RECLAIM" and any(record[k] is None for k in FIELDS[1:5]):
            raise TrialError("confirmed annotation requires event dates")
        ref, confirmed, sweep, reclaim, invalid = [days.index(day) if day is not None else None for day in dates]
        if (ref is not None or confirmed is not None) and (ref is None or confirmed is None or ref < PARAMETERS["pivot_left"] or confirmed != ref + PARAMETERS["pivot_right"]):
            raise TrialError("pivot confirmation requires left context and two closed right bars")
        if sweep is not None and (confirmed is None or sweep <= confirmed):
            raise TrialError("sweep must follow pivot confirmation")
        if reclaim is not None and (sweep is None or not sweep <= reclaim <= sweep + PARAMETERS["reclaim_window"]):
            raise TrialError("reclaim outside fixed window")
        if invalid is not None and (reclaim is None or invalid <= reclaim):
            raise TrialError("invalidation must follow reclaim")
    if left["reviewer"] == right["reviewer"]:
        raise TrialError("two distinct self-reported reviewers required")
    agreement = {key: left[key] == right[key] for key in FIELDS[:-1] if left[key] is not None or right[key] is not None}
    eligible = sample["exposure_status"] == "NOT_KNOWN_VIEWED" and not left["future_seen"] and not right["future_seen"] and sample["quality"] != "DATA_BLOCKED" and all(r["label"] not in {"DATA_BLOCKED", "AMBIGUOUS"} for r in (left, right))
    return {"sample_purpose": "WORKFLOW_DEBUG", "claim_allowed": False, "identity_status": "SELF_REPORTED_NOT_AUTHENTICATED", "agreement": agreement, "matching_fields": sum(agreement.values()), "compared_fields": len(agreement), "clean_agreement_eligible": eligible}
