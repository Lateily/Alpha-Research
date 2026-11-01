import test from 'node:test';
import assert from 'node:assert/strict';
import { createDataPoller, dataContextKey, dataCenterView, materialAvailability, readDataCenter } from '../tools/nonprod_workbench/ui/data-center-view.mjs';

const login = 'owner@example.invalid';
const sid = '53a8ee9a-327c-4e9c-ac7c-5d2d39023448';
const card = { schema: 'ar.input-card.v1', snapshot_id: sid, input_hash: 'a'.repeat(64),
  source_run_id: 'published', source_trade_date: '20261015', consumer_code_sha: 'b'.repeat(40),
  my_workspace: { login }, human_review: 'PENDING' };
const materials = { schema: 'ar.material-index.v1', rows: [], total: 0,
  consumer_code_sha: 'b'.repeat(40), my_workspace: { login }, human_review: 'PENDING' };
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

test('request binds current input and sends only supported read filters', async () => {
  const calls = [];
  const api = async path => { calls.push(path); return path.includes('input-card/') ? card : materials; };
  const result = await readDataCenter(api, { login, snapshotId: sid, filters: { industry_key: 'semiconductor', trade_date: '20261015', ts_code: '' }, page: 0, allInputs: false });
  assert.equal(result.card.input_hash, card.input_hash);
  assert.equal(calls.length, 2);
  const query = new URL(calls[1], 'http://localhost').searchParams;
  assert.equal(query.get('snapshot_id'), sid);
  assert.equal(query.get('industry_key'), 'semiconductor');
  assert.equal(query.has('ts_code'), false);
});

test('actor, snapshot, code and human-state mismatches are refused', async () => {
  for (const wrong of [{ ...card, snapshot_id: 'foreign' }, { ...card, my_workspace: { login: 'other' } },
    { ...card, consumer_code_sha: 'c'.repeat(40) }, { ...card, human_review: 'VERIFIED' }]) {
    await assert.rejects(readDataCenter(async path => path.includes('input-card/') ? wrong : materials,
      { login, snapshotId: sid, filters: {}, page: 0 }), /DATA_CONTEXT_MISMATCH/);
  }
});

test('actor or filter changes hide previously verified data immediately', () => {
  const key = dataContextKey({ login, snapshotId: sid, filters: {}, page: 0 });
  const state = { key, data: { card, materials }, lastSuccessAt: 1000, stale: false };
  assert.equal(dataCenterView(state, key, false, 1001).stale, false);
  assert.equal(dataCenterView(state, 'different-query', false, 1001).data, null);
  assert.equal(dataCenterView(state, key, true, 1001).status, 'DISCONNECTED');
  assert.equal(dataCenterView(state, key, false, 17000).status, 'DISCONNECTED');
});

test('old slow response cannot overwrite a disposed actor/filter view', async () => {
  const pending = defer(), seen = []; let reads = 0;
  const poller = createDataPoller({ read: () => { ++reads; return pending.promise; }, apply: value => seen.push(value),
    fail: error => { throw error; }, schedule: () => 1, cancel: () => {} });
  const run = poller.refresh();
  assert.equal(reads, 1);
  poller.stop(); pending.resolve({ card, materials }); await run;
  assert.deepEqual(seen, []);
});

test('disconnect is reported without any POST or automatic resubmission', async () => {
  const calls = [], failures = [];
  const api = async (...args) => { calls.push(args); throw new Error('offline'); };
  const poller = createDataPoller({ read: () => readDataCenter(api, { login, snapshotId: sid, filters: {}, page: 0 }),
    apply: () => assert.fail('must not become connected'), fail: error => failures.push(error.message), schedule: () => 1, cancel: () => {} });
  await poller.refresh(); poller.stop();
  assert.equal(failures[0], 'offline');
  assert.equal(calls.length, 1); assert.equal(calls[0].length, 1);
});

test('unsupported material shape is exposed as incomplete rather than no results', () => {
  const issue = { snapshot_id: sid, error: 'UNSUPPORTED_CANDIDATE_ROWS' };
  const view = materialAvailability({ rows: [], issues: [issue] });
  assert.equal(view.status, 'PARTIAL');
  assert.equal(view.emptyLabel, '结果不完整');
  assert.deepEqual(view.issues, [issue]);
  assert.equal(materialAvailability({ rows: [], issues: [] }).emptyLabel, '无匹配材料');
});
