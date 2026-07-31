#!/usr/bin/env python3
"""DEPRECATED compatibility shell — real fetcher moved to fetch_issuer_guidance.py.

SEMANTIC CORRECTION (PR-A A3, 2026-07-31): Tushare forecast/express are
公司业绩预告/快报 (issuer self-disclosure), NOT broker consensus. This shell
exists for exactly one deprecation cycle so any straggler invocation
(cron, docs, muscle memory) still produces correct, correctly-labeled data
in BOTH public/data/issuer_guidance/ and the deprecated
public/data/consensus_forecast/ (each file carries deprecated:true +
moved_to:"issuer_guidance/"). Delete this file once no consumer references
consensus_forecast/.

不是买卖指令;研究信号,human executes.
"""

import sys

from fetch_issuer_guidance import main

if __name__ == "__main__":
    print("WARNING: fetch_consensus_forecast.py is DEPRECATED — "
          "use scripts/fetch_issuer_guidance.py (issuer guidance ≠ broker consensus)",
          file=sys.stderr)
    sys.exit(main())
