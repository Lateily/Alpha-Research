// Display rules for the workbench research trust line and desk headline.
// Run: node tests/nonprod-workbench-trust-line.test.mjs
import assert from 'node:assert/strict';
import {
  countText, fileBindingText, levelChip, rateText, runQualityPairs, thresholdText, trustLineStatus
} from '../tools/nonprod_workbench/ui/trust-line-view.mjs';
import { statusTone } from '../tools/nonprod_workbench/ui/status-tone.mjs';

// Withheld and not-computable rates are text, never a zero percentage.
assert.equal(rateText({ rate: null, level: 'RATE_WITHHELD_N_BELOW_MIN', min_n: 20 }), '— (n<20)');
assert.equal(rateText({ rate: null, level: 'NOT_COMPUTABLE', not_computable_reason: 'NO_MACRO_MANIFEST' }),
  '不可算 · NO_MACRO_MANIFEST');
assert.equal(rateText({ rate: 0, level: 'MISSES_BAR', min_n: 20 }), '0.0%');
assert.equal(countText({ numerator: null, denominator: null }), '— / —');
assert.equal(countText({ numerator: 43, denominator: 46 }), '43 / 46');
// A not-computable metric never shows 0 / 0 beside 不可算.
assert.equal(countText({ numerator: 0, denominator: 0, level: 'NOT_COMPUTABLE' }), '— / —');
assert.equal(thresholdText({ threshold: 0.2, direction: 'LOWER_IS_BETTER' }), '≤ 20%（草案）');

// Levels are text chips; nothing is rendered green.
for (const level of ['MEETS_BAR', 'MISSES_BAR', 'RATE_WITHHELD_N_BELOW_MIN', 'NOT_COMPUTABLE']) {
  const chip = levelChip(level);
  assert.ok(chip.text.includes(level));
  assert.notEqual(chip.tone, 'green');
}
assert.equal(trustLineStatus({ status: 'NOT_PRODUCED' }).value, 'NOT_PRODUCED');
assert.equal(trustLineStatus({ status: 'REFUSED', reason: 'RUN_BINDING_MISMATCH' }).detail, 'RUN_BINDING_MISMATCH');
// A refused or absent line is visually distinct from a valid one.
assert.equal(statusTone('REFUSED'), 'red');
assert.equal(statusTone('NOT_PRODUCED'), 'amber');
assert.equal(statusTone(trustLineStatus({ status: 'PRESENT', e1_basis: 'SAME_AS_OF' }).value), 'neutral');

// A COMPLETE run with DATA_BLOCKED data shows both facts.
assert.deepEqual(runQualityPairs({ report: 'COMPLETE', data_quality: 'DATA_BLOCKED', research_data_quality: 'DATA_BLOCKED' }),
  [['运行完整性', 'COMPLETE'], ['数据质量', 'DATA_BLOCKED'], ['研究数据质量', 'DATA_BLOCKED']]);
assert.equal(fileBindingText({ issues: [] }), '0 FILE_BINDING_ISSUES');
assert.equal(fileBindingText(null), 'NOT_OBSERVED');
console.log('nonprod-workbench trust line display: ok');
