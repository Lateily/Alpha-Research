"""tushare_rows.py — one row reader for the rotation/discovery scripts.

The rotation scripts (rotation_validation, rotation_panel, momentum_prefilter,
court_wakeup) each carried a private `_api` that swallowed every exception and
every non-zero provider code and returned ``[]``.  An empty list then looked
exactly like a real "no rows" answer, and `rotation_validation --append`
stored a failed ``limit_list_d`` call as a zero-limit-up day (23 of 90 days in
the 2026-09 production window).

This reader keeps the two outcomes apart:

    (rows, None)     provider answered code 0; ``rows`` may legitimately be []
    (None, reason)   the call failed; ``reason`` is a short machine string

It never retries into a fallback host, never invents rows and never echoes the
token.  Under ``AR_OFFLINE`` it refuses before opening a socket.

不是买卖指令；研究信号，human executes。
"""
import json
import os
import time
import urllib.request

TUSHARE_URL = "https://api.tushare.pro"


def _scrub(text, token):
    text = str(text or "")
    if token:
        text = text.replace(token, "***")
    return text[:120]


def fetch_rows(name, token, *, timeout=30, attempts=4, pause=1.5,
               opener=None, sleep=time.sleep, **params):
    """Return ``(rows, None)`` on a code-0 answer or ``(None, reason)`` on failure."""
    if os.environ.get("AR_OFFLINE"):
        return None, "TUSHARE_OFFLINE"
    if not isinstance(token, str) or not token.strip():
        return None, "TUSHARE_TOKEN_MISSING"
    opener = opener or urllib.request.urlopen
    body = json.dumps({"api_name": name, "token": token,
                       "params": params, "fields": ""}).encode()
    reason = "TUSHARE_NO_ATTEMPT"
    for attempt in range(max(1, int(attempts))):
        try:
            req = urllib.request.Request(TUSHARE_URL, body,
                                         {"Content-Type": "application/json"})
            payload = json.load(opener(req, timeout=timeout))
            if not isinstance(payload, dict):
                reason = "TUSHARE_PAYLOAD_SHAPE"
            elif payload.get("code") == 0:
                data = payload.get("data")
                fields = data.get("fields") if isinstance(data, dict) else None
                items = data.get("items") if isinstance(data, dict) else None
                if (not isinstance(fields, list) or not isinstance(items, list)
                        or any(not isinstance(row, list) or len(row) != len(fields)
                               for row in items)):
                    reason = "TUSHARE_DATA_SHAPE"
                else:
                    return [dict(zip(fields, row)) for row in items], None
            else:
                reason = (f"TUSHARE_CODE_{payload.get('code')}:"
                          f"{_scrub(payload.get('msg'), token)}")
        except Exception as exc:                        # noqa: BLE001
            # Upstream exception text may echo the request payload (token).
            reason = f"TUSHARE_EXCEPTION:{type(exc).__name__}"
        if attempt + 1 < max(1, int(attempts)):
            sleep(pause)
    return None, reason


def optional_float(value):
    """Provider numeric cell -> float, or None when missing / non-finite.

    Replaces the ``float(r.get(x) or 0)`` idiom that turned a missing value
    into a real zero reading.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out
