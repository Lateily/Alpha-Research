import { createSharedPoller, sharedRead } from './shared-view.mjs';

const fields = ['industry_key', 'industry_taxonomy', 'taxonomy_version', 'research_date', 'ts_code'];
const authorities = ['production_authority', 'paper_authority', 'u4_authority', 'trading_authority'];
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const forbidden = ['report', 'questions', 'excerpt', 'citations', 'artifact_files', 'pack_files', 'path'];
function validRow(row) {
  return row && typeof row === 'object' && !Array.isArray(row) &&
    !forbidden.some(key => key in row) && row.human_review === 'PENDING' &&
    authorities.every(key => row[key] === false) &&
    ['material_id','version','company','industry_key','industry_taxonomy','taxonomy_version',
      'source_cutoff_at','artifact_generated_at','archived_at','execution_attestation','stored_verification'].every(key => typeof row[key] === 'string') &&
    /^[0-9]{8}$/.test(row.research_date || '') && Array.isArray(row.assessments) &&
    row.assessments.every(value => value === 'UNRESOLVED') &&
    ['consumer_execution_identity','importer_execution_identity'].every(key =>
      /^[a-f0-9]{40}$/.test(row[key]?.code_sha || '') && digest(row[key]?.source_tree_hash)) &&
    ['result_hash','pack_hash','record_hash','report_sha256'].every(key => digest(row[key])) &&
    Array.isArray(row.source_documents) && row.source_documents.every(doc => doc &&
      !forbidden.some(key => key in doc) && digest(doc.pdf_sha256) && doc.publisher_status === 'UNVERIFIED' &&
      ['material_id','version','published_at','available_at','captured_at'].every(key => typeof doc[key] === 'string') &&
      (doc.publication_precision == null || typeof doc.publication_precision.basis === 'string'));
}
export function libraryContextKey({ login, codeSha, filters = {}, page = 0 }) {
  return JSON.stringify([login, codeSha, ...fields.map(key => filters[key] || ''), page]);
}
export function libraryView(state, key, parentStale, verificationEpoch) {
  if (state?.key !== key) return { data: null, stale: true, status: 'WAIT', error: '', hashStatus: 'NOT_CHECKED' };
  // governance-mutation: SHARED_RESEARCH_LIBRARY_REFRESH
  const stale = Boolean(parentStale || state.stale || state.verificationEpoch !== verificationEpoch);
  const hashStatus = state.data?.library_hash || (state.data?.status === 'NOT_CONFIGURED' ? 'NOT_CONFIGURED' : state.error ? 'UNAVAILABLE' : 'NOT_CHECKED');
  return { ...state, stale, status: stale ? 'DISCONNECTED' : state.data.status, hashStatus };
}
export async function readResearchLibrary(api, { login, codeSha, filters = {}, page = 0 }, renew) {
  const params = new URLSearchParams({ page: String(page) });
  for (const key of fields) if (filters[key]) params.set(key, filters[key]);
  const data = await sharedRead(api, `/api/shared-workspace/research-library?${params}`, renew);
  const configured = data?.status !== 'NOT_CONFIGURED';
  // governance-mutation: SHARED_RESEARCH_LIBRARY_CONTEXT
  if (data?.schema !== 'ar.shared-research-library.v1' || data.my_workspace?.login !== login ||
      data.consumer_code_sha !== codeSha || !/^[a-f0-9]{40}$/.test(codeSha || '') ||
      !['NOT_CONFIGURED', 'EMPTY', 'RESULTS_AVAILABLE_NOT_HUMAN_VERIFIED'].includes(data.status) ||
      (configured ? !digest(data.library_hash) : data.library_hash !== null) ||
      !Array.isArray(data.results) || !Number.isSafeInteger(data.total) || data.total < data.results.length ||
      data.page !== page || data.page_size !== 50 || data.results.length > 50 ||
      fields.some(key => (data.query?.[key] ?? null) !== (filters[key] || null)) ||
      data.human_review !== 'PENDING' || authorities.some(key => data[key] !== false) ||
      data.content_sharing_allowed !== false || data.content_status !== 'RIGHTS_UNVERIFIED_CONTENT_DENIED' ||
      data.rights?.status !== 'UNVERIFIED' || data.rights?.visibility !== 'PRIVATE' ||
      data.rights?.sharing_allowed !== false || data.rights?.model_use_allowed !== false ||
      (!configured && (data.total !== 0 || data.results.length !== 0)) ||
      data.results.some(row => !validRow(row))) {
    throw new Error('RESEARCH_LIBRARY_CONTEXT_MISMATCH');
  }
  return data;
}
export function createLibraryReader(options) {
  return createSharedPoller({ ...options, schedule: () => null, cancel: () => {} });
}
