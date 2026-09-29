from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "docs/research/DAILY_RESEARCH_BRIEF_CONTENT_RULES_V0.md"
REVIEW = ROOT / "docs/research/review/FIRST_ISOLATED_DAILY_BRIEF_REVIEW_20260923.md"
EARNINGS = ROOT / "docs/research/EARNINGS_UNRESOLVED_THESIS_QUESTIONS_V0.md"
CI = ROOT / ".github/workflows/python-ci.yml"


class DailyResearchBriefDocsTest(unittest.TestCase):
    def test_content_rules_freeze_epistemic_labels_and_authority(self):
        text = RULES.read_text(encoding="utf-8")
        for token in (
            "FACT",
            "ASSOCIATION",
            "INFERENCE",
            "DATA_BLOCKED",
            "POSITION_IMPACT_CONFIRMED",
            "POSITION_IMPACT_NOT_ESTABLISHED",
            "不直接修改工程输入合同",
            "AI 草稿不得标成人工通过",
        ):
            self.assertIn(token, text)

    def test_rules_bind_jason_fields_and_better_layout(self):
        text = RULES.read_text(encoding="utf-8")
        for token in (
            "给 Jason 的字段需求",
            "run_id",
            "target_trade_date",
            "source_sha256",
            "portfolio_value_delta",
            "给 Better 的可读版式样稿",
            "最新尝试",
            "最后成功发布",
        ):
            self.assertIn(token, text)

    def test_first_review_record_waits_for_frozen_artifact(self):
        text = REVIEW.read_text(encoding="utf-8")
        self.assertIn("WAITING_FOR_FROZEN_BRIEF", text)
        self.assertIn("未收到首份冻结隔离简报", text)
        for token in ("通过", "证据不足", "退回", "reviewer: Reed"):
            self.assertIn(token, text)
        self.assertNotIn("overall_verdict: PASS", text)

    def test_earnings_questions_preserve_registered_thesis(self):
        text = EARNINGS.read_text(encoding="utf-8")
        for token in (
            "claim_id",
            "registered_thesis_hash",
            "CONFIRMED",
            "WEAKENED",
            "INVALIDATED",
            "NOT_ADDRESSED",
            "DATA_BLOCKED",
            "不回写原 thesis",
            "AI 草稿不能签成人工研究结论",
        ):
            self.assertIn(token, text)

    def test_ci_runs_daily_research_brief_contract(self):
        workflow = CI.read_text(encoding="utf-8")
        self.assertIn("python3 tests/test_daily_research_brief_docs.py", workflow)


if __name__ == "__main__":
    unittest.main()
