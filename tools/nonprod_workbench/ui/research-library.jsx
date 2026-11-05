import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileSearch, Play, RefreshCw, Search, X } from 'lucide-react';
import { createLibraryReader, libraryContextKey, libraryView, readResearchLibrary } from './research-library-view.mjs';
import { statusTone } from './status-tone.mjs';
import { sharedRead } from './shared-view.mjs';

export default function ResearchLibrary({ api, renew, login, codeSha, parentStale, refreshRevision, onRun, busy }) {
  const [packs, setPacks] = useState(null), [packId, setPackId] = useState(''), [packError, setPackError] = useState('');
  const [draft, setDraft] = useState({ industry_key: '', research_date: '', ts_code: '', industry_taxonomy: '', taxonomy_version: '' });
  const [filters, setFilters] = useState({}), [page, setPage] = useState(0), [selected, setSelected] = useState(null);
  const [state, setState] = useState(null), reader = useRef(null), currentKey = useRef(null);
  const parentCycle = useRef({ stale: parentStale, epoch: 0 });
  if (parentCycle.current.stale !== parentStale) parentCycle.current = { stale: parentStale, epoch: parentCycle.current.epoch + 1 };
  const verificationEpoch = JSON.stringify([refreshRevision, parentCycle.current.epoch]);
  const context = { login, codeSha, filters, page }, key = libraryContextKey(context);
  const requestKey = JSON.stringify([key, verificationEpoch]); currentKey.current = requestKey;
  const view = libraryView(state, key, parentStale, verificationEpoch), data = view.data;
  const detail = data?.results.find(row => row.record_hash === selected);
  useEffect(() => {
    let active = true;
    setPacks(null); setPackId(''); setPackError('');
    if (parentStale || !codeSha) return;
    sharedRead(api, '/api/shared-workspace/research-inputs', renew).then(result => {
      if (!active) return;
      if (result.my_workspace.login !== login || (result.enabled && result.consumer_code_sha !== codeSha)) throw new Error('RESEARCH_INPUT_CONTEXT_CHANGED');
      setPacks(result);
    }).catch(error => { if (active) setPackError(error.message); });
    return () => { active = false; };
  }, [login, codeSha, parentStale, refreshRevision]);
  useEffect(() => {
    if (!codeSha || parentStale) { reader.current = null; return; }
    const controller = createLibraryReader({
      read: () => readResearchLibrary(api, context, renew),
      apply: data => { if (currentKey.current === requestKey) setState({ key, verificationEpoch, data, stale: false, error: '', checkedAt: new Date().toISOString() }); },
      fail: error => { if (currentKey.current === requestKey) setState(old => ({ key, verificationEpoch, data: old?.key === key ? old.data : null,
        stale: true, error: error.message, checkedAt: old?.key === key ? old.checkedAt : null })); }
    });
    reader.current = controller; controller.refresh();
    return () => { controller.stop(); if (reader.current === controller) reader.current = null; };
  }, [key, verificationEpoch, parentStale]);
  function submit(event) {
    event.preventDefault(); setSelected(null); setPage(0);
    const next = { ...draft, research_date: draft.research_date.replaceAll('-', '') };
    setFilters(next);
    if (libraryContextKey({ login, codeSha, filters: next, page: 0 }) === key) reader.current?.refresh();
  }
  const badge = value => <span className={`badge ${statusTone(view.stale ? view.status : value)}`}>{view.stale ? view.status : value}</span>;
  const change = key => event => setDraft({ ...draft, [key]: event.target.value });
  return <div className="data-center research-library">
    <div className="section-title"><h3>研究资料库</h3><div>{badge(view.status)}<button className="icon-button" title="重新核验研究资料库" aria-label="刷新研究资料库" onClick={() => reader.current?.refresh()}><RefreshCw size={17} /></button></div></div>
    <div className="source-strip"><span>索引只读</span><span>人工核验 PENDING</span><span>正文分发 DENIED</span><span>最后核验 {view.checkedAt || 'NOT_CHECKED'}</span></div>
    {view.error && <div className="shared-error" role="alert">DISCONNECTED · {view.error}</div>}
    {packError && <div className="shared-error" role="alert">{packError}</div>}
    {packs?.enabled && <div className="research-filters"><label>冻结财报材料<select aria-label="冻结财报材料" value={packId} onChange={event => setPackId(event.target.value)}><option value="">选择材料包</option>{packs.inputs.map(pack => <option key={pack.snapshot_id} value={pack.snapshot_id}>{pack.company} · {pack.research_date} · {pack.pack_hash.slice(0,12)}</option>)}</select></label><button className="icon-button" title="提交财报回应任务" aria-label="提交财报回应任务" disabled={busy || parentStale || !packId} onClick={() => onRun?.(packId)}><Play size={18} /></button>{packs.inputs.filter(pack => pack.snapshot_id === packId).map(pack => <code key={pack.snapshot_id}>{pack.input_hash} · 原件截止 {pack.source_cutoff_at}</code>)}</div>}
    <form className="research-filters" onSubmit={submit}>
      <label>行业<input value={draft.industry_key} maxLength={128} onChange={change('industry_key')} /></label>
      <label>研究日<input type="date" value={draft.research_date} onChange={change('research_date')} /></label>
      <label>股票代码<input value={draft.ts_code} maxLength={9} onChange={event => setDraft({ ...draft, ts_code: event.target.value.trim().toUpperCase() })} /></label>
      <button className="icon-button" title="查询研究索引" aria-label="查询研究索引" type="submit"><Search size={18} /></button>
      <details className="research-taxonomy"><summary>行业分类口径</summary><div><label>分类体系<input value={draft.industry_taxonomy} maxLength={128} onChange={change('industry_taxonomy')} /></label><label>分类版本<input value={draft.taxonomy_version} maxLength={128} onChange={change('taxonomy_version')} /></label></div></details>
    </form>
    <div className="source-strip"><span>{data?.total ?? '—'} 项</span><span>库 hash</span><code>{view.hashStatus}</code></div>
    <div className="table-scroll"><table><thead><tr><th>股票 / 研究日</th><th>行业 / 分类版本</th><th>原件截止 / 草稿状态</th><th>核验记录</th></tr></thead><tbody>{(data?.results || []).map(row => <tr key={row.record_hash}>
      <td><strong>{row.company}</strong><span>{row.research_date}</span><code>{row.material_id} / {row.version}</code></td>
      <td>{row.industry_key}<code>{row.industry_taxonomy}</code><code>{row.taxonomy_version}</code></td>
      <td><code>{row.source_cutoff_at}</code>{badge(row.human_review)}<span>{row.assessments.join(' · ')}</span></td>
      <td><code>{row.report_sha256}</code><button className="icon-button" title="查看来源与校验记录" aria-label={`查看研究 ${row.company} ${row.research_date}`} disabled={view.stale} onClick={() => setSelected(row.record_hash)}><FileSearch size={17} /></button></td>
    </tr>)}</tbody></table>{!data?.results.length && <p className="shared-empty">{data?.status === 'EMPTY' || data?.total > 0 ? '无匹配研究' : data?.status === 'NOT_CONFIGURED' ? 'NOT_CONFIGURED' : view.error ? 'UNAVAILABLE' : 'WAIT'}</p>}</div>
    <div className="shared-pagination"><button className="icon-button" title="上一页研究" aria-label="上一页研究" disabled={!page} onClick={() => { setSelected(null); setPage(value => value - 1); }}><ChevronLeft size={17} /></button><span>{page + 1} / {Math.max(1, Math.ceil((data?.total || 0) / 50))}</span><button className="icon-button" title="下一页研究" aria-label="下一页研究" disabled={!data || (page + 1) * 50 >= data.total} onClick={() => { setSelected(null); setPage(value => value + 1); }}><ChevronRight size={17} /></button></div>
    {detail && <section className="research-metadata"><div className="section-title"><h4>{detail.company} · {detail.research_date}</h4><button className="icon-button" title="关闭核验记录" aria-label="关闭核验记录" onClick={() => setSelected(null)}><X size={17} /></button></div>
      <div className="source-strip">{badge(detail.human_review)}{badge(data.content_status)}{badge(detail.stored_verification)}</div>
      <dl className="input-card-fields">{[['研究日', detail.research_date], ['原件截止', detail.source_cutoff_at], ['产物生成时间', detail.artifact_generated_at], ['入库时间', detail.archived_at],
        ['任务执行版本', detail.consumer_execution_identity.code_sha], ['导入版本', detail.importer_execution_identity.code_sha], ['身份依据', detail.execution_attestation],
        ['输入包 hash', detail.pack_hash], ['产物 hash', detail.result_hash], ['报告 SHA256', detail.report_sha256], ['记录 hash', detail.record_hash]].map(([name,value]) => <React.Fragment key={name}><dt>{name}</dt><dd><code>{value}</code></dd></React.Fragment>)}</dl>
      <div className="table-scroll"><table><thead><tr><th>原件标识</th><th>发布日期 / 日期精度</th><th>首次捕获</th><th>文件 SHA256 / 来源核验</th></tr></thead><tbody>{detail.source_documents.map(doc => <tr key={doc.pdf_sha256}><td><code>{doc.material_id}</code><code>{doc.version}</code></td><td><code>{doc.published_at}</code><span>{doc.publication_precision?.basis || 'NOT_RECORDED'}</span></td><td><code>{doc.captured_at}</code></td><td><code>{doc.pdf_sha256}</code>{badge(doc.publisher_status)}</td></tr>)}</tbody></table></div>
    </section>}
  </div>;
}
