export function latestJobByKind(jobs, kind) {
  return [...jobs].reverse().find(job => job.kind === kind);
}

export function snapshotBriefPresentation(job) {
  if (job.status === 'STARTED') return 'pending';
  return job.status === 'SUCCEEDED' ? 'ready' : 'failed';
}
