# Mentor-brief build tools (one-off, local)

These four scripts were used on 2026-08-15 on Junyan's Windows workstation to
build, render, and verify the mentor-brief `.docx` / proof PDF and contact
sheets that accompanied the 2026-08-13 AIOS meeting documents in this folder.

They are kept here for reproducibility only:

- They hardcode Windows paths (`C:\Users\jctx\Desktop\AR\output\meetings\...`)
  and Windows font files; adjust `OUT_DIR` / `DOCX` / `PDF` / `FIG` / `root`
  before running elsewhere.
- They depend on `python-docx` and `Pillow`, which are not part of the
  repository's runtime requirements.
- The rendered `.docx`, PDF, and PNG outputs are intentionally not committed.
- They are not wired into any nightly, CI, or product pipeline.
