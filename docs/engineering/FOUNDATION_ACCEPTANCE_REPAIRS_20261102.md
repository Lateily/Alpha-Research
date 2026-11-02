# Foundation Acceptance Repairs

The first frozen candidate, `57d1f24`, ran all 105 local offline CI steps: 99
passed and six failed. The mutation gate stopped during baseline validation;
there is no full mutation PASS from that candidate. The workbench build passed.

Two independent domain reviews found seven P2 blockers, all reproduced with
synthetic responses and local files. No live source, production, ledger or
shared-service mutation was authorized by these probes.

A subsequent non-author review of `cf17b22` found an eighth P2: default-field
v1 observations could accept identity/date-only rows as numeric source evidence.
Its in-progress acceptance runs were explicitly stopped and retained, not marked
PASS. The repair below covers every first-five default numeric baseline, with
contract-parity, explicit narrow-field, empty-response and finite-zero controls.

| Finding | Correction | Behavioral pin |
| --- | --- | --- |
| V1 missing ticker recorded success before consumer refusal | Require the requested stock identity before successful receipt publication | `test_v1_missing_response_ticker_cannot_record_success_or_ok_health` |
| V1 provider-default fields allowed date-only rows to report OK | Enforce the existing five-endpoint numeric baselines on nonempty default-field responses; preserve explicit narrow scopes, empty responses and numeric zero | `test_v1_default_fields_require_endpoint_numeric_evidence` and real daily-basic helper controls |
| Duplicate historical bars returned as normal OHLC | Refuse duplicate observed stock dates before returning bars; legacy path unchanged | `test_observed_daily_duplicate_historical_dates_cannot_return_ohlc_bars` |
| Future forecast period confused with future publication | Exempt forecast report periods only; publication cutoffs and filed-report guards remain | `test_forecast_published_future_report_period_is_not_invalid_period` and selector/control cases |
| HTTP parameter failure retried as outage | Preserve typed 400/422 errors in observed mode; legacy retries unchanged | `test_observed_http_parameter_error_is_one_attempt_param_error_and_blocked_plan` |
| Explicit global-index date ignored | Enforce selected bounds while retaining unverified foreign-calendar semantics | `test_global_explicit_trade_date_mismatch_is_outside_request_not_only_calendar_gap` |
| Full source/classification anchors could retain credential-shaped content | Screen raw anchors and decoded JSON before any persistence; never redact originals | `test_source_and_classification_anchor_credentials_refused_before_write` |
| Symlinked or raced output parents could mutate original source | Create new roots/children through no-follow directory descriptors and recheck identity | `test_symlink_output_parent_refused_before_any_creation`, raced-parent and quarantine cases |

The credential and source-mutation regressions were observed failing before the
fix. New mutation declarations must produce assertion failures, not setup errors.
Each data correction also retains normal, missing, conflicting or historical
controls in `test_endpoint_review_regressions.py`.

## Local Runner Corrections

- Existing tests that intentionally reject symlink ancestors require a canonical
  temporary root on macOS. The local runner uses `/private/tmp`, not the `/var`
  alias. Product no-follow checks are unchanged.
- The preservation collision fixture now supplies two distinct directory entries
  at the enumeration boundary. Writing `DATA.json` beside `data.json` cannot
  represent that scenario on a case-insensitive filesystem; it rewrote the source
  and triggered the existing hash guard instead. The exact collision reason and
  real guard are preserved.
- Real local HTTP/Unix-socket fixtures need host permission to bind sockets.
  A sandbox refusal is not a model result. External provider calls remain disabled.
- Synthetic test credentials remain explicitly dummy values; the repository
  secret scanner is not weakened or bypassed.

## Completion Boundary

These repairs do not grant deployment approval. Fresh full acceptance and
independent review must bind one clean final SHA. Local CI equivalents are not
remote GitHub results. Historical real intake remains its original immutable
operation, with 120 admitted and eight quarantined originals, not a current
research or prospective trading sample. Production and the existing shared
service stay unchanged until their respective gates pass.
