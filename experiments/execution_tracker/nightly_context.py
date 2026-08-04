#!/usr/bin/env python3
"""Immutable context shared by every engine in one nightly run."""
from __future__ import annotations

import datetime
import os
import re


def target_trade_date(default_today=True):
    value = str(os.environ.get("AR_TARGET_TRADE_DATE") or "").strip()
    if not value and default_today:
        value = datetime.date.today().strftime("%Y%m%d")
    if value and not re.fullmatch(r"\d{8}", value):
        raise ValueError(f"AR_TARGET_TRADE_DATE 非 YYYYMMDD: {value!r}")
    if value:
        datetime.datetime.strptime(value, "%Y%m%d")
    return value or None


def run_id():
    return str(os.environ.get("AR_RUN_ID") or "STANDALONE")


def generated_at():
    target = target_trade_date()
    return f"{target} {datetime.datetime.now().strftime('%H:%M:%S')}"


def bind(obj, *, target=None, run=None):
    """Attach the shared context to a top-level output object."""
    if not isinstance(obj, dict):
        raise TypeError("nightly output must be a dict")
    target = str(target or target_trade_date())[:8]
    datetime.datetime.strptime(target, "%Y%m%d")
    obj["run_id"] = str(run or run_id())
    obj["target_trade_date"] = target
    return obj
