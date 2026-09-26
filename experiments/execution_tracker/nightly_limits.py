"""Shared fail-closed process limits for the nightly orchestrator and its steps."""

# One authority source: child steps may reserve time inside their limit, and
# run_nightly passes step_timeout(step) to subprocess.run for every step.
NIGHTLY_STEP_TIMEOUT_SECONDS = 600

# candidate_battery has its own ceiling (2026-09-21). The owner requires every
# funnel candidate to be collected every night. From London a 184-200 candidate
# battery needed about 680-830s at four workers, so the shared 600s cut off the
# ts_code tail (on 20260921, 50 of 58 STAR candidates). Only this step is widened;
# every other step keeps the shared limit. The battery reserves time inside it.
# governance-mutation: NIGHTLY_BATTERY_STEP_CEILING
CANDIDATE_BATTERY_STEP_TIMEOUT_SECONDS = 1800
STEP_TIMEOUT_OVERRIDES = {"candidate_battery": CANDIDATE_BATTERY_STEP_TIMEOUT_SECONDS}


def step_timeout(step: str) -> int:
    """The subprocess timeout the orchestrator must give one named step."""
    # governance-mutation: NIGHTLY_STEP_TIMEOUT_OVERRIDE
    return STEP_TIMEOUT_OVERRIDES.get(step, NIGHTLY_STEP_TIMEOUT_SECONDS)
