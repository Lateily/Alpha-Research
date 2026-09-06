const red = new Set([
  'MISMATCH', 'HASH_MISMATCH', 'MISSING', 'MISSING_OR_INVALID', 'INVALID',
  'INCOMPLETE', 'FAILED', 'ERROR', 'INTEGRITY_ERROR', 'STOP', 'REJECT',
  'REJECTED_LOCAL'
]);
const amber = new Set([
  'STALE', 'FUTURE', 'BLOCKED', 'DATA_BLOCKED', 'PARTIAL', 'UNBOUND',
  'UNVERIFIED', 'WAIT', 'WAIT_TIMING', 'DRAFT', 'IN_REVIEW', 'OBSERVED_WITH_GAPS'
]);
const green = new Set(['OK', 'SUCCEEDED', 'MATCH', 'ACCEPTED_LOCAL', 'LOCAL_INTEGRITY_OK']);

export function statusTone(value) {
  if (red.has(value)) return 'red';
  if (amber.has(value)) return 'amber';
  // Only known complete tokens can signal success; unknown states stay neutral.
  if (green.has(value)) return 'green';
  return 'neutral';
}
