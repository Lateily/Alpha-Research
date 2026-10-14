export function selectMyJobs(jobs, login) {
  return jobs.filter(job => job.actor === login);
}

export function latestOwnedJob(jobs, login, kind) {
  return selectMyJobs(jobs, login).filter(job => job.kind === kind)
    .sort((a, b) => b.submitted_at - a.submitted_at)[0] || null;
}

export function sharedQueryState(previous, data, error = '') {
  if (error) return { data: previous?.data || null, connection: 'DISCONNECTED', stale: true, error };
  return { data, connection: 'CONNECTED', stale: false, error: '' };
}

export function sharedViewFreshness(query, detailStale = false) {
  const commonStale = query.stale || query.connection === 'DISCONNECTED';
  return { commonStale, detailStale: commonStale || detailStale, downloadsEnabled: !commonStale && !detailStale };
}

export function retainedStatus(value, stale) {
  return stale ? 'DISCONNECTED' : value;
}

export function commonSyncView(common, stale) {
  const identities = common?.observation?.run_identity || {};
  return {
    status: retainedStatus(common?.sync_status || 'NOT_PRODUCED', stale),
    error: common?.error || '',
    lastCheckedAt: common?.sync?.last_checked_at ?? null,
    lastSuccessfulSyncAt: common?.sync?.last_successful_sync_at ?? null,
    latestAttempt: common?.latest_attempt || identities.latest_attempt || {},
    lastPublished: identities.last_published || {},
    currentSnapshot: { ...identities.displayed, snapshot_id: common?.current_snapshot_id },
    canBrief: Boolean(common?.current_snapshot_id) && !stale
  };
}

const pendingKey = workspaceId => `ar.shared.pending.v1.${workspaceId}`;
export function getPending(storage, workspaceId) {
  if (!workspaceId) return [];
  try {
    const value = JSON.parse(storage.getItem(pendingKey(workspaceId)) || '[]');
    return Array.isArray(value) ? value.filter(item => item.workspace_id === workspaceId && item.body?.command_id && item.body?.snapshot_id) : [];
  } catch { return []; }
}

export function savePending(storage, workspaceId, body, jobId = null) {
  const rows = getPending(storage, workspaceId);
  const prior = rows.find(item => item.body.command_id === body.command_id);
  if (prior) { if (jobId) prior.job_id = jobId; }
  else rows.push({ workspace_id: workspaceId, body: { ...body }, job_id: jobId });
  storage.setItem(pendingKey(workspaceId), JSON.stringify(rows));
}

export function recordSubmissionFailure(storage, workspaceId, commandId, error) {
  if (error.status >= 400 && error.status < 500) {
    storage.setItem(pendingKey(workspaceId), JSON.stringify(getPending(storage, workspaceId).filter(item => item.body.command_id !== commandId)));
  }
}

export async function sharedRead(api, path, renew) {
  try { return await api(path); }
  catch (error) {
    if (error.status !== 403) throw error;
    await renew();
    return api(path);
  }
}

export async function pollSharedPending(api, storage, workspaceId, commands, renew) {
  const details = [];
  for (const item of getPending(storage, workspaceId)) {
    const jobId = item.job_id || commands[item.body.command_id]?.job_id;
    if (!jobId) continue;
    savePending(storage, workspaceId, item.body, jobId);
    const detail = await sharedRead(api, `/api/shared-workspace/jobs/${encodeURIComponent(jobId)}`, renew);
    if (detail.workspace_id !== workspaceId) throw new Error('PENDING_WORKSPACE_MISMATCH');
    details.push(detail);
    if (['SUCCEEDED', 'STOP', 'INTERRUPTED', 'RECOVERY_REQUIRED'].includes(detail.status)) {
      storage.setItem(pendingKey(workspaceId), JSON.stringify(getPending(storage, workspaceId).filter(row => row.body.command_id !== item.body.command_id)));
    }
  }
  return details;
}
