import assert from 'node:assert/strict';
import test from 'node:test';
import { existsSync } from 'node:fs';
const url = new URL('../tools/nonprod_workbench/ui/shared-view.mjs', import.meta.url);
const view = existsSync(url) ? await import(url) : {};
const identityContext={login:'owner@example.com',workspaceId:'51715142-1963-466f-8470-ceb609afccbd',codeSha:'a'.repeat(40)};
function contextReply(){return {schema:'ar.shared-workspace-context.v1',
  my_workspace:{login:identityContext.login,workspace_id:identityContext.workspaceId},
  execution_identity:{code_sha:identityContext.codeSha,source_tree_hash:'b'.repeat(64)},
  owned_commands:{'original-command':{job_id:'0cfde834-bca2-4a5a-8d8c-06c9110e1604'}},
  validation_scope:'IDENTITY_AND_JOB_REGISTRATION_NOT_OUTPUTS',sample_purpose:'WORKFLOW_DEBUG',
  human_review:'PENDING',production_authority:false,trading_authority:false};}
test('narrow context is an exact identity and registration contract without full-history GET',async()=>{
  assert.equal(typeof view.readSharedContext,'function');const calls=[],reply=contextReply();
  const received=await view.readSharedContext(async path=>{calls.push(path);return reply;},identityContext,assert.fail);
  assert.deepEqual(calls,['/api/shared-workspace/context']);assert.equal(received,reply);
  assert.equal(Object.hasOwn(received,'common_data'),false);assert.equal(Object.hasOwn(received,'my_jobs'),false);
});
test('narrow context rejects scope authority ownership code and malformed command bindings',async()=>{
  assert.equal(typeof view.readSharedContext,'function');
  for(const change of [d=>d.schema='ar.shared-workspace.v1',d=>d.validation_scope='FULLY_VERIFIED',
    d=>d.my_workspace.login='member@example.com',d=>d.my_workspace.workspace_id='another-workspace',
    d=>d.execution_identity.code_sha='c'.repeat(40),d=>d.execution_identity.source_tree_hash='bad',
    d=>d.execution_identity.code_sha=['a'.repeat(40)],d=>d.execution_identity.source_tree_hash=['b'.repeat(64)],
    d=>d.execution_identity.extra=true,d=>d.my_workspace.extra=true,d=>d.owned_commands=[],
    d=>d.owned_commands['original-command'].status='SUCCEEDED',d=>d.owned_commands['original-command'].job_id='../bad',
    d=>d.owned_commands['bad command']={job_id:'original-job'},d=>d.common_data={sync_status:'SYNCED'},
    d=>d.sample_purpose='ACCEPTED',d=>d.human_review='PASS',d=>d.production_authority=true,d=>d.trading_authority=true]){
    const bad=contextReply();change(bad);
    await assert.rejects(view.readSharedContext(async()=>bad,identityContext,assert.fail),/SHARED_CONTEXT_MISMATCH/);
  }
});
test('detail verification has its own exact fifteen-second age despite fresh common reads',()=>{
  const query={connection:'CONNECTED',stale:false,lastSuccessAt:16000};
  assert.equal(view.sharedViewFreshness(query,false,16000,1000).downloadsEnabled,true);
  const expired=view.sharedViewFreshness(query,false,16001,1000);
  assert.equal(expired.commonStale,false);assert.equal(expired.detailStale,true);assert.equal(expired.downloadsEnabled,false);
  for(const timestamp of [null,NaN,Infinity])
    assert.equal(view.sharedViewFreshness(query,false,16001,timestamp).downloadsEnabled,false);
});
test('start-aligned polling does not add five idle seconds after a slow verified response',async()=>{
  let now=1000,release;const timers=[];
  const poller=view.createSharedPoller({read:()=>new Promise(resolve=>{release=resolve;}),apply:()=>{},fail:assert.fail,
    cadenceFromStart:true,now:()=>now,schedule:(fn,delay)=>{timers.push({fn,delay});return 1;},cancel:()=>{}});
  const first=poller.refresh();now=13000;release({});await first;
  assert.equal(timers.length,1);assert.equal(timers[0].delay,0);
  poller.stop();
});
test('start-aligned fast reads retain a bounded delay and never change the legacy cadence',async()=>{
  for(const [aligned,elapsed,expected] of [[true,2000,1000],[true,-2000,1000],[false,12000,5000]]){
    let now=1000;const delays=[];
    const poller=view.createSharedPoller({read:async()=>{now+=elapsed;return {};},apply:()=>{},fail:assert.fail,
      cadenceFromStart:aligned,now:()=>now,schedule:(_,delay)=>{delays.push(delay);return 1;},cancel:()=>{}});
    await poller.refresh();poller.stop();assert.deepEqual(delays,[expected]);
  }
});
test('slow failed reads retain a retry cooldown instead of hammering invalid evidence',async()=>{
  let now=1000;const delays=[];
  const poller=view.createSharedPoller({read:async()=>{now+=12400;throw new Error('INVALID_EVIDENCE');},apply:assert.fail,fail:()=>{},
    cadenceFromStart:true,now:()=>now,schedule:(_,delay)=>{delays.push(delay);return 1;},cancel:()=>{}});
  await poller.refresh();poller.stop();assert.deepEqual(delays,[5000]);
});
test('a fast then slow verified response stays inside the unchanged freshness budget',async()=>{
  let now=0;const durations=[1000,12400],completions=[],delays=[];
  const poller=view.createSharedPoller({read:async()=>{now+=durations.shift();return {};},apply:()=>completions.push(now),fail:assert.fail,
    cadenceFromStart:true,now:()=>now,schedule:(_,delay)=>{delays.push(delay);return 1;},cancel:()=>{}});
  await poller.refresh();now+=delays[0];await poller.refresh();poller.stop();
  assert.ok(completions[1]-completions[0]<=15000,'post-read idle must budget the next slow read as well');
});
test('slow shared GET is single-flight and applies every completed read', async () => {
  assert.equal(typeof view.createSharedPoller, 'function', 'missing completion-driven polling');
  const responses = [], applied = [], timers = new Map(); let nextTimer = 0;
  const poller = view.createSharedPoller({
    read: () => new Promise(resolve => responses.push(resolve)),
    apply: value => applied.push(value), fail: error => assert.fail(error),
    schedule: callback => { timers.set(++nextTimer, callback); return nextTimer; },
    cancel: id => timers.delete(id)
  });
  const first = poller.refresh();
  for (let i = 0; i < 4; i++) poller.refresh();
  assert.equal(responses.length, 1, 'manual refresh must join the slow in-flight GET');
  assert.equal(timers.size, 0, 'no fixed interval while the request is pending');
  responses.shift()({ jobs: ['new-result'] }); await first;
  assert.deepEqual(applied, [{ jobs: ['new-result'] }]);
  assert.equal(timers.size, 1);
  const timer = [...timers.values()][0]; timers.clear(); timer();
  assert.equal(responses.length, 1);
  poller.stop(); responses.shift()({ jobs: ['old-page-or-identity'] });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(applied.length, 1, 'disposed view must not apply an old response');
  assert.equal(timers.size, 0);
});
test('successful read expires by age even if the next GET never resolves', () => {
  const query = view.sharedQueryState(null, { my_jobs: [] }, '', 1000);
  assert.equal(view.sharedViewFreshness(query, false, 16001).commonStale, true);
  assert.equal(view.sharedViewFreshness(query, false, 16001).downloadsEnabled, false);
  assert.equal(view.sharedViewFreshness(query, false, 1001).commonStale, false);
  const failed = view.sharedQueryState(query, null, 'DISCONNECTED', 17000);
  assert.equal(failed.lastSuccessAt, 1000);
});
test('actor switch immediately hides and disables retained workspace data', () => {
  assert.equal(typeof view.sharedActorQuery, 'function', 'missing current-actor projection');
  const query = view.sharedQueryState(null, {my_workspace:{login:'owner',workspace_id:'owner-workspace'}, my_jobs:[{job_id:'old'}]}, '', 1000);
  assert.equal(view.sharedActorQuery(query, 'owner'), query);
  const switched = view.sharedActorQuery(query, 'member');
  assert.equal(switched.data, null);
  assert.equal(view.sharedViewFreshness(switched, false, 1001).downloadsEnabled, false);
  assert.equal(view.sharedViewFreshness(switched, false, 1001).commonStale, true);
});
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
  // Keep the read younger than the age limit so only disconnect protection
  // can disable it; expiry must not accidentally kill this old mutation pin.
  const connected = view.sharedQueryState(null, { my_jobs: jobs }, '', 1000);
  const failed = view.sharedQueryState(connected, null, 'LOCAL_STATE_UNAVAILABLE', 1001);
  const freshness = view.sharedViewFreshness(failed, false, 1002);
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
test('explicit retry resolves two unknown deliveries with original inputs and late acceptance', async () => {
  assert.equal(typeof view.retrySharedPending, 'function', 'missing explicit original-command retry');
  const storage = storageFixture(), calls = [], accepted = new Map();
  const originals = [
    { command_id: 'unknown-first', kind: 'observe', snapshot_id: 'original-one' },
    { command_id: 'unknown-second', kind: 'snapshot-brief', snapshot_id: 'original-two' }
  ];
  for (const body of originals) view.savePending(storage, 'mine', body);
  view.savePending(storage, 'other', { ...originals[0], snapshot_id: 'other-input' });
  const otherBefore = view.getPending(storage, 'other');
  let executions = 0, lateAcceptance = false;
  const accept = body => {
    const prior = accepted.get(body.command_id);
    if (prior) { assert.deepEqual(prior.body, body); return prior; }
    const job = { job_id: `original-job-${++executions}`, body: { ...body } };
    accepted.set(body.command_id, job); return job;
  };
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path === '/api/shared-workspace') {
      const owned_commands = Object.fromEntries([...accepted].map(([id, job]) => [id, { job_id: job.job_id }]));
      // Simulate an original request accepted after this GET's image was read.
      if (lateAcceptance) { accept(originals[1]); lateAcceptance = false; }
      return { my_workspace: { workspace_id: 'mine' }, owned_commands,
        common_data: { current_snapshot_id: 'newest-must-not-replace-original' } };
    }
    if (body) {
      assert.equal(path, '/api/workspace/job');
      assert.deepEqual(body, originals.find(row => row.command_id === body.command_id));
      return { job_id: accept(body).job_id, status: 'QUEUED' };
    }
    return { workspace_id: 'mine', job_id: path.split('/').at(-1), status: 'SUCCEEDED' };
  };
  const renew = () => assert.fail('no cookie renewal needed');
  await view.pollSharedPending(api, storage, 'mine', {}, renew);
  assert.deepEqual(calls, [], 'automatic reconnect must not POST unknown deliveries');
  await view.retrySharedPending(api, storage, 'mine', originals[0].command_id, renew);
  assert.equal(view.getPending(storage, 'mine')[0].job_id, 'original-job-1');
  await view.pollSharedPending(api, storage, 'mine', {}, renew);
  assert.equal(view.getPending(storage, 'mine').length, 1, 'terminal query frees the original slot');
  lateAcceptance = true;
  await view.retrySharedPending(api, storage, 'mine', originals[1].command_id, renew);
  assert.equal(executions, 2, 'late original acceptance and retry must share one job');
  await view.pollSharedPending(api, storage, 'mine', {}, renew);
  assert.deepEqual(view.getPending(storage, 'mine'), []);
  assert.deepEqual(view.getPending(storage, 'other'), otherBefore);
  assert.deepEqual(calls.filter(call => call.body).map(call => call.body), originals);
  // Already accepted original: reconcile by GET without another intentional POST.
  view.savePending(storage, 'mine', originals[0]);
  await view.retrySharedPending(api, storage, 'mine', originals[0].command_id, renew);
  assert.equal(calls.filter(call => call.body).length, 2);
  assert.equal(view.getPending(storage, 'mine')[0].job_id, 'original-job-1');
});
test('explicit retry refuses a changed actor workspace without posting or touching pending', async () => {
  assert.equal(typeof view.retrySharedPending, 'function', 'missing actor-bound retry');
  const storage = storageFixture(), body = { command_id: 'same-command', kind: 'observe', snapshot_id: 'original-input' };
  view.savePending(storage, 'mine', body); view.savePending(storage, 'other', body);
  const before = ['mine', 'other'].map(id => view.getPending(storage, id));
  await assert.rejects(view.retrySharedPending(async (path, request) => {
    assert.equal(path, '/api/shared-workspace'); assert.equal(request, undefined);
    return { my_workspace: { workspace_id: 'other' }, owned_commands: {} };
  }, storage, 'mine', body.command_id, () => {}), /PENDING_WORKSPACE_MISMATCH/);
  assert.deepEqual(['mine', 'other'].map(id => view.getPending(storage, id)), before);
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
