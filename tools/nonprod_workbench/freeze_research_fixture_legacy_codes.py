"""Developer-only: re-run freeze_research_fixture.py with the pre-#380 code format.

The committed ``fixtures/research_method_v1_1.json`` was frozen before #380
renamed the funnel test registry codes from ``000001.SZ`` to ``T000001.SZ``.
Running the plain freezer now would rewrite every code in the fixture, so a
fixture re-freeze would carry an unrelated diff.  This wrapper loads
``tests/test_research_funnel_closure.py`` with the two #380 code-format lines
reverted in memory (the file on disk is not modified) and then runs the repo
freezer unchanged, so a re-freeze diff contains only the behaviour change under
review.  At eae0b80 it reproduces the committed fixture byte-for-byte.

Usage (offline, from the repository root):

    PYTHONDONTWRITEBYTECODE=1 AR_OFFLINE=1 python3 -B \
        tools/nonprod_workbench/freeze_research_fixture_legacy_codes.py

It prints the fixture sha256; FIXTURE_SHA256 in scripts/llm/workbench_research.py
must then be re-pinned by review.  It never reads a production tree.
"""

import runpy
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY_CODE_FORMAT = (
    ('code = f"T{index:06d}.SZ"', 'code = f"{index:06d}.SZ"'),
    ('last = f"T{30:06d}.SZ"', 'last = f"{30:06d}.SZ"'),
)


def main() -> None:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / "tests"))
    source_path = ROOT / "tests/test_research_funnel_closure.py"
    source = source_path.read_text(encoding="utf-8")
    for new, old in LEGACY_CODE_FORMAT:
        if source.count(new) != 1:
            raise SystemExit(f"expected exactly one {new!r} in {source_path}")
        source = source.replace(new, old)
    module = types.ModuleType("test_research_funnel_closure")
    module.__file__ = str(source_path)
    sys.modules["test_research_funnel_closure"] = module
    exec(compile(source, str(source_path), "exec"), module.__dict__)
    freezer = ROOT / "tools/nonprod_workbench/freeze_research_fixture.py"
    sys.argv = [str(freezer)]
    runpy.run_path(str(freezer), run_name="__main__")


if __name__ == "__main__":
    main()
