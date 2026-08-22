# Video Evidence Contract

Record each evidence item with:

- source identifier and optional content hash;
- start and end timestamp;
- modality: `CAPTION`, `AUDIO`, `FRAME`, `ON_SCREEN_TEXT`, or `INFERENCE`;
- observation stated without interpretation;
- inference, when present, in a separate field;
- extraction method and coverage;
- confidence and conflict notes.

Use `TRANSCRIPT_ONLY`, `PARTIAL`, or `DATA_BLOCKED` whenever modality coverage
cannot support the requested claim. A transcript proves words were captured; it
does not prove who appeared, what changed visually, or what happened off-screen.
