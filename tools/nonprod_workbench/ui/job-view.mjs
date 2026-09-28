export function latestJobByKind(jobs, kind) {
  return [...jobs].reverse().find(job => job.kind === kind);
}
