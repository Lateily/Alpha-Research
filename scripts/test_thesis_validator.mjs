#!/usr/bin/env node
// Test gate for FC.1 (temporal validity) and the broader thesis validator.
//
// Why this exists: validateThesisQuality is a production code path that
// scores every thesis. FC.1 added step_1_catalyst_date_in_future to catch
// the "catalyst already happened" failure mode surfaced in
// docs/research/factcheck/700HK_pilot_2026-05-05.md §A1. We want a fast,
// no-API-cost gate that confirms the check fires correctly and the parser
// handles the date formats actually appearing in production thesis output.
//
// Run: node scripts/test_thesis_validator.mjs
// Exit: 0 = all PASS, 1 = any FAIL.

import { readFileSync } from 'fs';
import {
  validateThesisQuality,
  parseCatalystDate,
  isCatalystDateInFuture,
  CATALYST_DATE_BACKWARD_TOLERANCE_DAYS,
} from '../api/research.js';

let pass = 0, fail = 0;
const results = [];
function record(name, ok, detail) {
  results.push({ name, ok, detail });
  if (ok) pass++;
  else fail++;
}

// ─── 1. parseCatalystDate edge cases ──────────────────────────────────────
console.log('\n=== parseCatalystDate (8 cases) ===');
const parserCases = [
  // [input, expected_iso_date_or_null, description]
  ['2026-08-15 (Q3 2026 earnings, expected window)', '2026-08-15', 'ISO date with annotation'],
  ['Q3 2025 earnings ~2026-10-11 primary; 2026-08 Q2 secondary', '2026-10-11', 'last ISO date wins'],
  ['Q1 2026', '2026-03-31', 'quarter end-of-period'],
  ['1H 2026', '2026-06-30', 'half-year end-of-period'],
  ['November 2025', '2025-11-28', 'month name + year (28d safe)'],
  ['FY2026', '2026-12-31', 'fiscal year end-of-period'],
  ['2026', '2026-12-31', 'year only end-of-period'],
  ['next 3-6 months', null, 'vague phrase → unparseable'],
];
for (const [input, expectedIso, desc] of parserCases) {
  const got = parseCatalystDate(input);
  const gotIso = got ? got.toISOString().slice(0, 10) : null;
  const ok = gotIso === expectedIso;
  console.log(`  [${ok ? '✓' : '✗'}] parse("${input.slice(0, 50)}") → ${gotIso} (expected ${expectedIso})  // ${desc}`);
  record(`parser:${desc}`, ok, `got=${gotIso} expected=${expectedIso}`);
}

// ─── 2. isCatalystDateInFuture against fixed reference date ───────────────
console.log('\n=== isCatalystDateInFuture (reference 2026-05-05) ===');
const REF = new Date('2026-05-05T12:00:00Z');
const futureCases = [
  // [input, expected, description]
  ['2026-08-15', true, 'clearly future'],
  ['2025-11-12', false, 'clearly past (700.HK pilot anomaly A1)'],
  ['Q3 2026', true, 'future quarter'],
  ['Q1 2025', false, 'past quarter'],
  // Tolerance boundary: 14 days backward is allowed.
  // 2026-05-05 minus 14d = 2026-04-21. Catalyst on 2026-04-25 (10d back) → allowed.
  ['2026-04-25', true, 'within 14d backward tolerance (post-event retrospective OK)'],
  // 2026-04-15 (20d back) → outside tolerance, fails.
  ['2026-04-15', false, 'beyond 14d backward tolerance'],
  ['next quarter', null, 'unparseable → null (validator treats null as N/A pass)'],
];
for (const [input, expected, desc] of futureCases) {
  const got = isCatalystDateInFuture(input, REF);
  const ok = got === expected;
  console.log(`  [${ok ? '✓' : '✗'}] inFuture("${input}", 2026-05-05) → ${got} (expected ${expected})  // ${desc}`);
  record(`future:${desc}`, ok, `got=${got} expected=${expected}`);
}

// ─── 3. End-to-end: real thesis from pilot ────────────────────────────────
console.log('\n=== End-to-end on saved 700.HK thesis ===');
const THESIS_FILE = 'docs/research/factcheck/700HK_thesis_2026-05-05_1255BST.json';
const captured = JSON.parse(readFileSync(THESIS_FILE, 'utf8'));
const thesisData = captured.data;
console.log(`  loaded: ${THESIS_FILE}`);
console.log(`  catalyst_date_or_window: "${thesisData.step_1_catalyst.catalyst_date_or_window}"`);

const orig = validateThesisQuality(thesisData);
console.log(`  validator: score=${orig.score} severity=${orig.severity}`);
console.log(`  step_1_specific_not_vague:        ${orig.qcChecklistResults.step_1_specific_not_vague}`);
console.log(`  step_1_catalyst_date_in_future:   ${orig.qcChecklistResults.step_1_catalyst_date_in_future}`);
const okOrig = orig.qcChecklistResults.step_1_catalyst_date_in_future === false;
record('e2e:original-thesis-fails-temporal', okOrig,
  `step_1_catalyst_date_in_future=${orig.qcChecklistResults.step_1_catalyst_date_in_future}; expected false because catalyst date 2025-11-12 is 6mo before today (2026-05-05)`);
console.log(`  [${okOrig ? '✓' : '✗'}] expected step_1_catalyst_date_in_future === false (catalyst already happened)`);

// Patch to a future date — should now pass temporal check.
const patched = JSON.parse(JSON.stringify(thesisData));
patched.step_1_catalyst.catalyst_date_or_window = '2026-08-15 (Q3 2026 earnings, expected window)';
const patchedResult = validateThesisQuality(patched);
console.log(`\n  after patch to future date 2026-08-15:`);
console.log(`  validator: score=${patchedResult.score} severity=${patchedResult.severity}`);
console.log(`  step_1_catalyst_date_in_future:   ${patchedResult.qcChecklistResults.step_1_catalyst_date_in_future}`);
const okPatched = patchedResult.qcChecklistResults.step_1_catalyst_date_in_future === true;
record('e2e:patched-thesis-passes-temporal', okPatched,
  `step_1_catalyst_date_in_future=${patchedResult.qcChecklistResults.step_1_catalyst_date_in_future}; expected true after patch to 2026-08-15`);
console.log(`  [${okPatched ? '✓' : '✗'}] expected step_1_catalyst_date_in_future === true (after patch)`);

// Score delta check: original should be 1 check lower than patched.
const scoreDelta = patchedResult.score - orig.score;
console.log(`\n  score delta (patched − original): +${scoreDelta} pp (expected ≈ +6.67 = 1 non-step-8 check)`);
const okDelta = scoreDelta >= 6 && scoreDelta <= 8;
record('e2e:score-delta-1-check', okDelta, `delta=${scoreDelta}; expected 6-8 (single non-step-8 check weight 6.67)`);
console.log(`  [${okDelta ? '✓' : '✗'}] expected score delta in [6, 8]`);

// missingFields check: new validator-only check should NOT pollute missingFields
// even when not self-reported in qc_checklist (validator-only exclusion).
const missingNewCheck = orig.missingFields.some(f => f.includes('step_1_catalyst_date_in_future'));
record('e2e:no-spurious-missing-field', !missingNewCheck,
  missingNewCheck ? `step_1_catalyst_date_in_future appears in missingFields (should not — validator-only)` : 'no spurious missingField');
console.log(`  [${!missingNewCheck ? '✓' : '✗'}] step_1_catalyst_date_in_future not in missingFields (validator-only)`);

// ─── 4. Backward-compat: existing checks still working ───────────────────
console.log('\n=== Backward-compat (pre-FC.1 checks unaffected) ===');
const expectedExistingChecksTrue = [
  'step_1_specific_not_vague',
  'step_2_no_unfounded_leaps',
  'step_3_evidence_includes_quant_qual_contrarian',
  'step_3_contrarian_view_has_what_changes_our_mind',
  'step_4_has_specific_numbers_and_horizon',
  'step_5_observable',
  'step_6_observable',
  'step_7_one_sentence_tagline',
];
for (const check of expectedExistingChecksTrue) {
  const v = orig.qcChecklistResults[check];
  const ok = v === true;
  console.log(`  [${ok ? '✓' : '✗'}] ${check} = ${v}`);
  record(`bc:${check}-true`, ok, `got=${v} expected=true (700.HK pilot baseline)`);
}

// ─── Summary ──────────────────────────────────────────────────────────────
console.log(`\n${'═'.repeat(60)}`);
console.log(`Summary: ${pass} PASS / ${fail} FAIL (${results.length} total)`);
console.log(`Backward tolerance: ${CATALYST_DATE_BACKWARD_TOLERANCE_DAYS} days`);
if (fail > 0) {
  console.log(`\nFailures:`);
  results.filter(r => !r.ok).forEach(r => console.log(`  ✗ ${r.name} — ${r.detail}`));
  process.exit(1);
}
console.log(`\nAll tests pass. FC.1 temporal validity check is wired correctly.`);
process.exit(0);
