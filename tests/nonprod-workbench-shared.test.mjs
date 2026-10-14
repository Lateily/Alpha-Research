import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
const url = new URL('../tools/nonprod_workbench/ui/shared-view.mjs', import.meta.url);
const view = existsSync(url) ? await import(url) : {};
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
