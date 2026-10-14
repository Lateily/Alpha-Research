import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
const url = new URL('../tools/nonprod_workbench/ui/shared-view.mjs', import.meta.url);
const view = existsSync(url) ? await import(url) : {};
test('common sync display retains old dates, new errors, times and separate identities', () => {
  assert.equal(typeof view.commonSyncView, 'function', 'missing common synchronization display');
  const common = { current_snapshot_id: 'old-input', error: 'SOURCE_CHANGED', sync_status: 'SYNC_FAILED',
    sync: { last_checked_at: 200, last_successful_sync_at: 100, source_run_id: 'old-run', source_trade_date: '20261012' },
    latest_attempt: { run_id: 'new-failed', report: 'INCOMPLETE', target_trade_date: '20261014' },
    observation: { run_identity: { latest_attempt: { run_id: 'old-attempt' }, last_published: { run_id: 'old-run', target_trade_date: '20261012' }, displayed: { run_id: 'old-run' } } } };
  const result = view.commonSyncView(common, false);
  assert.equal(result.status, 'SYNC_FAILED');
  assert.equal(result.error, 'SOURCE_CHANGED');
  assert.equal(result.lastCheckedAt, 200);
  assert.equal(result.lastSuccessfulSyncAt, 100);
  assert.equal(result.latestAttempt.run_id, 'new-failed');
  assert.equal(result.lastPublished.target_trade_date, '20261012');
  assert.equal(result.currentSnapshot.run_id, 'old-run');
  assert.equal(view.commonSyncView(common, true).status, 'DISCONNECTED');
  assert.equal(view.commonSyncView({ error: 'FROZEN_PUBLICATION_MISSING_OR_CONFLICTING' }, false).canBrief, false);
  assert.equal(result.canBrief, true);
});
const jobs = [
  { job_id: 'mine-old', actor: 'owner@example.com', kind: 'snapshot-brief', status: 'SUCCEEDED', submitted_at: 1 },
  { job_id: 'mine-new', actor: 'owner@example.com', kind: 'snapshot-brief', status: 'STOP', submitted_at: 3 },
  { job_id: 'team-green', actor: 'member@example.com', kind: 'snapshot-brief', status: 'SUCCEEDED', submitted_at: 4 }
];
test('my jobs exclude the other actor and unattributed history', () => {
  assert.equal(typeof view.selectMyJobs, 'function', 'missing S1 personal projection');
  assert.deepEqual(view.selectMyJobs([...jobs, { actor: 'LEGACY_UNATTRIBUTED' }], 'owner@example.com').map(j => j.job_id), ['mine-old', 'mine-new']);
});
test('latest owned STOP never falls back to a team success', () => {
  assert.equal(typeof view.latestOwnedJob, 'function', 'missing S1 latest-owned selection');
  assert.equal(view.latestOwnedJob(jobs, 'owner@example.com', 'snapshot-brief').job_id, 'mine-new');
  assert.equal(view.latestOwnedJob([...jobs].reverse(), 'owner@example.com', 'snapshot-brief').status, 'STOP');
  assert.equal(view.latestOwnedJob(jobs, 'nobody', 'observe'), null);
});
test('query failure explicitly marks disconnected without discarding stale ownership', () => {
  assert.equal(typeof view.sharedQueryState, 'function', 'missing S1 query failure state');
  const previous = { data: { my_jobs: jobs }, connection: 'CONNECTED' };
  const failed = view.sharedQueryState(previous, null, 'LOCAL_STATE_UNAVAILABLE');
  assert.equal(failed.connection, 'DISCONNECTED');
  assert.equal(failed.stale, true);
  assert.equal(failed.data, previous.data);
  assert.equal(view.sharedQueryState(failed, { my_jobs: [] }).connection, 'CONNECTED');
});
test('retained detail and common-data statuses and downloads are disconnected', () => {
  assert.equal(typeof view.sharedViewFreshness, 'function', 'missing retained-view freshness');
  assert.equal(typeof view.retainedStatus, 'function', 'missing retained-status protection');
  const failed = view.sharedQueryState({ data: { my_jobs: jobs }, connection: 'CONNECTED' }, null, 'LOCAL_STATE_UNAVAILABLE');
  const freshness = view.sharedViewFreshness(failed, false);
  assert.equal(freshness.commonStale, true);
  assert.equal(freshness.detailStale, true);
  assert.equal(freshness.downloadsEnabled, false);
  for (const status of ['SUCCEEDED', 'OK', 'MATCH', 'MANUAL_OBSERVE_ONLY']) {
    assert.equal(view.retainedStatus(status, freshness.commonStale), 'DISCONNECTED');
    assert.equal(view.retainedStatus(status, freshness.detailStale), 'DISCONNECTED');
  }
});
test('detail remains stale after list reconnect until its own successful revalidation', () => {
  assert.equal(typeof view.sharedViewFreshness, 'function', 'missing detail freshness');
  const connected = view.sharedQueryState(null, { my_jobs: jobs });
  assert.deepEqual(view.sharedViewFreshness(connected, true), { commonStale: false, detailStale: true, downloadsEnabled: false });
  assert.deepEqual(view.sharedViewFreshness(connected, false), { commonStale: false, detailStale: false, downloadsEnabled: true });
  assert.equal(view.retainedStatus('SUCCEEDED', false), 'SUCCEEDED');
});

function storageFixture() {
  const values = new Map();
  return { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}
test('pending requests keep their frozen input and are isolated by workspace', () => {
  assert.equal(typeof view.savePending, 'function', 'missing persistent pending storage');
  const storage = storageFixture();
  const body = { command_id: 'pending-command-001', kind: 'snapshot-brief', snapshot_id: 'frozen-one' };
  view.savePending(storage, 'workspace-one', body);
  assert.deepEqual(view.getPending(storage, 'workspace-two'), []);
  assert.deepEqual(view.getPending(storage, 'workspace-one')[0].body, body);
  view.savePending(storage, 'workspace-one', { ...body, snapshot_id: 'new-source' }, 'original-job');
  assert.equal(view.getPending(storage, 'workspace-one')[0].body.snapshot_id, 'frozen-one');
});
test('cookie renewal and reconnect only query the original job and never POST', async () => {
  assert.equal(typeof view.pollSharedPending, 'function', 'missing read-only pending recovery');
  const storage = storageFixture(), calls = [];
  const body = { command_id: 'lost-response-001', kind: 'observe', snapshot_id: 'original-input' };
  view.savePending(storage, 'mine', body);
  let cookie = false;
  const api = async (...args) => {
    calls.push(args);
    assert.equal(args.length, 1, 'reconnect must not send a request body');
    if (!cookie) { const error = new Error('COOKIE_REQUIRED'); error.status = 403; throw error; }
    return { job_id: 'original-job', workspace_id: 'mine', status: 'RUNNING' };
  };
  const renew = async () => { cookie = true; calls.push(['entry-renewal']); };
  await view.pollSharedPending(api, storage, 'mine', { 'lost-response-001': { job_id: 'original-job', status: 'RUNNING' } }, renew);
  assert.deepEqual(calls, [['/api/shared-workspace/jobs/original-job'], ['entry-renewal'], ['/api/shared-workspace/jobs/original-job']]);
  assert.equal(view.getPending(storage, 'mine')[0].job_id, 'original-job');
  assert.deepEqual(await view.pollSharedPending(api, storage, 'someone-else', {}, renew), []);
});
test('unconfirmed submission is not automatically resubmitted', async () => {
  assert.equal(typeof view.pollSharedPending, 'function');
  const storage = storageFixture();
  view.savePending(storage, 'mine', { command_id: 'unknown-command', kind: 'observe', snapshot_id: 'original-input' });
  await view.pollSharedPending(() => assert.fail('no accepted job exists to query'), storage, 'mine', {}, () => assert.fail('no renewal needed'));
  assert.equal(view.getPending(storage, 'mine').length, 1);
});
test('definitive HTTP rejection frees only that workspace pending record', () => {
  assert.equal(typeof view.recordSubmissionFailure, 'function', 'missing rejected submission cleanup');
  const storage = storageFixture();
  const body = { command_id: 'rejected-command', kind: 'observe', snapshot_id: 'original-input' };
  view.savePending(storage, 'mine', body); view.savePending(storage, 'other', body);
  view.recordSubmissionFailure(storage, 'mine', body.command_id, { status: 500 });
  assert.equal(view.getPending(storage, 'mine').length, 1, 'uncertain delivery must remain queryable');
  view.recordSubmissionFailure(storage, 'mine', body.command_id, { status: 429 });
  assert.deepEqual(view.getPending(storage, 'mine'), []);
  assert.equal(view.getPending(storage, 'other').length, 1);
});
test('terminal STOP clears only its own pending item and remains latest', async () => {
  assert.equal(typeof view.pollSharedPending, 'function');
  const storage = storageFixture();
  const body = { command_id: 'terminal-command', kind: 'snapshot-brief', snapshot_id: 'original-input' };
  view.savePending(storage, 'mine', body, 'mine-new'); view.savePending(storage, 'other', body, 'team-green');
  const details = await view.pollSharedPending(async () => ({ job_id: 'mine-new', workspace_id: 'mine', status: 'STOP' }), storage, 'mine', {}, async () => {});
  assert.equal(details[0].status, 'STOP');
  assert.deepEqual(view.getPending(storage, 'mine'), []);
  assert.equal(view.getPending(storage, 'other').length, 1);
  for (const status of ['QUEUED', 'RUNNING', 'INTERRUPTED', 'RECOVERY_REQUIRED']) {
    assert.equal(view.latestOwnedJob([...jobs, { ...jobs[1], status, submitted_at: 5 }], 'owner@example.com', 'snapshot-brief').status, status);
  }
});
