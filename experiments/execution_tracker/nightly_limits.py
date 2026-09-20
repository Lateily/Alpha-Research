"""Shared fail-closed process limits for the nightly orchestrator and its steps."""

# One authority source: child steps may reserve time inside this limit, while
# run_nightly must pass the same value to subprocess.run.
NIGHTLY_STEP_TIMEOUT_SECONDS = 600
