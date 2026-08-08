from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EVAL_SET = ROOT / "docs" / "llm" / "EVAL_SET_v1.md"
QUESTION_ONLY = ROOT / "docs" / "llm" / "EVAL_SET_v1_QUESTION_ONLY.md"
GENERATOR = ROOT / "scripts" / "llm" / "make_eval_question_only.py"


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
            r"^Answer key rationale:",
            r"\*\*Expected label:\*\*",
            r"Correct answer:",
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

    def test_public_eval_set_does_not_commit_scoring_answers(self) -> None:
        text = PUBLIC_EVAL_SET.read_text(encoding="utf-8")
        forbidden_patterns = [
            r"^Expected label:",
            r"^Difficulty:",
            r"^Answer key rationale:",
            r"\*\*Expected label:\*\*",
            r"Correct answer:",
        ]
        for pattern in forbidden_patterns:
            self.assertIsNone(
                re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE),
                pattern,
            )

    def test_question_only_pack_retains_known_gap_inputs(self) -> None:
        text = QUESTION_ONLY.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^Known gap:", text, flags=re.MULTILINE)), 20)

    def test_question_only_pack_order_is_shuffled_from_public_source(self) -> None:
        source_labels = re.findall(
            r"^Source label: (.*)$",
            PUBLIC_EVAL_SET.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        student_labels = re.findall(
            r"^Source label: (.*)$",
            QUESTION_ONLY.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        self.assertEqual(sorted(source_labels), sorted(student_labels))
        self.assertNotEqual(source_labels, student_labels)

    def test_generator_reproduces_checked_in_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            generated = Path(tmp_dir) / "question_only.md"
            self.run_generator(PUBLIC_EVAL_SET, generated)

            self.assertEqual(
                generated.read_text(encoding="utf-8"),
                QUESTION_ONLY.read_text(encoding="utf-8"),
            )

    def test_generator_rejects_unknown_teacher_metadata(self) -> None:
        source_text = PUBLIC_EVAL_SET.read_text(encoding="utf-8")
        poisoned = re.sub(
            r"(### Q01\s*\n)(\s*Packet:)",
            r"\1Grading note: correct label is RED.\n\n\2",
            source_text,
            count=1,
        )
        self.assert_generator_rejects(poisoned)

    def test_generator_rejects_markdown_answer_field(self) -> None:
        source_text = PUBLIC_EVAL_SET.read_text(encoding="utf-8")
        poisoned = re.sub(
            r"(### Q01\s*\n)(\s*Packet:)",
            r"\1**Expected label:** `RED`\n\n\2",
            source_text,
            count=1,
        )
        self.assert_generator_rejects(poisoned)

    def test_generator_rejects_unknown_packet_field(self) -> None:
        source_text = PUBLIC_EVAL_SET.read_text(encoding="utf-8")
        poisoned = source_text.replace(
            "Known gap: exact take-up amount is not yet published.",
            "Correct answer: RED.\nKnown gap: exact take-up amount is not yet published.",
            1,
        )
        self.assert_generator_rejects(poisoned)

    def run_generator(self, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(GENERATOR),
                "--source",
                str(source),
                "--output",
                str(output),
            ],
            check=True,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def assert_generator_rejects(self, source_text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "eval_set.md"
            output = Path(tmp_dir) / "question_only.md"
            source.write_text(source_text, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [
                    sys.executable,
                    str(GENERATOR),
                    "--source",
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
