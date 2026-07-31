"""Serve a local read-only AI Progress Board live view."""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import progress_conflicts


DEFAULT_REPO = "Lateily/Alpha-Research"
DEFAULT_ISSUE = "164"
DEFAULT_INTERVAL_SECONDS = 30


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a local read-only live view for AI Progress Board events."
    )
    parser.add_argument(
        "--source",
        default="scripts/llm/progress_board.example.json",
        help="Local JSON event/comment file. Used when --repo/--comments-url is absent.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help=f"GitHub repository owner/name, for example {DEFAULT_REPO}.",
    )
    parser.add_argument(
        "--issue",
        default=DEFAULT_ISSUE,
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
    parser.add_argument("--host", default="127.0.0.1", help="Local server host.")
    parser.add_argument("--port", type=int, default=8765, help="Local server port.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Browser refresh interval.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one board snapshot as JSON instead of starting the server.",
    )
    args = parser.parse_args()

    source = build_source(args)
    if args.once:
        print(json.dumps(build_snapshot(source), ensure_ascii=False, indent=2))
        return 0

    serve(args, source)
    return 0


def build_source(args: argparse.Namespace) -> dict[str, str]:
    if args.comments_url:
        return {"kind": "url", "value": args.comments_url, "token_env": args.token_env}
    if args.repo:
        return {
            "kind": "github",
            "repo": args.repo,
            "issue": args.issue,
            "token_env": args.token_env,
        }
    return {"kind": "file", "value": args.source, "token_env": args.token_env}


def serve(args: argparse.Namespace, source: dict[str, str]) -> None:
    handler = make_handler(source, max(args.interval_seconds, 5))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"AI Progress Board live view: {url}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def make_handler(
    source: dict[str, str], interval_seconds: int
) -> type[BaseHTTPRequestHandler]:
    class ProgressHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path in {"/", "/index.html"}:
                self.send_text(render_page(interval_seconds), "text/html; charset=utf-8")
                return
            if self.path == "/events":
                snapshot = build_snapshot(source)
                self.send_text(
                    json.dumps(snapshot, ensure_ascii=False),
                    "application/json; charset=utf-8",
                )
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def send_text(self, content: str, content_type: str) -> None:
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ProgressHandler


def build_snapshot(source: dict[str, str]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    try:
        events = load_source_events(source)
        conflicts = progress_conflicts.find_conflicts(events, now)
        active = progress_conflicts.active_claims(events, now)
        return {
            "ok": True,
            "source": redacted_source(source),
            "refreshed_at_utc": now.isoformat(),
            "summary": summarize(events, active, conflicts),
            "active_claims": sorted(active, key=lambda item: item.get("expires_at", "")),
            "conflicts": serialize_conflicts(conflicts),
            "timeline": sorted(events, key=lambda item: item.get("timestamp_utc", "")),
        }
    except (OSError, ValueError, HTTPError, URLError) as exc:
        return {
            "ok": False,
            "source": redacted_source(source),
            "refreshed_at_utc": now.isoformat(),
            "error": str(exc),
            "summary": {},
            "active_claims": [],
            "conflicts": [],
            "timeline": [],
        }


def load_source_events(source: dict[str, str]) -> list[dict[str, Any]]:
    if source["kind"] == "file":
        return progress_conflicts.load_events(Path(source["value"]))
    if source["kind"] == "github":
        return load_github_issue_events(source)

    request = Request(source["value"], headers=github_headers(source))
    with urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8"))

    if isinstance(raw, list):
        return progress_conflicts.events_from_comments(raw)
    if isinstance(raw, dict) and isinstance(raw.get("comments"), list):
        return progress_conflicts.events_from_comments(raw["comments"])
    raise ValueError("GitHub response did not contain issue comments.")


def load_github_issue_events(source: dict[str, str]) -> list[dict[str, Any]]:
    token = os.environ.get(source["token_env"], "")
    if token:
        url = (
            f"https://api.github.com/repos/{source['repo']}/issues/"
            f"{source['issue']}/comments?per_page=100"
        )
        request = Request(url, headers=github_headers(source))
        with urlopen(request, timeout=15) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return progress_conflicts.events_from_comments(raw)

    endpoint = f"repos/{source['repo']}/issues/{source['issue']}/comments?per_page=100"
    completed = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        check=False,
        encoding="utf-8",
        timeout=20,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ValueError(f"gh api failed: {detail}")
    raw = json.loads(completed.stdout)
    return progress_conflicts.events_from_comments(raw)


def github_headers(source: dict[str, str]) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "alpha-research-progress-watch",
    }
    token = os.environ.get(source["token_env"], "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def summarize(
    events: list[dict[str, Any]],
    active: list[dict[str, Any]],
    conflicts: list[tuple[dict[str, Any], dict[str, Any], list[str]]],
) -> dict[str, int]:
    return {
        "events": len(events),
        "active_claims": len(active),
        "done": count_events(events, "DONE"),
        "blocked": count_events(events, "BLOCKED"),
        "released": count_events(events, "RELEASE"),
        "conflicts": len(conflicts),
    }


def count_events(events: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for event in events if event.get("event") == event_type)


def serialize_conflicts(
    conflicts: list[tuple[dict[str, Any], dict[str, Any], list[str]]]
) -> list[dict[str, Any]]:
    serialized = []
    for left, right, files in conflicts:
        serialized.append(
            {
                "left": progress_conflicts.actor(left),
                "right": progress_conflicts.actor(right),
                "left_task": left.get("task"),
                "right_task": right.get("task"),
                "files": files,
            }
        )
    return serialized


def redacted_source(source: dict[str, str]) -> dict[str, str]:
    if source["kind"] == "github":
        return {
            "kind": source["kind"],
            "value": f"{source['repo']}#${source['issue']}".replace("#$", "#"),
        }
    return {"kind": source["kind"], "value": source["value"]}


def render_page(interval_seconds: int) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Progress Board Live</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #65717f;
      --line: #d9dee7;
      --blue: #2563eb;
      --green: #1f8a5b;
      --red: #c2410c;
      --amber: #a16207;
      --violet: #6d28d9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.96);
    }}
    h1 {{
      margin: 0;
      font-size: 20px;
      font-weight: 700;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      text-align: right;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
      gap: 14px;
      padding: 14px;
      height: calc(100vh - 62px);
    }}
    section {{
      min-height: 0;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      overflow: hidden;
    }}
    .section-title {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
      font-weight: 700;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      padding: 12px;
    }}
    .stat {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
    }}
    .stat strong {{
      display: block;
      font-size: 24px;
      line-height: 1.1;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .list {{
      display: grid;
      gap: 10px;
      padding: 12px;
      overflow: auto;
      max-height: calc(100vh - 260px);
    }}
    .timeline {{
      height: calc(100vh - 116px);
      overflow: auto;
      padding: 12px;
    }}
    .event {{
      border: 1px solid var(--line);
      border-left-width: 5px;
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 10px;
      background: #fff;
    }}
    .CLAIM {{ border-left-color: var(--blue); }}
    .UPDATE {{ border-left-color: var(--violet); }}
    .DONE {{ border-left-color: var(--green); }}
    .BLOCKED {{ border-left-color: var(--red); }}
    .RELEASE {{ border-left-color: var(--amber); }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 74px;
      padding: 3px 8px;
      border-radius: 999px;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
    }}
    .badge.CLAIM {{ background: var(--blue); }}
    .badge.UPDATE {{ background: var(--violet); }}
    .badge.DONE {{ background: var(--green); }}
    .badge.BLOCKED {{ background: var(--red); }}
    .badge.RELEASE {{ background: var(--amber); }}
    .summary {{
      margin: 8px 0;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }}
    .small {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }}
    .empty, .error {{
      padding: 14px;
      color: var(--muted);
    }}
    .error {{ color: var(--red); }}
    @media (max-width: 760px) {{
      main {{
        grid-template-columns: 1fr;
        height: auto;
      }}
      .timeline, .list {{
        max-height: none;
        height: auto;
      }}
      header {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .meta {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>AI Progress Board Live</h1>
    <div class="meta">
      <div id="source"></div>
      <div id="refreshed"></div>
    </div>
  </header>
  <main>
    <section>
      <div class="section-title">Status</div>
      <div id="stats" class="stats"></div>
      <div class="section-title">Active Claims</div>
      <div id="claims" class="list"></div>
      <div class="section-title">Conflicts</div>
      <div id="conflicts" class="list"></div>
    </section>
    <section>
      <div class="section-title">Timeline</div>
      <div id="timeline" class="timeline"></div>
    </section>
  </main>
  <script>
    const intervalMs = {interval_seconds * 1000};

    function text(value) {{
      return value === undefined || value === null || value === "" ? "-" : String(value);
    }}

    function escapeHtml(value) {{
      return text(value).replace(/[&<>"']/g, char => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\\"": "&quot;",
        "'": "&#39;"
      }}[char]));
    }}

    function renderEvent(event) {{
      const eventType = escapeHtml(event.event);
      const files = Array.isArray(event.files) ? event.files.join(", ") : "";
      return `
        <div class="event ${{eventType}}">
          <div class="row">
            <span class="badge ${{eventType}}">${{eventType}}</span>
            <span class="small">${{escapeHtml(event.timestamp_utc)}}</span>
          </div>
          <div class="summary">${{escapeHtml(event.summary)}}</div>
          <div class="small">
            task=${{escapeHtml(event.task)}} · owner=${{escapeHtml(event.human_owner)}} ·
            executor=${{escapeHtml(event.executor)}} · reviewer=${{escapeHtml(event.reviewer)}}
          </div>
          <div class="small">
            branch=${{escapeHtml(event.branch)}} · files=${{escapeHtml(files)}} ·
            risk=${{escapeHtml(event.risk)}} · cost=¥${{escapeHtml(event.cost_cny || "0")}}
          </div>
        </div>`;
    }}

    function renderStats(summary) {{
      const items = [
        ["Events", summary.events || 0],
        ["Active", summary.active_claims || 0],
        ["Done", summary.done || 0],
        ["Blocked", summary.blocked || 0],
        ["Released", summary.released || 0],
        ["Conflicts", summary.conflicts || 0]
      ];
      return items.map(([label, value]) => `
        <div class="stat"><strong>${{value}}</strong><span>${{label}}</span></div>
      `).join("");
    }}

    function renderConflicts(conflicts) {{
      if (!conflicts.length) return `<div class="empty">No active conflicts.</div>`;
      return conflicts.map(item => `
        <div class="event BLOCKED">
          <div class="summary">${{escapeHtml(item.left)}} overlaps ${{escapeHtml(item.right)}}</div>
          <div class="small">tasks=${{escapeHtml(item.left_task)}} / ${{escapeHtml(item.right_task)}}</div>
          <div class="small">files=${{escapeHtml((item.files || []).join(", "))}}</div>
        </div>
      `).join("");
    }}

    async function refresh() {{
      const response = await fetch("/events", {{ cache: "no-store" }});
      const data = await response.json();
      document.getElementById("source").textContent =
        `${{data.source.kind}}: ${{data.source.value}}`;
      document.getElementById("refreshed").textContent =
        `refreshed: ${{data.refreshed_at_utc}}`;

      if (!data.ok) {{
        document.getElementById("stats").innerHTML = "";
        document.getElementById("claims").innerHTML = "";
        document.getElementById("conflicts").innerHTML = "";
        document.getElementById("timeline").innerHTML =
          `<div class="error">${{escapeHtml(data.error)}}</div>`;
        return;
      }}

      document.getElementById("stats").innerHTML = renderStats(data.summary);
      document.getElementById("claims").innerHTML =
        data.active_claims.length ? data.active_claims.map(renderEvent).join("") :
        `<div class="empty">No active claims.</div>`;
      document.getElementById("conflicts").innerHTML = renderConflicts(data.conflicts);
      const timeline = document.getElementById("timeline");
      timeline.innerHTML = data.timeline.map(renderEvent).join("");
      timeline.scrollTop = timeline.scrollHeight;
    }}

    refresh();
    setInterval(refresh, intervalMs);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
