export const BRIDGE_SCHEMA = 'product-aios-bridge.v0' as const

export const BRIDGE_STATUSES = [
  'COMPLETE',
  'PARTIAL',
  'STALE',
  'BLOCKED',
  'ERROR',
] as const

export type BridgeStatus = (typeof BRIDGE_STATUSES)[number]

type FreshnessStatus = 'CURRENT' | 'STALE' | 'UNKNOWN'
type HumanReviewState = 'NOT_REQUESTED' | 'PENDING' | 'APPROVED' | 'REVISE' | 'REJECTED'
type MemoryState = 'NONE' | 'CANDIDATE' | 'REJECTED'

export interface ProductAiosBridgePacket {
  schema: typeof BRIDGE_SCHEMA
  generated_at: string
  status: BridgeStatus
  task: {
    schema: 'ai-task.v1'
    task_id: string
    objective: string
    human_owner: string
    reviewer: string
    state: string
  }
  run: {
    run_id: string
    executor: string
    state: string
    mode: 'SHADOW'
    network_policy: 'OFFLINE'
    cost_cny: string
  }
  freshness: {
    status: FreshnessStatus
    data_cutoff: string
    checked_at: string
  }
  artifact: {
    summary: string
    evidence_refs: string[]
    missing_evidence: string[]
    warnings: string[]
    blocking_reasons: string[]
    external_content_trust: 'UNTRUSTED_DATA'
    no_trade_flag: true
  }
  human_review: {
    state: HumanReviewState
    reviewer: string | null
    decision_ref: string | null
    final_merge_authority: 'Junyan'
    final_merge_authorized: false
  }
  memory_candidate: {
    state: MemoryState
    memory_id: string | null
    promoted: false
  }
  error_code: string | null
}

export interface BridgeValidationResult {
  ok: boolean
  packet: ProductAiosBridgePacket | null
  errors: string[]
}

export interface BridgeFixtureSetResult {
  ok: boolean
  fixtures: Record<BridgeStatus, ProductAiosBridgePacket> | null
  errors: string[]
}

const ROOT_KEYS = [
  'schema',
  'generated_at',
  'status',
  'task',
  'run',
  'freshness',
  'artifact',
  'human_review',
  'memory_candidate',
  'error_code',
] as const
const TASK_KEYS = ['schema', 'task_id', 'objective', 'human_owner', 'reviewer', 'state'] as const
const RUN_KEYS = ['run_id', 'executor', 'state', 'mode', 'network_policy', 'cost_cny'] as const
const FRESHNESS_KEYS = ['status', 'data_cutoff', 'checked_at'] as const
const ARTIFACT_KEYS = [
  'summary',
  'evidence_refs',
  'missing_evidence',
  'warnings',
  'blocking_reasons',
  'external_content_trust',
  'no_trade_flag',
] as const
const REVIEW_KEYS = [
  'state',
  'reviewer',
  'decision_ref',
  'final_merge_authority',
  'final_merge_authorized',
] as const
const MEMORY_KEYS = ['state', 'memory_id', 'promoted'] as const
const TASK_STATES = new Set([
  'DISCOVERED',
  'TRIAGED',
  'SPEC_READY',
  'CLAIMED',
  'RUNNING',
  'VERIFYING',
  'REVIEWING',
  'AWAITING_APPROVAL',
  'MERGED',
  'DEPLOYED',
  'VALIDATING',
  'DONE',
  'SPEC_BLOCKED',
  'BLOCKED',
  'RELEASED',
  'FAILED',
  'SUPERSEDED',
  'RETIRED',
  'DELIVERED_UNWIRED',
])
const SECRET_PATTERNS = [
  /\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}\b/i,
  /\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}\b/i,
  /\bAKIA[0-9A-Z]{12,}\b/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S{8,}/i,
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[], field: string, errors: string[]) {
  const expected = new Set(keys)
  const actual = Object.keys(value)
  const missing = keys.filter((key) => !(key in value))
  const extra = actual.filter((key) => !expected.has(key))
  if (missing.length > 0) errors.push(`${field} is missing required fields`)
  if (extra.length > 0) errors.push(`${field} contains unsupported fields`)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value === value.trim()
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyString)
}

function isAwareIsoTimestamp(value: unknown): value is string {
  if (!isNonEmptyString(value) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false
  return !Number.isNaN(Date.parse(value))
}

function containsSecretLikeValue(value: unknown): boolean {
  if (typeof value === 'string') return SECRET_PATTERNS.some((pattern) => pattern.test(value))
  if (Array.isArray(value)) return value.some(containsSecretLikeValue)
  if (isRecord(value)) return Object.values(value).some(containsSecretLikeValue)
  return false
}

function validateNestedRecord(
  value: unknown,
  keys: readonly string[],
  field: string,
  errors: string[],
): Record<string, unknown> | null {
  if (!isRecord(value)) {
    errors.push(`${field} must be an object`)
    return null
  }
  hasExactKeys(value, keys, field, errors)
  return value
}

export function validateProductAiosBridgePacket(value: unknown): BridgeValidationResult {
  const errors: string[] = []
  if (!isRecord(value)) {
    return { ok: false, packet: null, errors: ['packet must be an object'] }
  }

  hasExactKeys(value, ROOT_KEYS, 'packet', errors)
  if (containsSecretLikeValue(value)) errors.push('packet contains secret-like data')
  if (value.schema !== BRIDGE_SCHEMA) errors.push('schema is not supported')
  if (!isAwareIsoTimestamp(value.generated_at)) errors.push('generated_at must be timezone-aware ISO-8601')
  if (!BRIDGE_STATUSES.includes(value.status as BridgeStatus)) errors.push('status is not supported')

  const task = validateNestedRecord(value.task, TASK_KEYS, 'task', errors)
  const run = validateNestedRecord(value.run, RUN_KEYS, 'run', errors)
  const freshness = validateNestedRecord(value.freshness, FRESHNESS_KEYS, 'freshness', errors)
  const artifact = validateNestedRecord(value.artifact, ARTIFACT_KEYS, 'artifact', errors)
  const review = validateNestedRecord(value.human_review, REVIEW_KEYS, 'human_review', errors)
  const memory = validateNestedRecord(value.memory_candidate, MEMORY_KEYS, 'memory_candidate', errors)

  if (task) {
    if (task.schema !== 'ai-task.v1') errors.push('task.schema must be ai-task.v1')
    for (const field of ['task_id', 'objective', 'human_owner', 'reviewer']) {
      if (!isNonEmptyString(task[field])) errors.push(`task.${field} must be a non-empty string`)
    }
    if (!isNonEmptyString(task.state) || !TASK_STATES.has(task.state)) errors.push('task.state is not supported')
  }

  if (run) {
    for (const field of ['run_id', 'executor']) {
      if (!isNonEmptyString(run[field])) errors.push(`run.${field} must be a non-empty string`)
    }
    if (!isNonEmptyString(run.state) || !TASK_STATES.has(run.state)) errors.push('run.state is not supported')
    if (run.mode !== 'SHADOW') errors.push('run.mode must be SHADOW')
    if (run.network_policy !== 'OFFLINE') errors.push('run.network_policy must be OFFLINE')
    if (!isNonEmptyString(run.cost_cny) || !/^\d+(?:\.\d+)?$/.test(run.cost_cny)) {
      errors.push('run.cost_cny must be a non-negative decimal string')
    }
  }

  if (freshness) {
    if (!['CURRENT', 'STALE', 'UNKNOWN'].includes(String(freshness.status))) {
      errors.push('freshness.status is not supported')
    }
    if (!isAwareIsoTimestamp(freshness.data_cutoff)) errors.push('freshness.data_cutoff must be timezone-aware ISO-8601')
    if (!isAwareIsoTimestamp(freshness.checked_at)) errors.push('freshness.checked_at must be timezone-aware ISO-8601')
  }

  if (artifact) {
    if (!isNonEmptyString(artifact.summary)) errors.push('artifact.summary must be a non-empty string')
    for (const field of ['evidence_refs', 'missing_evidence', 'warnings', 'blocking_reasons']) {
      if (!isStringList(artifact[field])) errors.push(`artifact.${field} must be a string list`)
    }
    if (artifact.external_content_trust !== 'UNTRUSTED_DATA') {
      errors.push('artifact.external_content_trust must be UNTRUSTED_DATA')
    }
    if (artifact.no_trade_flag !== true) errors.push('artifact.no_trade_flag must be true')
  }

  if (review) {
    const reviewStates = ['NOT_REQUESTED', 'PENDING', 'APPROVED', 'REVISE', 'REJECTED']
    if (!reviewStates.includes(String(review.state))) errors.push('human_review.state is not supported')
    if (review.reviewer !== null && !isNonEmptyString(review.reviewer)) errors.push('human_review.reviewer is invalid')
    if (review.decision_ref !== null && !isNonEmptyString(review.decision_ref)) errors.push('human_review.decision_ref is invalid')
    if (review.final_merge_authority !== 'Junyan') errors.push('final merge authority must remain Junyan')
    if (review.final_merge_authorized !== false) errors.push('bridge cannot authorize final merge')
    if (review.state === 'APPROVED' && review.decision_ref === null) errors.push('approved review requires decision_ref')
    if (review.state === 'APPROVED' && run && review.reviewer === run.executor) {
      errors.push('executor cannot approve its own output')
    }
    if (review.state === 'APPROVED' && task && review.reviewer !== task.reviewer) {
      errors.push('approved reviewer must match task.reviewer')
    }
  }

  if (memory) {
    if (!['NONE', 'CANDIDATE', 'REJECTED'].includes(String(memory.state))) {
      errors.push('memory_candidate.state is not supported')
    }
    if (memory.memory_id !== null && !isNonEmptyString(memory.memory_id)) errors.push('memory_candidate.memory_id is invalid')
    if (memory.promoted !== false) errors.push('bridge cannot promote memory')
  }

  if (value.status === 'COMPLETE') {
    if (!artifact || !isStringList(artifact.evidence_refs) || artifact.evidence_refs.length === 0) {
      errors.push('COMPLETE requires evidence_refs')
    }
    if (artifact && isStringList(artifact.missing_evidence) && artifact.missing_evidence.length > 0) {
      errors.push('COMPLETE cannot have missing_evidence')
    }
    if (!review || review.state !== 'APPROVED') errors.push('COMPLETE requires approved human review')
  }
  if (value.status === 'PARTIAL' && artifact && isStringList(artifact.missing_evidence) && artifact.missing_evidence.length === 0) {
    errors.push('PARTIAL requires missing_evidence')
  }
  if (value.status === 'STALE' && freshness?.status !== 'STALE') errors.push('STALE requires stale freshness')
  if (value.status === 'BLOCKED' && artifact && isStringList(artifact.blocking_reasons) && artifact.blocking_reasons.length === 0) {
    errors.push('BLOCKED requires blocking_reasons')
  }
  if (value.status === 'ERROR' && !isNonEmptyString(value.error_code)) errors.push('ERROR requires error_code')
  if (value.status !== 'ERROR' && value.error_code !== null) errors.push('error_code is only allowed for ERROR')

  if (errors.length > 0) return { ok: false, packet: null, errors: [...new Set(errors)] }
  return { ok: true, packet: value as unknown as ProductAiosBridgePacket, errors: [] }
}

export function validateProductAiosBridgeFixtureSet(value: unknown): BridgeFixtureSetResult {
  if (!isRecord(value) || value.schema !== 'product-aios-bridge.fixtures.v0' || !isRecord(value.fixtures)) {
    return { ok: false, fixtures: null, errors: ['fixture set contract is invalid'] }
  }
  const rootKeys = Object.keys(value)
  if (rootKeys.length !== 2 || !rootKeys.includes('schema') || !rootKeys.includes('fixtures')) {
    return { ok: false, fixtures: null, errors: ['fixture set contains unsupported fields'] }
  }
  const fixtureKeys = Object.keys(value.fixtures)
  if (
    fixtureKeys.length !== BRIDGE_STATUSES.length
    || !BRIDGE_STATUSES.every((status) => fixtureKeys.includes(status))
  ) {
    return { ok: false, fixtures: null, errors: ['fixture set must contain exactly five statuses'] }
  }

  const fixtures = {} as Record<BridgeStatus, ProductAiosBridgePacket>
  const errors: string[] = []
  for (const status of BRIDGE_STATUSES) {
    const result = validateProductAiosBridgePacket(value.fixtures[status])
    if (!result.ok || !result.packet || result.packet.status !== status) {
      errors.push(`${status} fixture is invalid`)
      continue
    }
    fixtures[status] = result.packet
  }
  if (errors.length > 0) return { ok: false, fixtures: null, errors }
  return { ok: true, fixtures, errors: [] }
}
