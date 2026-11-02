import { createSharedPoller, sharedRead } from './shared-view.mjs';

export function dataContextKey({ login, snapshotId, filters = {}, page = 0, allInputs = false }) {
  return JSON.stringify([login, snapshotId, filters.industry_key || '', filters.trade_date || '', filters.ts_code || '', page, allInputs]);
}

export function dataCenterView(state, key, parentStale, now = Date.now()) {
  if (state?.key !== key) return { data: null, stale: true, status: 'WAIT', error: '' };
  const stale = Boolean(parentStale || state.stale || !Number.isFinite(state.lastSuccessAt) || now - state.lastSuccessAt > 15000);
  return { ...state, stale, status: stale ? 'DISCONNECTED' : 'CONNECTED' };
}

export async function readDataCenter(api, { login, snapshotId, filters = {}, page = 0, allInputs = false }, renew) {
  const card = snapshotId ? await sharedRead(api, `/api/shared-workspace/input-card/${encodeURIComponent(snapshotId)}`, renew) : null;
  const params = new URLSearchParams({ page: String(page) });
  if (snapshotId && !allInputs) params.set('snapshot_id', snapshotId);
  for (const key of ['industry_key', 'trade_date', 'ts_code']) if (filters[key]) params.set(key, filters[key]);
  const materials = await sharedRead(api, `/api/shared-workspace/materials?${params}`, renew);
  if (materials?.schema !== 'ar.material-index.v1' || !Array.isArray(materials.rows) || !Array.isArray(materials.issues || []) ||
      materials.my_workspace?.login !== login || materials.human_review !== 'PENDING' ||
      (card && (card.schema !== 'ar.input-card.v1' || card.snapshot_id !== snapshotId || card.my_workspace?.login !== login ||
        card.consumer_code_sha !== materials.consumer_code_sha || card.human_review !== 'PENDING'))) {
    throw new Error('DATA_CONTEXT_MISMATCH');
  }
  return { card, materials };
}

export function createDataPoller(options) { return createSharedPoller(options); }
export function materialAvailability(materials) {
  const issues = materials?.issues || [];
  return { status: issues.length ? 'PARTIAL' : materials?.status || 'SCOPED_INDEX_AVAILABLE',
    emptyLabel: issues.length ? '结果不完整' : '无匹配材料', issues };
}
