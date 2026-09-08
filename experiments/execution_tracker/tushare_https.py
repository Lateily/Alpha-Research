"""DataFrame reader for nightly consumers over the existing HTTPS transport.

No SDK-private endpoint override, environment URL, fallback host or extra retry
layer. Provider failures remain failures; missing rows remain missing rows.
"""
from functools import partial
import os

import fund_source


READ_APIS = frozenset({
    "daily", "moneyflow_dc", "forecast", "express", "income", "fina_indicator",
    "anns_d", "daily_basic", "index_global",
})


class TushareHTTPS:
    def __init__(self, token):
        if not isinstance(token, str) or not token.strip():
            raise ValueError("TUSHARE_TOKEN_REQUIRED")
        self.__token = token.strip()

    def __getattr__(self, name):
        return partial(self.query, name)

    def query(self, api, fields="", **params):
        if os.environ.get("AR_OFFLINE"):
            raise RuntimeError("TUSHARE_OFFLINE")
        if fund_source.TUSHARE_URL != "https://api.tushare.pro":
            raise RuntimeError("TUSHARE_HTTPS_ENDPOINT_REQUIRED")
        if api not in READ_APIS:
            raise ValueError("TUSHARE_READ_API_NOT_ALLOWED")
        if not isinstance(fields, str):
            raise ValueError("TUSHARE_FIELDS_MUST_BE_STRING")
        try:
            data = fund_source._tushare_call(api, self.__token, params, fields)
        except Exception as exc:
            # Upstream errors may echo the credential-bearing request payload.
            raise RuntimeError("TUSHARE_READ_FAILED:" + type(exc).__name__) from None
        if not isinstance(data, dict):
            raise ValueError("TUSHARE_DATA_SHAPE")
        columns, rows = data.get("fields"), data.get("items")
        if (not isinstance(columns, list) or any(not isinstance(c, str) or not c for c in columns)
                or len(set(columns)) != len(columns)):
            raise ValueError("TUSHARE_FIELD_SHAPE")
        if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
            raise ValueError("TUSHARE_ROW_SHAPE")
        import pandas as pd
        return pd.DataFrame(rows, columns=columns)
