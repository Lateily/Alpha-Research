import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  validateProductAiosBridgeFixtureSet,
  validateProductAiosBridgePacket,
} from '../src/contracts/productAiosBridge.ts'

const fixtureUrl = new URL('../public/data/v2/aios/product-aios-bridge-fixtures.v0.json', import.meta.url)
const fixtureDocument: unknown = JSON.parse(readFileSync(fixtureUrl, 'utf8'))
const fixtureSetResult = validateProductAiosBridgeFixtureSet(fixtureDocument)
assert.equal(fixtureSetResult.ok, true, fixtureSetResult.errors.join(', '))
assert.ok(fixtureSetResult.fixtures)
const fixtures = fixtureSetResult.fixtures

const withUnknownField = structuredClone(fixtures.COMPLETE) as unknown as Record<string, unknown>
withUnknownField.provider_key = 'not-a-real-value'
assert.equal(validateProductAiosBridgePacket(withUnknownField).ok, false)

const syntheticSecret = `ghp_${'a'.repeat(36)}`
const withSecret = structuredClone(fixtures.COMPLETE)
withSecret.task.task_id = syntheticSecret
const secretResult = validateProductAiosBridgePacket(withSecret)
assert.equal(secretResult.ok, false)
assert.equal(JSON.stringify(secretResult).includes(syntheticSecret), false)

const incompleteComplete = structuredClone(fixtures.COMPLETE)
incompleteComplete.artifact.evidence_refs = []
assert.equal(validateProductAiosBridgePacket(incompleteComplete).ok, false)

const staleFalsePass = structuredClone(fixtures.STALE)
staleFalsePass.freshness.status = 'CURRENT'
assert.equal(validateProductAiosBridgePacket(staleFalsePass).ok, false)

const selfApproved = structuredClone(fixtures.COMPLETE)
selfApproved.run.executor = 'Jason'
assert.equal(validateProductAiosBridgePacket(selfApproved).ok, false)

const tradeEnabled = structuredClone(fixtures.COMPLETE) as unknown as {
  artifact: { no_trade_flag: boolean }
}
tradeEnabled.artifact.no_trade_flag = false
assert.equal(validateProductAiosBridgePacket(tradeEnabled).ok, false)

const naiveTimestamp = structuredClone(fixtures.COMPLETE)
naiveTimestamp.freshness.data_cutoff = '2026-08-17T09:00:00'
assert.equal(validateProductAiosBridgePacket(naiveTimestamp).ok, false)

const finalMergeFalsePass = structuredClone(fixtures.COMPLETE) as unknown as {
  human_review: { final_merge_authorized: boolean }
}
finalMergeFalsePass.human_review.final_merge_authorized = true
assert.equal(validateProductAiosBridgePacket(finalMergeFalsePass).ok, false)

const fixtureSetWithExtra = structuredClone(fixtureDocument) as Record<string, unknown>
fixtureSetWithExtra.provider = 'none'
assert.equal(validateProductAiosBridgeFixtureSet(fixtureSetWithExtra).ok, false)

console.log('PRODUCT AIOS BRIDGE CONTRACT TESTS PASS (14 tests, 0 network calls)')
