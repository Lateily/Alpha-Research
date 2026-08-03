from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "llm" / "k1_shadow_eval.py"
QUESTION_ONLY = ROOT / "docs" / "llm" / "EVAL_SET_v1_QUESTION_ONLY.md"


class K1ShadowEvalOfflineTest(unittest.TestCase):
    def test_prepare_creates_three_leak_free_model_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "prepare",
                    "--question-pack",
                    str(QUESTION_ONLY),
                    "--run-dir",
                    str(run_dir),
                    "--seed",
                    "7",
                ],
                check=True,
                cwd=ROOT,
            )

            for arm in ("kimi", "claude", "codex"):
                text = (run_dir / "model_inputs" / f"{arm}.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("---- QUESTION PACK START ----", text)
                self.assertIn("### Q20", text)
                self.assertNotIn("Expected label", text)
                self.assertNotIn("Answer key rationale", text)
                self.assertEqual(
                    len(re.findall(r"^Known gap:", text, flags=re.MULTILINE)),
                    20,
                )

            mapping = json.loads(
                (run_dir / "private" / "unblind_map.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(mapping["schema"], "k1-shadow-unblind.v1")
            self.assertEqual(
                sorted(mapping["answer_to_arm"].keys()),
                ["Answer A", "Answer B", "Answer C"],
            )

    def test_build_blind_hides_model_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "prepare",
                    "--question-pack",
                    str(QUESTION_ONLY),
                    "--run-dir",
                    str(run_dir),
                    "--seed",
                    "11",
                ],
                check=True,
                cwd=ROOT,
            )

            for arm in ("kimi", "claude", "codex"):
                (run_dir / "model_outputs" / f"{arm}.md").write_text(
                    f"Result from anonymous worker for {arm.upper()} hidden in map.\n".replace(
                        arm.upper(), "ARM"
                    ),
                    encoding="utf-8",
                )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "build-blind",
                    "--run-dir",
                    str(run_dir),
                    "--seed",
                    "11",
                ],
                check=True,
                cwd=ROOT,
            )
            subprocess.run(
                [sys.executable, str(SCRIPT), "validate", "--run-dir", str(run_dir)],
                check=True,
                cwd=ROOT,
            )

            packet = (run_dir / "blind" / "K1_BLIND_REVIEW_PACKET.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("## Answer A", packet)
            self.assertIn("## Answer B", packet)
            self.assertIn("## Answer C", packet)
            self.assertNotIn("kimi", packet.lower())
            self.assertNotIn("claude", packet.lower())
            self.assertNotIn("codex", packet.lower())


if __name__ == "__main__":
    unittest.main()
