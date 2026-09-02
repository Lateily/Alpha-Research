#!/usr/bin/env python3
"""Offline behavior regression for the canonical LHB appearances contract."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_API = ROOT / "api" / "research.js"
LHB_FIXTURE = ROOT / "public" / "data" / "lhb" / "300308.SZ.json"
LHB_HEADER = "TUSHARE — 龙虎榜 LHB APPEARANCES"

SDK_LOADER = r"""
const source = 'export default class Anthropic { constructor() { this.messages = {}; } }';

export async function resolve(specifier, context, nextResolve) {
  if (specifier === '@anthropic-ai/sdk') {
    return {
      url: `data:text/javascript,${encodeURIComponent(source)}`,
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
"""

NODE_RUNNER = r"""
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

globalThis.fetch = () => {
  throw new Error('network is forbidden in the LHB render regression');
};

const [researchPath, fixturePath] = process.argv.slice(2);
const { buildExtrasBlock } = await import(pathToFileURL(researchPath).href);
const lhb = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const render = payload => buildExtrasBlock({ tushare_suite: { lhb: payload } });
const appearances = [...lhb.appearances];
for (let index = 2; index <= 6; index += 1) {
  appearances.push({
    trade_date: `202607${String(27 - index).padStart(2, '0')}`,
    reason: `LIMIT-${index}`,
    net_amount: index * 100000000,
  });
}

process.stdout.write(JSON.stringify({
  fixtureCount: lhb.appearances.length,
  positive: render(lhb),
  limited: render({ ...lhb, appearances }),
  empty: render({ ...lhb, appearances: [] }),
  missing: render({ _status: 'ok' }),
  legacyOnly: render({ _status: 'ok', records: lhb.appearances }),
}));
"""


def _render_cases() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="ar-lhb-render-") as tmp:
        temp_root = Path(tmp)
        loader = temp_root / "anthropic-loader.mjs"
        runner = temp_root / "runner.mjs"
        loader.write_text(SDK_LOADER, encoding="utf-8")
        runner.write_text(NODE_RUNNER, encoding="utf-8")
        env = {
            key: value
            for key, value in os.environ.items()
            if not any(part in key.upper() for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        }
        env.update({"ANTHROPIC_API_KEY": "offline-test", "AR_OFFLINE": "1"})
        completed = subprocess.run(
            [
                "node",
                "--no-warnings",
                "--experimental-loader",
                str(loader),
                str(runner),
                str(RESEARCH_API),
                str(LHB_FIXTURE),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_lhb_render_reads_appearances() -> None:
    rendered = _render_cases()
    positive = str(rendered["positive"])
    assert rendered["fixtureCount"] == 1
    assert LHB_HEADER in positive
    assert "20260728" in positive
    assert "日跌幅达到15%的前5只证券" in positive
    assert "net +28.39亿" in positive

    limited = str(rendered["limited"])
    assert "LIMIT-5" in limited
    assert "LIMIT-6" not in limited

    for case in ("empty", "missing", "legacyOnly"):
        assert LHB_HEADER not in str(rendered[case]), case


if __name__ == "__main__":
    test_lhb_render_reads_appearances()
    print("PASS LHB fixture: appearances=1 date/reason/net rendered")
    print("PASS LHB limit: first 5 rendered, sixth omitted")
    print("PASS LHB negatives: empty/missing/legacy records omitted without error")
