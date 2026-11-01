import React, { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileText, RefreshCw, Search } from 'lucide-react';
import { createDataPoller, dataCenterView, dataContextKey, materialAvailability, readDataCenter } from './data-center-view.mjs';
import { statusTone } from './status-tone.mjs';

export default function DataCenter({ api, renew, login, snapshotId, parentStale, refreshRevision, onOpenJob }) {
  const [draft, setDraft] = useState({ industry_key: '', trade_date: '', ts_code: '' });
  const [filters, setFilters] = useState({}), [page, setPage] = useState(0), [allInputs, setAllInputs] = useState(false);
  const [inspected, setInspected] = useState(null), [state, setState] = useState(null);
  const poller = useRef(null), currentKey = useRef(null);
  const context = { login, snapshotId: inspected || snapshotId, filters, page, allInputs };
  const key = dataContextKey(context); currentKey.current = key;
  const view = dataCenterView(state, key, parentStale), card = view.data?.card, materials = view.data?.materials;
  const availability = materialAvailability(materials);
  useEffect(() => {
    const controller = createDataPoller({
      read: () => readDataCenter(api, context, renew),
      apply: data => { if (currentKey.current === key) setState({ key, data, stale: false, error: '', lastSuccessAt: Date.now() }); },
      fail: error => { if (currentKey.current === key) setState(previous => ({ key, data: previous?.key === key ? previous.data : null,
        stale: true, error: error.message, lastSuccessAt: previous?.lastSuccessAt })); }
    });
    poller.current = controller; controller.refresh();
    return () => controller.stop();
  }, [key]);
  useEffect(() => { poller.current?.refresh(); }, [refreshRevision]);
  function badge(value) { const shown = view.stale ? view.status : value || 'UNAVAILABLE'; return <span className={`badge ${statusTone(shown)}`}>{shown}</span>; }
  function submit(event) {
    event.preventDefault();
    setFilters({ ...draft, trade_date: draft.trade_date.replaceAll('-', '') }); setPage(0);
  }
  return <div className="data-center">
    <div className="section-title"><h3>输入与资料</h3><div>{badge(view.status)}<button className="icon-button" title="重新核验输入与资料" aria-label="刷新输入与资料" onClick={() => poller.current?.refresh()}><RefreshCw size={17} /></button></div></div>
    {view.error && <div className="shared-error" role="alert">{view.status} · {view.error}</div>}
    {view.stale && view.data && <div className="shared-error" role="status">DISCONNECTED · STALE</div>}
    <section className="input-card-section">
      <div className="section-title"><h4>输入卡</h4>{inspected && <button onClick={() => setInspected(null)}><RefreshCw size={15} />当前输入</button>}</div>
      {card ? <>
        <dl className="input-card-fields">{[['冻结输入', card.snapshot_id], ['输入 hash', card.input_hash], ['发布 run', card.source_run_id], ['来源交易日', card.source_trade_date],
          ['冻结时最新尝试', card.latest_attempt_identity?.run_id], ['执行版本', card.consumer_code_sha], ['验证范围', card.validation_scope], ['目录 hash', card.catalog_hash]].map(([label, value]) => <React.Fragment key={label}><dt>{label}</dt><dd><code>{value || 'UNBOUND'}</code></dd></React.Fragment>)}</dl>
        <div className="source-strip">{badge(card.governance_status)}{badge(card.instrumentation_status)}<span>人工核验 {card.human_review}</span><span>研究质量 {card.research_quality}</span></div>
        <div className="table-scroll"><table><thead><tr><th>模块</th><th>身份与数据状态</th><th>缺失字段</th></tr></thead><tbody>{card.modules.map(module => <tr key={module.module}><td>{module.module}</td><td>{badge(module.identity_status)} {badge(module.data_quality)}</td><td><code>{module.missing_fields.join(', ') || 'NONE'}</code></td></tr>)}</tbody></table></div>
        <details><summary>来源 hash 与封印依据</summary><div className="table-scroll"><table><thead><tr><th>来源</th><th>内容 hash</th><th>原始绑定</th><th>证据依据</th></tr></thead><tbody>{card.sources.map(source => <tr key={source.path}><td><code>{source.path}</code></td><td><code>{source.source_sha256 || 'UNBOUND'}</code></td><td>{badge(source.binding)}</td><td><code>{source.provenance?.basis || 'NOT_RECORDED'}</code>{source.provenance?.unread_catalog_paths?.map(path => <span className="text-red" key={path}>{path} · UNREAD</span>)}</td></tr>)}</tbody></table></div></details>
        <details><summary>数据缺口与补数计划</summary>{card.health ? <><div className="table-scroll"><table><thead><tr><th>来源</th><th>健康状态</th><th>记录范围</th></tr></thead><tbody>{Object.entries(card.health.sources).map(([id, source]) => <tr key={id}><td><code>{id}</code></td><td>{badge(source.status)}</td><td><code>{source.instrumentation}</code></td></tr>)}</tbody></table></div><pre>{JSON.stringify(card.backfill_plans, null, 2)}</pre></> : <p className="shared-empty">NOT_ATTACHED · NOT_INSTRUMENTED</p>}</details>
      </> : <p className="shared-empty">{view.error || (view.data ? 'NO_FROZEN_INPUT' : 'WAIT')}</p>}
    </section>
    <section className="material-section">
      <div className="section-title"><h4>资料查询</h4><label className="data-all-inputs"><input type="checkbox" checked={allInputs} onChange={event => { setAllInputs(event.target.checked); setPage(0); }} />全部已登记输入</label></div>
      <form className="material-filters" onSubmit={submit}>
        <label>行业<input value={draft.industry_key} maxLength={128} onChange={event => setDraft({ ...draft, industry_key: event.target.value })} /></label>
        <label>交易日<input type="date" value={draft.trade_date} onChange={event => setDraft({ ...draft, trade_date: event.target.value })} /></label>
        <label>股票代码<input value={draft.ts_code} maxLength={9} onChange={event => setDraft({ ...draft, ts_code: event.target.value.trim().toUpperCase() })} /></label>
        <button className="icon-button" title="查询资料" aria-label="查询资料" type="submit"><Search size={18} /></button>
      </form>
      <div className="source-strip"><span>{materials?.total ?? '—'} 项</span>{badge(materials ? availability.status : 'WAIT')}<code>{materials?.scope || 'NOT_EVALUATED'}</code></div>
      {availability.issues.map((issue, i) => <div className="shared-error" role="status" key={i}><code>{issue.trade_date || 'UNBOUND'} · {issue.snapshot_id}</code> · {issue.error}</div>)}
      <div className="table-scroll"><table><thead><tr><th>材料 / 日期</th><th>股票 / 行业</th><th>分类版本</th><th>hash / 核验</th><th>查看</th></tr></thead><tbody>{(materials?.rows || []).map(row => <tr key={row.material_id}>
        <td>{row.kind}<span>{row.trade_date}</span><code>{row.source_run_id}</code>{row.actor && <code>{row.actor}</code>}</td><td>{row.ts_code || '—'}<span>{row.industry_key || 'UNKNOWN_INDUSTRY'}</span></td>
        <td><code>{row.industry_taxonomy} / {row.industry_version}</code></td><td><code>{row.artifact_hash || 'UNBOUND'}</code>{badge(row.human_review)}</td>
        <td><button className="icon-button" title={row.job_id ? '查看封存简报' : '查看输入卡'} aria-label={row.job_id ? `查看简报 ${row.job_id}` : `查看输入 ${row.snapshot_id}`} disabled={view.stale} onClick={() => row.job_id ? onOpenJob(row.job_id) : setInspected(row.snapshot_id)}><FileText size={17} /></button></td>
      </tr>)}</tbody></table>{materials && !materials.rows.length && <p className="shared-empty">{availability.emptyLabel}</p>}</div>
      <div className="shared-pagination"><button className="icon-button" title="上一页资料" aria-label="上一页资料" disabled={!page} onClick={() => setPage(value => value - 1)}><ChevronLeft size={17} /></button><span>{page + 1} / {Math.max(1, Math.ceil((materials?.total || 0) / 50))}</span><button className="icon-button" title="下一页资料" aria-label="下一页资料" disabled={!materials || (page + 1) * 50 >= materials.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={17} /></button></div>
      <div className="source-strip"><span>未收录</span><code>{materials?.missing_material_types?.join(' · ') || 'NOT_EVALUATED'}</code></div>
    </section>
  </div>;
}
