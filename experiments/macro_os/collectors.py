#!/usr/bin/env python3
"""Macro OS M0-B source collectors, provenance binding, and health export.

Supported adapters:
  * BLS Public Data API (official E1): labor and inflation series
  * BEA Public API (official E1): GDP and core-PCE tables
  * Cboe official VIX history download (official E1)
  * FRED/ALFRED (E2 mirror): Treasury, real-yield, and credit series
  * U.S. Census Economic Indicators (official E1): retail sales

Collection writes raw bytes and observations into the append-only SQLite store.
The output remains CALIBRATING and has no direct blocking or trading authority.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.macro_os import contracts
from experiments.macro_os.storage import (
    DEFAULT_DB,
    MacroHistoryStore,
    MacroStoreError,
    Observation,
    source_identity_hash,
)


COLLECTOR_VERSION = "macro-m0b/1.0"
DEFAULT_HEALTH = Path("public/data/v2/macro/source_health.json")
DISCLAIMER = "不是买卖指令;研究信号,human executes."
FAILURE_STATUSES = {"DATA_BLOCKED", "SOURCE_DOWN", "DATA_INVALID"}
SECRET_QUERY_KEYS = {"api_key", "key", "userid", "registrationkey"}
REDACTION_MARKER = b"[REDACTED_SECRET]"


class CollectionError(RuntimeError):
    def __init__(self, status: str, code: str, safe_message: str):
        if status not in FAILURE_STATUSES:
            raise ValueError(f"invalid collection failure status: {status}")
        super().__init__(safe_message)
        self.status = status
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True)
class MetricSpec:
    series_id: str
    metric_key: str
    native_series_id: str
    unit: str
    cadence: str
    max_observation_age_seconds: int
    max_fetch_age_seconds: int


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    public_locator: str
    headers: dict[str, str]
    body: bytes | None
    allowed_hosts: tuple[str, ...]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    final_url: str
    headers: dict[str, str]
    body: bytes


Parser = Callable[[bytes, str, "RequestSpec"], list[Observation]]
Builder = Callable[[datetime, dict[str, str]], HttpRequest]


@dataclass(frozen=True)
class RequestSpec:
    request_id: str
    source_id: str
    metrics: tuple[MetricSpec, ...]
    build_request: Builder
    parser: Parser

    @property
    def requested_series(self) -> list[str]:
        return sorted({metric.series_id for metric in self.metrics})


class Transport(Protocol):
    def fetch(self, request: HttpRequest) -> HttpResponse:
        ...


def _iso_now(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise CollectionError("DATA_INVALID", "NAIVE_CLOCK", "collector clock lacks timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise CollectionError(
                "DATA_INVALID", "DUPLICATE_JSON_KEY", f"official response repeats JSON key {key}"
            )
        out[key] = value
    return out


def _json_payload(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_guard)
    except UnicodeDecodeError as exc:
        raise CollectionError("DATA_INVALID", "INVALID_UTF8", "response is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CollectionError("DATA_INVALID", "INVALID_JSON", "response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise CollectionError("DATA_INVALID", "INVALID_SHAPE", "response root must be an object")
    return value


def _number_text(value: Any) -> tuple[str, float]:
    if value is None:
        raise CollectionError("DATA_INVALID", "MISSING_VALUE", "official value is missing")
    text = str(value).strip().replace(",", "")
    if not text or text in {".", "---", "NA", "N/A"}:
        raise CollectionError("DATA_INVALID", "MISSING_VALUE", "official value is empty")
    try:
        numeric = float(text)
    except ValueError as exc:
        raise CollectionError("DATA_INVALID", "INVALID_NUMBER", "official value is not numeric") from exc
    if not (-1e100 < numeric < 1e100):
        raise CollectionError("DATA_INVALID", "INVALID_NUMBER", "official value is not finite")
    return str(value).strip(), numeric


def _date_iso(year: int, month: int = 1, day: int = 1) -> str:
    return datetime(year, month, day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _period_iso(raw: str) -> str:
    value = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%m/%d/%Y", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            return parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    match = re.fullmatch(r"([0-9]{4})Q([1-4])", value, re.IGNORECASE)
    if match:
        return _date_iso(int(match.group(1)), (int(match.group(2)) - 1) * 3 + 1)
    match = re.fullmatch(r"([0-9]{4})M([0-9]{1,2})", value, re.IGNORECASE)
    if match and 1 <= int(match.group(2)) <= 12:
        return _date_iso(int(match.group(1)), int(match.group(2)))
    raise CollectionError("DATA_INVALID", "INVALID_PERIOD", f"unsupported period {value!r}")


def _sanitize_url(url: str, environment: dict[str, str] | None = None) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = [(key, value) for key, value in query if key.lower() not in SECRET_QUERY_KEYS]
    safe_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe_query), "")
    )
    encoded, _names = _redact_response_body(
        safe_url.encode("utf-8"), environment or {}
    )
    return encoded.decode("utf-8")


def _redact_response_body(
    raw: bytes, environment: dict[str, str]
) -> tuple[bytes, list[str]]:
    redacted = raw
    names: list[str] = []
    source_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(source_payload)
    credential_names = sorted(
        {
            name
            for source in source_payload["sources"]
            for name in source["credential_env_vars"]
        }
    )
    for name in credential_names:
        value = environment.get(name, "").strip()
        if not value:
            continue
        variants = {
            value.encode("utf-8"),
            urllib.parse.quote(value, safe="").encode("utf-8"),
            urllib.parse.quote_plus(value, safe="").encode("utf-8"),
        }
        matched = False
        for variant in sorted(variants, key=len, reverse=True):
            if variant and variant in redacted:
                redacted = redacted.replace(variant, REDACTION_MARKER)
                matched = True
        if matched:
            names.append(name)
    return redacted, names


def _validate_response_origin(request: HttpRequest, response: HttpResponse) -> None:
    final = urllib.parse.urlsplit(response.final_url)
    if final.scheme != "https" or (final.hostname or "").lower() not in request.allowed_hosts:
        raise CollectionError(
            "DATA_INVALID",
            "UNAPPROVED_RESPONSE_ORIGIN",
            "response resolved to a host outside the collector allowlist",
        )


class UrllibTransport:
    def __init__(self, timeout_seconds: int = 30, max_response_bytes: int = 64 * 1024 * 1024):
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def fetch(self, request: HttpRequest) -> HttpResponse:
        if os.environ.get("AR_OFFLINE") == "1":
            raise CollectionError(
                "DATA_BLOCKED", "AR_OFFLINE", "network collection is disabled by AR_OFFLINE"
            )
        req = urllib.request.Request(
            request.url,
            data=request.body,
            headers=request.headers,
            method=request.method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise CollectionError(
                        "DATA_INVALID",
                        "RESPONSE_TOO_LARGE",
                        "source response exceeds the configured byte limit",
                    )
                headers = {key.lower(): value for key, value in response.headers.items()}
                return HttpResponse(
                    status=int(response.status),
                    final_url=str(response.url),
                    headers=headers,
                    body=body,
                )
        except urllib.error.HTTPError as exc:
            raise CollectionError(
                "SOURCE_DOWN", f"HTTP_{exc.code}", f"source returned HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = type(exc.reason).__name__ if getattr(exc, "reason", None) else "URLError"
            raise CollectionError("SOURCE_DOWN", reason, "source connection failed") from exc
        except (TimeoutError, socket.timeout) as exc:
            # governance-mutation: MACRO_M0B_TIMEOUT_TRANSLATION
            raise CollectionError("SOURCE_DOWN", "TIMEOUT", "source request timed out") from exc


def _bls_builder(now: datetime, env: dict[str, str]) -> HttpRequest:
    series_ids = [metric.native_series_id for metric in BLS_METRICS]
    payload: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": str(now.year - 5),
        "endyear": str(now.year),
    }
    key = env.get("BLS_API_KEY", "").strip()
    if key:
        payload["registrationkey"] = key
    return HttpRequest(
        method="POST",
        url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
        public_locator="https://api.bls.gov/publicAPI/v2/timeseries/data/",
        headers={"Content-Type": "application/json", "User-Agent": "Alpha-Research-MacroOS/1"},
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        allowed_hosts=("api.bls.gov",),
    )


def _bls_parser(raw: bytes, fetched_at: str, spec: RequestSpec) -> list[Observation]:
    payload = _json_payload(raw)
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise CollectionError("DATA_INVALID", "BLS_REJECTED", "BLS did not accept the request")
    rows = ((payload.get("Results") or {}).get("series"))
    if not isinstance(rows, list):
        raise CollectionError("DATA_INVALID", "BLS_SHAPE", "BLS response lacks series rows")
    by_native = {metric.native_series_id: metric for metric in spec.metrics}
    observations: list[Observation] = []
    seen_native: set[str] = set()
    for series in rows:
        if not isinstance(series, dict):
            continue
        native = str(series.get("seriesID", ""))
        metric = by_native.get(native)
        if metric is None:
            continue
        seen_native.add(native)
        data = series.get("data")
        if not isinstance(data, list):
            raise CollectionError("DATA_INVALID", "BLS_SHAPE", f"BLS series {native} lacks data")
        for row in data:
            period = str(row.get("period", ""))
            if not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
                continue
            try:
                year = int(row["year"])
            except (KeyError, TypeError, ValueError) as exc:
                raise CollectionError("DATA_INVALID", "BLS_PERIOD", "BLS year is invalid") from exc
            value_text, value = _number_text(row.get("value"))
            observations.append(
                Observation(
                    series_id=metric.series_id,
                    metric_key=metric.metric_key,
                    observation_at=_date_iso(year, int(period[1:])),
                    vintage_at=fetched_at,
                    value_text=value_text,
                    value=value,
                    unit=metric.unit,
                    attributes={
                        "native_series_id": native,
                        "period": period,
                        "period_name": row.get("periodName"),
                        "footnotes": row.get("footnotes") or [],
                    },
                )
            )
    missing = sorted(set(by_native) - seen_native)
    if missing:
        raise CollectionError(
            "DATA_INVALID", "BLS_MISSING_SERIES", f"BLS omitted requested series: {missing}"
        )
    if not observations:
        raise CollectionError("DATA_INVALID", "BLS_EMPTY", "BLS returned no usable observations")
    return observations


def _cboe_builder(_now: datetime, _env: dict[str, str]) -> HttpRequest:
    url = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    return HttpRequest(
        method="GET",
        url=url,
        public_locator=url,
        headers={"Accept": "text/csv", "User-Agent": "Alpha-Research-MacroOS/1"},
        body=None,
        allowed_hosts=("cdn.cboe.com",),
    )


def _cboe_parser(raw: bytes, fetched_at: str, spec: RequestSpec) -> list[Observation]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CollectionError("DATA_INVALID", "CBOE_ENCODING", "Cboe CSV is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CollectionError("DATA_INVALID", "CBOE_HEADER", "Cboe CSV has no header")
    normalized = {field.strip().upper(): field for field in reader.fieldnames}
    if "DATE" not in normalized or "CLOSE" not in normalized:
        raise CollectionError("DATA_INVALID", "CBOE_HEADER", "Cboe CSV lacks DATE/CLOSE")
    metric = spec.metrics[0]
    observations: list[Observation] = []
    for row in reader:
        value_text, value = _number_text(row.get(normalized["CLOSE"]))
        observations.append(
            Observation(
                series_id=metric.series_id,
                metric_key=metric.metric_key,
                observation_at=_period_iso(str(row.get(normalized["DATE"], ""))),
                vintage_at=fetched_at,
                value_text=value_text,
                value=value,
                unit=metric.unit,
                attributes={"native_series_id": metric.native_series_id},
            )
        )
    if not observations:
        raise CollectionError("DATA_INVALID", "CBOE_EMPTY", "Cboe returned no VIX rows")
    return observations


def _fred_builder(metric: MetricSpec) -> Builder:
    def build(now: datetime, env: dict[str, str]) -> HttpRequest:
        key = env.get("FRED_API_KEY", "").strip()
        # governance-mutation: MACRO_M0B_FRED_KEYLESS_ROUTE
        if key:
            query = urllib.parse.urlencode(
                {
                    "series_id": metric.native_series_id,
                    "api_key": key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": "5000",
                }
            )
            public_query = urllib.parse.urlencode(
                {
                    "series_id": metric.native_series_id,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": "5000",
                }
            )
            return HttpRequest(
                method="GET",
                url=f"https://api.stlouisfed.org/fred/series/observations?{query}",
                public_locator=(
                    "https://api.stlouisfed.org/fred/series/observations?" + public_query
                ),
                headers={"Accept": "application/json", "User-Agent": "Alpha-Research-MacroOS/1"},
                body=None,
                allowed_hosts=("api.stlouisfed.org",),
            )

        # The provider's graph CSV is a credential-free current-vintage export.
        # It remains the same E2 FRED source and never masquerades as an official
        # Treasury/BLS/BEA release.  Limit the request to the registry's 10-year
        # market-series horizon instead of downloading an unbounded history.
        start_year = max(1900, now.astimezone(timezone.utc).year - 10)
        query = urllib.parse.urlencode(
            {
                "id": metric.native_series_id,
                "cosd": f"{start_year:04d}-01-01",
                "coed": now.astimezone(timezone.utc).date().isoformat(),
            }
        )
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?" + query
        return HttpRequest(
            method="GET",
            url=url,
            public_locator=url,
            headers={"Accept": "text/csv"},
            body=None,
            allowed_hosts=("fred.stlouisfed.org",),
        )

    return build


def _fred_json_parser(
    raw: bytes, fetched_at: str, spec: RequestSpec
) -> list[Observation]:
    payload = _json_payload(raw)
    if "error_code" in payload:
        raise CollectionError("DATA_INVALID", "FRED_REJECTED", "FRED rejected the request")
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise CollectionError("DATA_INVALID", "FRED_SHAPE", "FRED response lacks observations")
    metric = spec.metrics[0]
    observations: list[Observation] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("value", "")).strip() == ".":
            continue
        value_text, value = _number_text(row.get("value"))
        observations.append(
            Observation(
                series_id=metric.series_id,
                metric_key=metric.metric_key,
                observation_at=_period_iso(str(row.get("date", ""))),
                vintage_at=fetched_at,
                value_text=value_text,
                value=value,
                unit=metric.unit,
                attributes={
                    "native_series_id": metric.native_series_id,
                    "realtime_start": row.get("realtime_start"),
                    "realtime_end": row.get("realtime_end"),
                },
            )
        )
    if not observations:
        raise CollectionError("DATA_INVALID", "FRED_EMPTY", "FRED returned no usable rows")
    return observations


def _fred_csv_parser(
    raw: bytes, fetched_at: str, spec: RequestSpec
) -> list[Observation]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CollectionError(
            "DATA_INVALID", "FRED_CSV_ENCODING", "FRED CSV is not UTF-8"
        ) from exc
    reader = csv.DictReader(io.StringIO(text))
    metric = spec.metrics[0]
    expected_header = ["observation_date", metric.native_series_id]
    # governance-mutation: MACRO_M0B_FRED_CSV_SERIES_BINDING
    if reader.fieldnames != expected_header:
        raise CollectionError(
            "DATA_INVALID",
            "FRED_CSV_HEADER",
            "FRED CSV header differs from the requested series",
        )
    observations: list[Observation] = []
    for row in reader:
        raw_value = str(row.get(metric.native_series_id, "")).strip()
        if not raw_value or raw_value == ".":
            continue
        value_text, value = _number_text(raw_value)
        observations.append(
            Observation(
                series_id=metric.series_id,
                metric_key=metric.metric_key,
                observation_at=_period_iso(str(row.get("observation_date", ""))),
                vintage_at=fetched_at,
                value_text=value_text,
                value=value,
                unit=metric.unit,
                attributes={
                    "native_series_id": metric.native_series_id,
                    "transport_mode": "FRED_GRAPH_CSV_CURRENT_VINTAGE",
                },
            )
        )
    if not observations:
        raise CollectionError(
            "DATA_INVALID", "FRED_CSV_EMPTY", "FRED CSV returned no usable rows"
        )
    return observations


def _fred_parser(raw: bytes, fetched_at: str, spec: RequestSpec) -> list[Observation]:
    if raw.lstrip().startswith(b"{"):
        return _fred_json_parser(raw, fetched_at, spec)
    return _fred_csv_parser(raw, fetched_at, spec)


def _bea_builder(table_name: str, frequency: str) -> Builder:
    def build(now: datetime, env: dict[str, str]) -> HttpRequest:
        key = env.get("BEA_API_KEY", "").strip()
        if not key:
            raise CollectionError(
                "DATA_BLOCKED", "BEA_API_KEY_MISSING", "BEA_API_KEY is not configured"
            )
        params = {
            "UserID": key,
            "method": "GetData",
            "DataSetName": "NIPA",
            "TableName": table_name,
            "Frequency": frequency,
            "Year": f"{now.year - 2},{now.year - 1},{now.year}",
            "ResultFormat": "JSON",
        }
        public_params = {key_: value for key_, value in params.items() if key_ != "UserID"}
        return HttpRequest(
            method="GET",
            url="https://apps.bea.gov/api/data/?" + urllib.parse.urlencode(params),
            public_locator=(
                "https://apps.bea.gov/api/data/?" + urllib.parse.urlencode(public_params)
            ),
            headers={"Accept": "application/json", "User-Agent": "Alpha-Research-MacroOS/1"},
            body=None,
            allowed_hosts=("apps.bea.gov",),
        )

    return build


def _bea_parser(raw: bytes, fetched_at: str, spec: RequestSpec) -> list[Observation]:
    payload = _json_payload(raw)
    api = payload.get("BEAAPI")
    if not isinstance(api, dict):
        raise CollectionError("DATA_INVALID", "BEA_SHAPE", "BEA response lacks BEAAPI")
    results = api.get("Results")
    if not isinstance(results, dict):
        raise CollectionError("DATA_INVALID", "BEA_SHAPE", "BEA response lacks Results")
    if results.get("Error"):
        raise CollectionError("DATA_INVALID", "BEA_REJECTED", "BEA rejected the request")
    rows = results.get("Data")
    if not isinstance(rows, list):
        raise CollectionError("DATA_INVALID", "BEA_SHAPE", "BEA response lacks Data rows")
    metric = spec.metrics[0]
    target_line = "1" if metric.series_id == "gdp" else "25"
    observations: list[Observation] = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("LineNumber", "")) != target_line:
            continue
        try:
            value_text, value = _number_text(row.get("DataValue"))
        except CollectionError as exc:
            if exc.code == "MISSING_VALUE":
                continue
            raise
        observations.append(
            Observation(
                series_id=metric.series_id,
                metric_key=metric.metric_key,
                observation_at=_period_iso(str(row.get("TimePeriod", ""))),
                vintage_at=fetched_at,
                value_text=value_text,
                value=value,
                unit=metric.unit,
                attributes={
                    "native_series_id": metric.native_series_id,
                    "line_number": target_line,
                    "line_description": row.get("LineDescription"),
                    "cl_unit": row.get("CL_UNIT"),
                    "unit_mult": row.get("UNIT_MULT"),
                },
            )
        )
    if not observations:
        raise CollectionError(
            "DATA_INVALID", "BEA_EMPTY", f"BEA returned no usable line {target_line} rows"
        )
    return observations


def _census_builder(now: datetime, env: dict[str, str]) -> HttpRequest:
    key = env.get("CENSUS_API_KEY", "").strip()
    if not key:
        raise CollectionError(
            "DATA_BLOCKED",
            "CENSUS_API_KEY_MISSING",
            "CENSUS_API_KEY is not configured",
        )
    params = {
        "get": "cell_value,data_type_code,time_slot_id,category_code,seasonally_adj",
        "time": f"from {now.year - 5}-01",
        "data_type_code": "SM",
        "category_code": "44X72",
        "seasonally_adj": "yes",
        "key": key,
    }
    public_params = {name: value for name, value in params.items() if name != "key"}
    base = "https://api.census.gov/data/timeseries/eits/marts"
    return HttpRequest(
        method="GET",
        url=base + "?" + urllib.parse.urlencode(params),
        public_locator=base + "?" + urllib.parse.urlencode(public_params),
        headers={"Accept": "application/json", "User-Agent": "Alpha-Research-MacroOS/1"},
        body=None,
        allowed_hosts=("api.census.gov",),
    )


def _census_parser(raw: bytes, fetched_at: str, spec: RequestSpec) -> list[Observation]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_guard)
    except UnicodeDecodeError as exc:
        raise CollectionError("DATA_INVALID", "INVALID_UTF8", "Census response is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise CollectionError("DATA_INVALID", "INVALID_JSON", "Census response is not JSON") from exc
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
        raise CollectionError("DATA_INVALID", "CENSUS_SHAPE", "Census response lacks tabular rows")
    header = [str(value) for value in payload[0]]
    if len(header) != len(set(header)):
        raise CollectionError("DATA_INVALID", "CENSUS_DUPLICATE_COLUMN", "Census response repeats a column")
    required = {"cell_value", "data_type_code", "category_code", "seasonally_adj", "time"}
    if not required.issubset(header):
        raise CollectionError("DATA_INVALID", "CENSUS_HEADER", "Census response lacks required columns")
    metric = spec.metrics[0]
    observations: list[Observation] = []
    for raw_row in payload[1:]:
        if not isinstance(raw_row, list) or len(raw_row) != len(header):
            raise CollectionError("DATA_INVALID", "CENSUS_SHAPE", "Census row width differs from header")
        row = dict(zip(header, raw_row))
        if (
            str(row["data_type_code"]) != "SM"
            or str(row["category_code"]) != "44X72"
            or str(row["seasonally_adj"]).lower() != "yes"
        ):
            continue
        value_text, value = _number_text(row["cell_value"])
        observations.append(
            Observation(
                series_id=metric.series_id,
                metric_key=metric.metric_key,
                observation_at=_period_iso(str(row["time"])),
                vintage_at=fetched_at,
                value_text=value_text,
                value=value,
                unit=metric.unit,
                attributes={
                    "native_series_id": metric.native_series_id,
                    "data_type_code": "SM",
                    "category_code": "44X72",
                    "seasonally_adjusted": True,
                    "time_slot_id": row.get("time_slot_id"),
                },
            )
        )
    if not observations:
        raise CollectionError("DATA_INVALID", "CENSUS_EMPTY", "Census returned no retail-sales rows")
    return observations


MONTHLY_AGE = 75 * 86400
QUARTERLY_AGE = 150 * 86400
DAILY_AGE = 7 * 86400
MONTHLY_FETCH = 7 * 86400
DAILY_FETCH = 2 * 86400

BLS_METRICS = (
    MetricSpec("average_hourly_earnings", "ahe_level", "CES0500000003", "usd_per_hour", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    MetricSpec("cpi", "headline_cpi_sa", "CUSR0000SA0", "index_1982_84_100", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    MetricSpec("jolts_job_openings", "job_openings", "JTS000000000000000JOL", "thousands", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    MetricSpec("nonfarm_payrolls", "total_nonfarm_employment", "CES0000000001", "thousands", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    MetricSpec("ppi", "final_demand_ppi_sa", "WPSFD4", "index_1982_100", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
    MetricSpec("unemployment_rate", "civilian_unemployment_rate", "LNS14000000", "pct", "monthly", MONTHLY_AGE, MONTHLY_FETCH),
)

CBOE_METRIC = MetricSpec(
    "vix_close", "vix_close", "VIX", "index_points", "daily", DAILY_AGE, DAILY_FETCH
)

FRED_METRICS = (
    MetricSpec("us_treasury_curve", "y2", "DGS2", "pct_annual", "daily", DAILY_AGE, DAILY_FETCH),
    MetricSpec("us_treasury_curve", "y10", "DGS10", "pct_annual", "daily", DAILY_AGE, DAILY_FETCH),
    MetricSpec("real_yields", "real_yield_10y", "DFII10", "pct_annual", "daily", DAILY_AGE, DAILY_FETCH),
    MetricSpec("ig_oas", "ig_oas", "BAMLC0A0CM", "pct_points", "daily", DAILY_AGE, DAILY_FETCH),
    MetricSpec("hy_oas", "hy_oas", "BAMLH0A0HYM2", "pct_points", "daily", DAILY_AGE, DAILY_FETCH),
)

BEA_GDP = MetricSpec(
    "gdp", "real_gdp_qoq_saar", "NIPA_T10101_LINE_1", "pct_qoq_saar", "quarterly", QUARTERLY_AGE, MONTHLY_FETCH
)
BEA_CORE_PCE = MetricSpec(
    "core_pce", "core_pce_price_index", "NIPA_T20304_LINE_25", "price_index", "monthly", MONTHLY_AGE, MONTHLY_FETCH
)
CENSUS_RETAIL_SALES = MetricSpec(
    "retail_sales",
    "retail_sales_value_sa",
    "MARTS_44X72_SM_SA",
    "million_usd_sa",
    "monthly",
    MONTHLY_AGE,
    MONTHLY_FETCH,
)


def collection_plan() -> tuple[RequestSpec, ...]:
    specs: list[RequestSpec] = [
        RequestSpec("bls_labor_prices", "bls_public_api", BLS_METRICS, _bls_builder, _bls_parser),
        RequestSpec("cboe_vix_history", "cboe_vix", (CBOE_METRIC,), _cboe_builder, _cboe_parser),
        RequestSpec("bea_gdp", "bea_public_api", (BEA_GDP,), _bea_builder("T10101", "Q"), _bea_parser),
        RequestSpec("bea_core_pce", "bea_public_api", (BEA_CORE_PCE,), _bea_builder("T20304", "M"), _bea_parser),
        RequestSpec(
            "census_retail_sales",
            "us_census_economic_indicators",
            (CENSUS_RETAIL_SALES,),
            _census_builder,
            _census_parser,
        ),
    ]
    specs.extend(
        RequestSpec(
            f"fred_{metric.native_series_id.lower()}",
            "fred_alfred",
            (metric,),
            _fred_builder(metric),
            _fred_parser,
        )
        for metric in FRED_METRICS
    )
    return tuple(specs)


def _transport_meta(
    response: HttpResponse,
    environment: dict[str, str],
    redacted_secret_names: Iterable[str] = (),
) -> dict[str, Any]:
    keep = ("content-type", "content-length", "etag", "last-modified")
    meta = {
        "final_host": (urllib.parse.urlsplit(response.final_url).hostname or "").lower(),
        "headers": {key: response.headers[key] for key in keep if key in response.headers},
    }
    encoded = json.dumps(meta, ensure_ascii=False, sort_keys=True).encode("utf-8")
    safe_encoded, header_names = _redact_response_body(encoded, environment)
    safe_meta = json.loads(safe_encoded.decode("utf-8"))
    redacted = sorted(set(redacted_secret_names) | set(header_names))
    return {
        **safe_meta,
        "redacted": bool(redacted),
        "redacted_secret_names": redacted,
    }


def collect(
    *,
    store: MacroHistoryStore,
    transport: Transport,
    specs: Iterable[RequestSpec],
    run_id: str,
    now: datetime | None,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    sources_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(sources_payload)
    registry_hash = sources_payload["registry_hash"]
    sources = contracts.source_index(sources_payload)
    environment = dict(os.environ if env is None else env)
    results: list[dict[str, Any]] = []
    for spec in specs:
        source = sources.get(spec.source_id)
        if source is None:
            raise MacroStoreError(f"collector references unknown M0-A source {spec.source_id}")
        request_now = now or datetime.now(timezone.utc)
        started_at = _iso_now(request_now)
        request: HttpRequest | None = None
        response: HttpResponse | None = None
        storage_body: bytes | None = None
        transport_meta: dict[str, Any] | None = None
        origin_validated = False
        try:
            if source["status"] in {"DATA_BLOCKED", "RETIRED"}:
                raise CollectionError(
                    "DATA_BLOCKED",
                    "SOURCE_NOT_ENABLED",
                    f"source registry status is {source['status']}",
                )
            request = spec.build_request(request_now, environment)
            public_host = (urllib.parse.urlsplit(request.public_locator).hostname or "").lower()
            if public_host not in request.allowed_hosts:
                raise CollectionError(
                    "DATA_INVALID", "UNAPPROVED_REQUEST_ORIGIN", "request host is not allowlisted"
                )
            response = transport.fetch(request)
            _validate_response_origin(request, response)
            origin_validated = True
            storage_body, redacted_names = _redact_response_body(
                response.body, environment
            )
            transport_meta = _transport_meta(response, environment, redacted_names)
            if response.status < 200 or response.status >= 300:
                raise CollectionError(
                    "SOURCE_DOWN", f"HTTP_{response.status}", f"source returned HTTP {response.status}"
                )
            fetched_at = _iso_now(now or datetime.now(timezone.utc))
            observations = spec.parser(storage_body, fetched_at, spec)
            emitted = {(row.series_id, row.metric_key) for row in observations}
            expected = {(row.series_id, row.metric_key) for row in spec.metrics}
            missing = sorted(expected - emitted)
            if missing:
                raise CollectionError(
                    "DATA_INVALID", "MISSING_METRICS", f"response omitted metrics: {missing}"
                )
            stored = store.record_success(
                run_id=run_id,
                request_id=spec.request_id,
                source=source,
                registry_hash=registry_hash,
                requested_series=spec.requested_series,
                started_at=started_at,
                fetched_at=fetched_at,
                public_locator=request.public_locator,
                response_url=_sanitize_url(response.final_url, environment),
                response_status=response.status,
                media_type=response.headers.get("content-type", "application/octet-stream"),
                raw_payload=storage_body,
                collector_version=COLLECTOR_VERSION,
                transport_meta=transport_meta,
                observations=observations,
            )
            results.append(
                {
                    "request_id": spec.request_id,
                    "source_id": spec.source_id,
                    "status": "OK",
                    "snapshot_hash": stored.snapshot_hash,
                    "rows": len(observations),
                    "inserted_rows": stored.inserted_observations,
                }
            )
        except CollectionError as exc:
            completed_at = _iso_now(now or datetime.now(timezone.utc))
            if (
                response is not None
                and request is not None
                and origin_validated
                and 200 <= response.status < 300
            ):
                if storage_body is None or transport_meta is None:
                    raise MacroStoreError(
                        "validated response lacks redacted storage payload"
                    )
                stored = store.record_invalid_response(
                    run_id=run_id,
                    request_id=spec.request_id,
                    source=source,
                    registry_hash=registry_hash,
                    requested_series=spec.requested_series,
                    started_at=started_at,
                    fetched_at=completed_at,
                    public_locator=request.public_locator,
                    response_url=_sanitize_url(response.final_url, environment),
                    response_status=response.status,
                    media_type=response.headers.get("content-type", "application/octet-stream"),
                    raw_payload=storage_body,
                    collector_version=COLLECTOR_VERSION,
                    transport_meta=transport_meta,
                    error_code=exc.code,
                    error_message=exc.safe_message,
                )
                snapshot_hash = stored.snapshot_hash
                locator = request.public_locator
            else:
                locator = request.public_locator if request else f"source://{spec.source_id}/{spec.request_id}"
                stored = store.record_failure(
                    run_id=run_id,
                    request_id=spec.request_id,
                    source=source,
                    registry_hash=registry_hash,
                    requested_series=spec.requested_series,
                    started_at=started_at,
                    completed_at=completed_at,
                    public_locator=locator,
                    status=exc.status,
                    error_code=exc.code,
                    error_message=exc.safe_message,
                )
                snapshot_hash = stored.snapshot_hash
            results.append(
                {
                    "request_id": spec.request_id,
                    "source_id": spec.source_id,
                    "status": exc.status,
                    "snapshot_hash": snapshot_hash,
                    "rows": 0,
                    "error_code": exc.code,
                }
            )
    return results


def build_health(
    *, store: MacroHistoryStore, specs: Iterable[RequestSpec], now: datetime
) -> dict[str, Any]:
    sources_payload = contracts.load_json(contracts.SOURCE_REGISTRY)
    contracts.validate_source_registry(sources_payload)
    source_rows = contracts.source_index(sources_payload)
    generated_at = _iso_now(now)
    now_utc = _parse_iso(generated_at)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        source = source_rows[spec.source_id]
        current_identity_hash = source_identity_hash(
            source, sources_payload["registry_hash"]
        )
        attempt = store.latest_attempt(spec.source_id, spec.request_id)
        for metric in spec.metrics:
            observation = store.latest_observation(
                spec.source_id, metric.series_id, metric.metric_key
            )
            status = "NOT_RUN"
            observation_age: int | None = None
            fetch_age: int | None = None
            if attempt:
                status = str(attempt["status"])
                fetch_age = max(
                    0, int((now_utc - _parse_iso(str(attempt["completed_at"]))).total_seconds())
                )
            if observation:
                raw_age = int(
                    (now_utc - _parse_iso(str(observation["observation_at"]))).total_seconds()
                )
                if raw_age < 0:
                    status = "DATA_INVALID"
                else:
                    observation_age = raw_age
            if status == "OK" and observation is None:
                status = "DATA_INVALID"
            recorded_identity_hash = (
                observation["source_identity_hash"]
                if observation
                else attempt["source_identity_hash"] if attempt else None
            )
            recorded_identity = (
                store.source_identity(recorded_identity_hash)
                if recorded_identity_hash
                else None
            )
            recorded_definition = (
                json.loads(recorded_identity["definition_json"])
                if recorded_identity
                else source
            )
            identity_is_current = recorded_identity_hash == current_identity_hash
            if status == "OK" and not identity_is_current:
                status = "STALE"
            if status == "OK" and (
                (observation_age is not None and observation_age > metric.max_observation_age_seconds)
                or (fetch_age is not None and fetch_age > metric.max_fetch_age_seconds)
            ):
                status = "STALE"
            stats = store.series_version_stats(
                spec.source_id, metric.series_id, metric.metric_key
            )
            rows.append(
                {
                    "source_id": spec.source_id,
                    "provider": (
                        recorded_identity["provider"]
                        if recorded_identity
                        else source["provider"]
                    ),
                    "current_provider": source["provider"],
                    "independence_group": (
                        recorded_identity["independence_group"]
                        if recorded_identity
                        else source["independence_group"]
                    ),
                    "current_independence_group": source["independence_group"],
                    "source_identity_hash": recorded_identity_hash,
                    "current_source_identity_hash": current_identity_hash,
                    "source_identity_current": identity_is_current,
                    "latest_attempt_source_identity_hash": (
                        attempt["source_identity_hash"] if attempt else None
                    ),
                    "official": (
                        bool(recorded_identity["official"])
                        if recorded_identity
                        else source["official"]
                    ),
                    "evidence_level": (
                        recorded_identity["evidence_level"]
                        if recorded_identity
                        else source["evidence_level"]
                    ),
                    "vintage_support": recorded_definition["vintage_support"],
                    "current_vintage_support": source["vintage_support"],
                    "request_id": spec.request_id,
                    "series_id": metric.series_id,
                    "metric_key": metric.metric_key,
                    "cadence": metric.cadence,
                    "status": status,
                    "as_of": observation["observation_at"] if observation else None,
                    "last_checked_at": attempt["completed_at"] if attempt else None,
                    "latest_snapshot_hash": (
                        observation["snapshot_hash"] if observation else None
                    ),
                    "latest_fetch_snapshot_hash": (
                        attempt["snapshot_hash"] if attempt else None
                    ),
                    "observation_age_seconds": observation_age,
                    "fetch_age_seconds": fetch_age,
                    "max_observation_age_seconds": metric.max_observation_age_seconds,
                    "max_fetch_age_seconds": metric.max_fetch_age_seconds,
                    "version_stats": stats,
                    "last_error_code": attempt["error_code"] if attempt else None,
                }
            )
    statuses = [row["status"] for row in rows]
    if statuses and all(status == "OK" for status in statuses):
        report = "COMPLETE"
    elif any(status in {"OK", "STALE"} for status in statuses):
        report = "PARTIAL"
    else:
        report = "DATA_BLOCKED"
    return {
        "schema": "ar.macro.source_health",
        "schema_version": "1.0",
        "report": report,
        "mode": "CALIBRATING",
        "as_of": generated_at,
        "generated_at": generated_at,
        "source_registry_hash": sources_payload["registry_hash"],
        "policy": {
            "formal_blocking_authority": False,
            "allowed_outputs": ["LABEL", "RISK_BUDGET_CONTEXT"],
            "forbidden_outputs": ["TRADE_ACTION", "DIRECT_BLOCK", "REGIME_CLAIM"],
        },
        "source_health": {
            "ok": sum(status == "OK" for status in statuses),
            "stale": sum(status == "STALE" for status in statuses),
            "blocked_or_failed": sum(
                status not in {"OK", "STALE"} for status in statuses
            ),
            "total": len(statuses),
        },
        "data": rows,
        "disclaimer": DISCLAIMER,
    }


def write_health(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    encoded = json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False, sort_keys=True
    ).encode("utf-8") + b"\n"
    with tmp.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


def _selected_specs(source_ids: list[str]) -> tuple[RequestSpec, ...]:
    plan = collection_plan()
    if not source_ids:
        return plan
    unknown = sorted(set(source_ids) - {spec.source_id for spec in plan})
    if unknown:
        raise CollectionError(
            "DATA_INVALID", "UNKNOWN_COLLECTOR", f"unknown collector source: {unknown}"
        )
    return tuple(spec for spec in plan if spec.source_id in set(source_ids))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--health-out", default=str(DEFAULT_HEALTH))
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--now", default=None, help="UTC ISO timestamp for deterministic operations")
    args = parser.parse_args(argv)
    try:
        fixed_now = _parse_iso(args.now) if args.now else None
        run_clock = fixed_now or datetime.now(timezone.utc)
        run_id = args.run_id or "macro_" + run_clock.strftime("%Y%m%d_%H%M%S")
        specs = _selected_specs(args.source)
        store = MacroHistoryStore(args.db)
        store.initialize()
        results = collect(
            store=store,
            transport=UrllibTransport(),
            specs=specs,
            run_id=run_id,
            now=fixed_now,
        )
        health = build_health(
            store=store,
            specs=specs,
            now=fixed_now or datetime.now(timezone.utc),
        )
        write_health(args.health_out, health)
        problems = store.verify_integrity()
        if problems:
            raise MacroStoreError("; ".join(problems))
        for row in results:
            print(
                f"macro_m0b: {row['request_id']} status={row['status']} rows={row['rows']}"
            )
        print(
            f"macro_m0b: report={health['report']} mode=CALIBRATING "
            f"db={args.db} health={args.health_out}"
        )
        return 0 if health["report"] == "COMPLETE" else 2
    except (CollectionError, MacroStoreError, contracts.ContractError, ValueError) as exc:
        print(f"macro_m0b: REFUSED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
