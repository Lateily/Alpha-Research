# experiments/

This directory is Codex's working area inside the AR Platform repo.

Codex may use this folder for:

- Independent validation.
- Divergence reports.
- Exploratory scripts.
- Backtest prototypes.
- Data-quality checks.
- Experiment specs.
- Claude handoff notes.

Codex should not use this folder to bypass production approval. Anything that
changes live pipeline behavior still requires Junyan's approval before moving
into `scripts/`, `src/`, `api/`, `public/data/`, or `.github/workflows/`.

## Required log

All meaningful findings should be appended to:

`experiments/CODEX_FINDINGS.md`

## Suggested filenames

- `EXP_001_data_health.md`
- `EXP_002_vp_engine_divergence.md`
- `EXP_003_wrongif_schema.md`
- `validate_vp_engine.py`
- `check_data_health.py`
- `compare_watchlist_to_pipeline.py`

## Default status

Experiments are not production changes.

Production readiness must be explicitly stated as one of:

- Not ready.
- Ready for Claude review.
- Ready for Junyan approval.
- Approved for production.
- Implemented in production.

