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
