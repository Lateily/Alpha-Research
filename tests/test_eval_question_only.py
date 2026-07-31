from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUESTION_ONLY = ROOT / "docs" / "llm" / "EVAL_SET_v1_QUESTION_ONLY.md"


class EvalQuestionOnlyTest(unittest.TestCase):
    def test_question_only_pack_has_20_questions(self) -> None:
        text = QUESTION_ONLY.read_text(encoding="utf-8")
        questions = re.findall(r"^### Q\d{2}\s*$", text, flags=re.MULTILINE)
        self.assertEqual(len(questions), 20)

    def test_question_only_pack_does_not_leak_teacher_fields(self) -> None:
        text = QUESTION_ONLY.read_text(encoding="utf-8")
        forbidden_patterns = [
            r"answer key",
            r"^Expected label:",
            r"^Difficulty:",
            r"^Known gap:",
            r"^Answer key rationale:",
            r"hidden labels",
            r"teacher file",
        ]
        for pattern in forbidden_patterns:
            self.assertIsNone(
                re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE),
                pattern,
            )

    def test_question_only_pack_has_no_score_sheet_or_unblind_template(self) -> None:
        text = QUESTION_ONLY.read_text(encoding="utf-8").lower()
        self.assertNotIn("blind score sheet", text)
        self.assertNotIn("answer a = tbd", text)
        self.assertNotIn("winner:", text)


if __name__ == "__main__":
    unittest.main()
