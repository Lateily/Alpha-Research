"""Export an AI Progress Board snapshot for UI or handoff use."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import progress_watch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export the same read-only snapshot served by progress_watch.py."
    )
    parser.add_argument(
        "--source",
        default="scripts/llm/progress_board.example.json",
        help="Local JSON event/comment file. Used when --repo/--comments-url is absent.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository owner/name, for example Lateily/Alpha-Research.",
    )
    parser.add_argument(
        "--issue",
        default=progress_watch.DEFAULT_ISSUE,
        help="GitHub issue number used with --repo.",
    )
    parser.add_argument(
        "--comments-url",
        default=None,
        help="Explicit GitHub issue comments API URL.",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable containing an optional GitHub token.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional file path to write the snapshot JSON.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of pretty-printed JSON.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if the snapshot source cannot be loaded.",
    )
    args = parser.parse_args()

    source = progress_watch.build_source(args)
    snapshot = progress_watch.build_snapshot(source)
    content = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":") if args.compact else None,
        indent=None if args.compact else 2,
    )

    if args.output:
        Path(args.output).write_text(content + "\n", encoding="utf-8")
    else:
        print(content)

    if args.fail_on_error and not snapshot.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
