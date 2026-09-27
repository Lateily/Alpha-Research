import React, { useEffect, useState } from 'react';
import { AlertTriangle, Download, FileCheck2, Play, RefreshCw, X } from 'lucide-react';

const PENDING_KEY = 'ar-jev-u4-shadow-pending';
const SCENARIO = 'synthetic-mixed';
const COMMAND_ID = /^[A-Za-z0-9_-]{8,80}$/;
const RECEIPT_SCHEMA = 'ar.jev_u4_shadow_receipt.v1';
const CHOICE_LABELS = ['SELECT_FOR_DEEP_RESEARCH', 'DEFER', 'REJECT', 'NO_TRADE', 'DATA_BLOCKED'];
const FILTERS = [
  ['ALL', '全部'],
  ['DETERMINISTIC_STOP', '确定性停门'],
  ['MODEL_UNAVAILABLE', '模型不可用'],
  ['HIGH_UNCERTAINTY', '高不确定性']
];
const GATE_LABELS = {
  ELIGIBLE_FOR_TYPED_JUDGMENT: '可供影子判断',
  FORCED_DATA_BLOCKED: 'U3 数据停门',
  FORCED_REJECT: 'E1 红旗拒绝',
  POLICY_STOPPED: '策略停门'
};

function readPending() {
  try {
    const value = JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null');
    return value && Object.keys(value).length === 2 && COMMAND_ID.test(value.command_id) &&
      value.scenario === SCENARIO ? value : null;
  } catch {
    return null;
  }
}

function isIntegrityError(error) {
  return /INTEGRITY_ERROR|integrity/i.test(String(error?.message || error?.status || ''));
}

function unwrapVerifiedResponse(value) {
  if (value?.status === 'INTEGRITY_ERROR') throw new Error('INTEGRITY_ERROR');
  const receipt = value?.receipt || value;
  if (receipt?.schema !== RECEIPT_SCHEMA || !receipt.identity || !receipt.source_binding?.run_identity ||
      !receipt.source_binding?.evidence_refs || !receipt.engine?.question_set ||
      !receipt.provider?.usage?.status || !receipt.batch_summary || !receipt.receipt_hash ||
      !Array.isArray(receipt.candidate_results) || !COMMAND_ID.test(receipt.identity.command_id) ||
      !receipt.candidate_results.every(row => row?.row_binding?.ticker &&
        row.row_binding.display_name && row.gate?.state && Array.isArray(row.gate.reason_codes) &&
        Array.isArray(row.state?.missing_evidence) && row.provider_result?.status &&
        (row.typed_answers === null || Array.isArray(row.typed_answers?.answers))) ||
      receipt.identity.sample_purpose !== 'WORKFLOW_DEBUG' ||
      receipt.provider.provider_contacted !== false || receipt.provider.network_policy !== 'deny' ||
      receipt.authority?.production_authority !== false ||
      receipt.authority?.trade_authority !== false ||
      receipt.authority?.paper_order_authority !== false ||
      receipt.authority?.formal_selection_authority !== false ||
      !['OFFLINE_FIXTURE', 'POLICY_PREVIEW'].includes(receipt.identity.run_mode)) {
    throw new Error('INTEGRITY_ERROR');
  }
  if (value?.evaluation != null) throw new Error('INTEGRITY_ERROR');
  return receipt;
}

function highUncertainty(row) {
  const observation = row.composer_observation;
  return !!observation && (
    Number(observation.top_choice_probability) < 0.6 ||
    Number(observation.top_two_margin) < 0.15 ||
    Number(observation.needs_human_review_probability) >= 0.5
  );
}

function gateTone(state) {
  if (state === 'FORCED_DATA_BLOCKED' || state === 'POLICY_STOPPED') return 'amber';
  if (state === 'FORCED_REJECT') return 'red';
  return 'green';
}

function HashLine({label, value}) {
  return <div className="jev-hash-line"><dt>{label}</dt><dd><code>{value || 'UNAVAILABLE'}</code></dd></div>;
}

export default function JevShadow({runs, api, busy, setBusy, setError, setNotice, onRunsChange, Badge, download}) {
  const [runSummaries, setRunSummaries] = useState(Array.isArray(runs) ? runs : []);
  const [selectedId, setSelectedId] = useState(() => Array.isArray(runs) ? runs[0]?.command_id || null : null);
  const [view, setView] = useState('EMPTY');
  const [receipt, setReceipt] = useState(null);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState('ALL');
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [pending, setPending] = useState(readPending);

  function updateRuns(next) {
    setRunSummaries(next);
    onRunsChange(next);
  }

  useEffect(() => {
    const next = Array.isArray(runs) ? runs : [];
    setRunSummaries(next);
    setSelectedId(current => current && next.some(row => row.command_id === current) ?
      current : next[0]?.command_id || null);
  }, [runs]);

  useEffect(() => {
    if (!selectedId) {
      setReceipt(null);
      setView('EMPTY');
      return;
    }
    const summary = runSummaries.find(row => row.command_id === selectedId);
    if (!COMMAND_ID.test(selectedId) || summary?.status === 'INTEGRITY_ERROR') {
      setReceipt(null);
      setView('INTEGRITY_ERROR');
      return;
    }
    let cancelled = false;
    setReceipt(null);
    setLoadError('');
    setView('LOADING');
    api(`/api/jev-u4-shadow/runs/${encodeURIComponent(selectedId)}`)
      .then(response => {
        const verified = unwrapVerifiedResponse(response);
        if (verified.identity.command_id !== selectedId) throw new Error('INTEGRITY_ERROR');
        const expectedStatus = verified.identity.run_mode === 'OFFLINE_FIXTURE' ? 'SIMULATED' : 'POLICY_PREVIEW';
        if (summary && ['SIMULATED', 'POLICY_PREVIEW'].includes(summary.status) && summary.status !== expectedStatus) {
          throw new Error('INTEGRITY_ERROR');
        }
        if (!cancelled) {
          setReceipt(verified);
          setSelectedTicker(null);
          setView('RECEIPT');
        }
      })
      .catch(error => {
        if (!cancelled) {
          setReceipt(null);
          setLoadError(error.message || '回执读取失败');
          setView(isIntegrityError(error) ? 'INTEGRITY_ERROR' : 'LOAD_ERROR');
        }
      });
    return () => { cancelled = true; };
  }, [selectedId, runSummaries, api]);

  async function runSynthetic() {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    setReceipt(null);
    setView('LOADING');
    const request = pending || {command_id: `jev_shadow_${crypto.randomUUID().replace(/-/g, '')}`, scenario: SCENARIO};
    try {
      sessionStorage.setItem(PENDING_KEY, JSON.stringify(request));
      setPending(request);
      const result = await api('/api/jev-u4-shadow/run', request);
      if (!['CREATED', 'IDEMPOTENT'].includes(result?.disposition) ||
          result?.display_mode !== 'SIMULATED' || result?.authority !== 'SHADOW_ONLY' ||
          result?.receipt?.identity?.command_id !== request.command_id ||
          result?.receipt?.identity?.run_mode !== 'OFFLINE_FIXTURE') {
        throw new Error('INTEGRITY_ERROR');
      }
      sessionStorage.removeItem(PENDING_KEY);
      setPending(null);
      const recorded = [
        {command_id: request.command_id, status: 'LOADING'},
        ...runSummaries.filter(row => row.command_id !== request.command_id)
      ];
      updateRuns(recorded);
      setSelectedId(request.command_id);
      setNotice(result.disposition === 'IDEMPOTENT' ? '已返回同一合成回执' : '合成 Shadow 演练已记录');
      try {
        const snapshot = await api('/api/state');
        if (Array.isArray(snapshot.jev_u4_shadow_runs)) updateRuns(snapshot.jev_u4_shadow_runs);
      } catch {
        // The exact receipt GET remains the display source even if the list refresh fails.
      }
    } catch (error) {
      setError(error.message || '合成演练请求未完成');
      setLoadError(error.message || '合成演练请求未完成');
      setView(isIntegrityError(error) ? 'INTEGRITY_ERROR' : 'LOAD_ERROR');
    } finally {
      setBusy(false);
    }
  }

  async function refreshRuns() {
    if (busy) return;
    setBusy(true);
    setError('');
    setReceipt(null);
    setView('LOADING');
    try {
      const snapshot = await api('/api/state');
      const next = Array.isArray(snapshot.jev_u4_shadow_runs) ? snapshot.jev_u4_shadow_runs : [];
      updateRuns(next);
      setSelectedId(current => current && next.some(row => row.command_id === current) ?
        current : next[0]?.command_id || null);
    } catch (error) {
      setLoadError(error.message || '运行记录读取失败');
      setView(isIntegrityError(error) ? 'INTEGRITY_ERROR' : 'LOAD_ERROR');
    } finally {
      setBusy(false);
    }
  }

  function abandonPending() {
    try { sessionStorage.removeItem(PENDING_KEY); } catch { /* no local storage to clear */ }
    setPending(null);
    setNotice('已结束本浏览器的待核重试；已有回执未被删除');
  }

  const candidates = receipt?.candidate_results || [];
  const visible = candidates.filter(row => {
    if (filter === 'DETERMINISTIC_STOP') return row.gate?.state !== 'ELIGIBLE_FOR_TYPED_JUDGMENT';
    if (filter === 'MODEL_UNAVAILABLE') return row.provider_result?.status === 'MODEL_UNAVAILABLE';
    if (filter === 'HIGH_UNCERTAINTY') return highUncertainty(row);
    return true;
  });
  const selected = visible.find(row => row.row_binding?.ticker === selectedTicker) || visible[0];
  const choice = selected?.typed_answers?.answers?.find(answer => answer.question_id === 'shadow_disposition')?.probabilities;
  const summary = receipt?.batch_summary;
  const source = receipt?.source_binding;
  const receiptStatus = receipt?.identity.run_mode === 'OFFLINE_FIXTURE' ? 'SIMULATED' : 'POLICY_PREVIEW';

  return <div className="jev-shadow">
    <section className="jev-launch"><div className="jev-launch-main"><div><div className="jev-boundary"><Badge tone="amber">模拟输入</Badge><Badge>SHADOW ONLY</Badge><span>模型调用 0 · 生产写入 0</span></div><h2>U4 影子模拟测试</h2><p>测试集：synthetic-mixed · WORKFLOW_DEBUG</p></div>
      <button className="primary jev-run-action" disabled={busy} onClick={runSynthetic}><Play size={18}/>{busy ? '正在核对运行' : pending ? '重试同一运行' : '运行模拟测试'}</button></div>
      <div className="jev-launch-footer"><span>{runSummaries.length} 条共享沙箱记录</span><div className="jev-launch-tools">{pending && <button disabled={busy} onClick={abandonPending}><X size={16}/>结束待核重试</button>}<button className="icon-button" disabled={busy} title="刷新模拟运行" aria-label="刷新模拟运行" onClick={refreshRuns}><RefreshCw size={16}/></button></div></div>
      {pending && <div className="jev-pending"><span>待核命令 ID</span><code>{pending.command_id}</code></div>}
    </section>
    {runSummaries.length > 0 && <section className="jev-run-picker"><label htmlFor="jev-run-select">运行记录</label><select id="jev-run-select" value={selectedId || ''} onChange={event => setSelectedId(event.target.value)}>{runSummaries.map(row => <option key={row.command_id} value={row.command_id}>{row.command_id} · {row.status || '待读取'}</option>)}</select></section>}

    {view === 'EMPTY' && <section className="empty jev-state" role="status"><FileCheck2 size={28}/><h3>尚无模拟回执</h3><span>点击上方“运行模拟测试”开始</span></section>}
    {view === 'LOADING' && <section className="empty jev-state" role="status"><RefreshCw size={28} className="spinning"/><h3>正在读取已验证回执</h3></section>}
    {view === 'INTEGRITY_ERROR' && <section className="empty jev-state jev-integrity" role="alert"><AlertTriangle size={28}/><h3>INTEGRITY_ERROR</h3><span>本地回执完整性校验失败；不显示历史结论</span></section>}
    {view === 'LOAD_ERROR' && <section className="empty jev-state" role="alert"><AlertTriangle size={28}/><h3>回执暂不可用</h3><span>{loadError}</span><button onClick={refreshRuns} disabled={busy}><RefreshCw size={16}/>重新读取</button></section>}

    {view === 'RECEIPT' && receipt && <>
      <section className="jev-receipt-head"><div className="section-title"><h2>运行结果</h2><div className="jev-result-actions"><Badge tone="green">回执已验证</Badge><Badge>{receiptStatus}</Badge><button className="icon-button" title="下载 Shadow 回执" aria-label="下载 Shadow 回执" onClick={() => download(`${receipt.identity.command_id}.json`, receipt)}><Download size={17}/></button></div></div>
        <div className="jev-facts"><div><span>数据日期</span><strong>{source.run_identity.as_of}</strong></div><div><span>输入性质</span><strong>{receipt.identity.run_mode === 'OFFLINE_FIXTURE' ? '固定合成输入' : '离线政策预览'}</strong></div><div><span>模型状态</span><strong>{receipt.provider.provider_contacted ? '已联系' : '未联系真实模型'}</strong></div><div><span>人工 U4</span><strong>未接入对照</strong></div></div>
      </section>
      <section><div className="section-title"><h2>结果概况</h2><span>{summary.total_candidates} 行 · 不形成正式选择</span></div><div className="jev-metrics">
        {[['可评估', summary.eligible_count], ['确定性停门', summary.forced_count], ['策略停门', summary.stopped_count], ['模型不可用', summary.unavailable_count], ['类型化判断', summary.typed_judgment_count]].map(([label, count]) => <div key={label}><span>{label}</span><strong>{count}</strong></div>)}
      </div></section>
      <section><div className="section-title"><h2>候选与门禁</h2><span>{visible.length} / {candidates.length} 行</span></div>
        <div className="jev-filters" role="group" aria-label="Shadow 候选筛选">{FILTERS.map(([key, label]) => <button key={key} className={filter === key ? 'active' : ''} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>)}</div>
        <div className="jev-filter-note">展示政策未验证 · 模型空白不是零分 · 人工 U4 对照未接入</div>
        <div className="table-scroll"><table className="jev-table"><thead><tr><th>候选</th><th>规则门禁</th><th>模型观察</th><th>缺失证据</th></tr></thead><tbody>{visible.map(row => {
          const ticker = row.row_binding.ticker;
          const observation = row.composer_observation;
          const missing = row.state?.missing_evidence || [];
          return <tr key={ticker} className={selected?.row_binding.ticker === ticker ? 'jev-selected' : ''}><td><button className="jev-candidate-button" aria-current={selected?.row_binding.ticker === ticker ? 'true' : undefined} onClick={() => setSelectedTicker(ticker)}><strong>{ticker}</strong><span>{row.row_binding.display_name}</span></button></td><td><Badge tone={gateTone(row.gate.state)}>{GATE_LABELS[row.gate.state] || row.gate.state}</Badge>{row.gate.forced_shadow_outcome && <small>{row.gate.forced_shadow_outcome}</small>}</td><td>{observation?.top_choice_label || row.provider_result.status}</td><td>{missing.length ? `${missing.length} 项待补` : '无列示缺口'}<small>{row.state?.source_publication?.daily_source_status || 'UNAVAILABLE'}</small></td></tr>;
        })}</tbody></table></div>
        {!visible.length && <div className="empty compact">当前筛选无候选行</div>}
      </section>

      {selected && <section className="jev-detail"><div className="section-title"><h2>{selected.row_binding.ticker} · {selected.row_binding.display_name}</h2><Badge tone={gateTone(selected.gate.state)}>{GATE_LABELS[selected.gate.state] || selected.gate.state}</Badge></div>
        <div className="jev-detail-grid"><div><h3>为什么停或继续</h3><div className="jev-detail-list"><span>门禁原因</span><p>{selected.gate.reason_codes.length ? selected.gate.reason_codes.join(' · ') : '无'}</p></div><div className="jev-detail-list"><span>缺失证据</span><p>{selected.state.missing_evidence.length ? selected.state.missing_evidence.join(' · ') : '无列示缺口'}</p></div><div className="jev-detail-list"><span>规则结果</span><p>{selected.gate.forced_shadow_outcome || selected.composer_observation?.shadow_outcome_state || selected.provider_result.status}</p></div></div>
          <div><h3>模型与人工</h3>{choice ? <div className="jev-probabilities">{CHOICE_LABELS.map(label => <div key={label}><span>{label}</span><div className="jev-prob-track"><span style={{width: `${Number(choice[label]) * 100}%`}}/></div><code>{choice[label]}</code></div>)}</div> : <p className="jev-muted">{selected.failure?.code || selected.provider_result.status} · 无类型化概率</p>}
            <div className="jev-detail-list"><span>提供者 / 网络 / 费用</span><p>{receipt.provider.name} · {receipt.provider.network_policy} · {receipt.provider.cost_cny} CNY</p></div><div className="jev-detail-list"><span>人工 U4 对照</span><p>未接入；不能计算一致率或分歧</p></div></div>
        </div><details className="jev-evidence"><summary>查看绑定哈希与技术回执</summary><dl className="jev-head-hashes"><HashLine label="Packet SHA256" value={source.packet_hash}/><HashLine label="Receipt SHA256" value={receipt.receipt_hash}/><HashLine label="U2 行" value={selected.row_binding.u2_candidate_row_hash}/><HashLine label="U3 行" value={selected.row_binding.u3_battery_row_hash}/><HashLine label="状态" value={selected.state_hash}/><HashLine label="Typed input" value={selected.provider_result.input_hash}/><HashLine label="Bundle" value={source.evidence_refs.same_day_bundle_hash}/><HashLine label="U2 pool" value={source.evidence_refs.u2_candidate_pool_hash}/><HashLine label="U3 battery" value={source.evidence_refs.u3_battery_hash}/><HashLine label="Packet 文件" value={source.packet_file_hash}/></dl><div className="jev-detail-list"><span>问题集 / 模型修订</span><p>{receipt.engine.question_set.version} · {receipt.provider.model_revision || '未调用'}</p></div></details>
      </section>}
    </>}
  </div>;
}
