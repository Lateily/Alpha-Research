import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Check, ChevronRight, Cloud, Database, Download, FileCheck2, KeyRound, Layers3, LockKeyhole, Play, RefreshCw, Save, Search, ShieldCheck, Users, X } from 'lucide-react';
import audit from './audit.json';
import './style.css';
const tabs = [['overview', '部署总览', Layers3], ['gateway', 'DeepSeek 入口', Activity], ['configuration', '部署草稿', Cloud], ['cutover', '迁移验收', FileCheck2], ['team', '团队权限', Users]];
const fieldLabels = {
  cloud_provider: '云厂商',
  account_id: '账号标识',
  region: '区域',
  monthly_budget: '基础设施月费用上限',
  currency: '预算币种',
  private_destination: '私有目的地（bucket / prefix）'
};
const gateLabels = ['账号、区域、预算与目的地批准', '全部旧写入者盘点（含第二台电脑）', '私有存储与登录身份核验', '非生产独立验收', '单独的切换批准', '停止旧调度、排空全部写入者', '一致备份、密钥扫描、哈希与恢复演练', '云端 canary、正式账本对账'];
async function api(path, body) {
  const result = await fetch(path, {
    method: body ? 'POST' : 'GET',
    credentials: 'same-origin',
    headers: body ? {
      'Content-Type': 'application/json'
    } : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const json = await result.json();
  if (!result.ok) throw new Error(json.error || `HTTP ${result.status}`);
  return json;
}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + '\n'], {
    type: 'application/json'
  }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Badge({
  children,
  tone = 'neutral'
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
function ReceiptDialog({
  receipt,
  close
}) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog className="modal" ref={ref} aria-label="离线回执" onCancel={close} onClick={event => {
    if (event.target === ref.current) {
      const bounds = ref.current.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close();
    }
  }}><div className="section-title"><h2>离线回执</h2><div className="actions"><button className="icon-button" title="下载回执" aria-label="下载回执" onClick={() => download(`${receipt.command_id}.json`, receipt)}><Download size={18} /></button><button className="icon-button" autoFocus title="关闭" aria-label="关闭回执" onClick={close}><X size={18} /></button></div></div><Badge tone="amber">SYNTHETIC · 非研究证据</Badge><pre>{JSON.stringify(receipt, null, 2)}</pre></dialog>;
}
function App() {
  const [tab, setTab] = useState('overview');
  const [state, setState] = useState(null);
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('ALL');
  const [fixture, setFixture] = useState('contract-smoke');
  const [pending, setPending] = useState(null);
  const [receipt, setReceipt] = useState(null);
  async function reload() {
    setError('');
    setBusy(true);
    try {
      const data = await api('/api/state');
      setState(data);
      setDraft(data.config);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    reload();
  }, []);
  async function probe() {
    setError('');
    setNotice('');
    setBusy(true);
    // Preserve the command ID across an uncertain HTTP result. Retrying cannot
    // create a second request; changing the fixture is disabled while pending.
    const request = pending || {
      command_id: `probe_${crypto.randomUUID()}`,
      provider: 'deepseek',
      mode: 'offline',
      fixture
    };
    setPending(request);
    try {
      const data = await api('/api/gateway/probe', request);
      setReceipt(data.receipt);
      setPending(null);
      setState(await api('/api/state'));
      setNotice(data.disposition === 'IDEMPOTENT' ? '重复请求已返回原回执' : '离线回执已记录');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function saveDraft(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api('/api/deployment-draft', {
        expected_revision: state.revision,
        config: draft
      });
      const data = await api('/api/state');
      setState(data);
      setDraft(data.config);
      setNotice('草稿已保存；审批状态未改变');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const items = audit.rows.filter(r => (filter === 'ALL' || r.state === filter) && `${r.surface} ${r.evidence} ${r.next}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon"><Layers3 size={22} /></div><div><strong>AR 工作台</strong><span>CONTROL PLANE</span></div></div>
      <div className="environment"><span className="dot" />非生产 · 本机</div>
      <nav aria-label="工作台导航">{tabs.map(([key, label, Icon]) => <button key={key} aria-current={tab === key ? 'page' : undefined} className={tab === key ? 'active' : ''} onClick={() => {
          setTab(key);
          setNotice('');
        }}><Icon size={18} />{label}<ChevronRight size={14} /></button>)}</nav>
      <div className="sidebar-footer"><ShieldCheck size={18} /><div>最终裁决：Junyan<span>未签发任何团队权限</span></div></div>
    </aside>
    <main>
      <header><div className="breadcrumb">AR / 部署准备 / <span>{tabs.find(t => t[0] === tab)[1]}</span></div><button className="icon-button" title="重新读取本地状态（会重载未保存草稿）" aria-label="刷新状态" disabled={busy} onClick={reload}><RefreshCw size={17} className={busy ? 'spinning' : ''} /></button></header>
      <div className="page">
        <div className="page-heading"><div><div className="eyebrow">WORKSPACE / 01</div><h1>{tabs.find(t => t[0] === tab)[1]}</h1></div><Badge tone="amber"><LockKeyhole size={13} />CUTOVER HOLD</Badge></div>
        <div className="authority-strip"><span><LockKeyhole size={14} />团队访问：关闭</span><span>模型付费调用：关闭</span><span>生产写入：关闭</span><span>会话：本机开发态，未认证人类身份</span></div>
        {error && <div role="alert" className="alert error"><X size={17} /><strong>请求未完成</strong><code>{error}</code><button onClick={reload} disabled={busy}>重载状态</button></div>}
        {notice && <div role="status" className="alert success"><Check size={16} />{notice}</div>}
        {!state ? <div className="empty" role="status"><Database size={30} /><h2>{error ? '本地服务不可用' : '正在读取工作台'}</h2><p>未显示任何缓存状态</p></div> : <>
          {tab === 'overview' && <>
            <div className="metrics"><article><span>本地离线回执</span><strong>{state.receipts.length}<small>条</small></strong><span>不是模型真实推理</span></article><article><span>本入口模型支出</span><strong>0<small>CNY</small></strong><span>未联系模型提供方</span></article><article><span>部署草稿待填</span><strong>{state.readiness.missing.length}<small>/ 6 项</small></strong><span>填写不等于批准</span></article><article><span>旧链切换状态</span><strong className="text-amber">HOLD</strong><span>旧写入尚未统一停止</span></article></div>
            <section><div className="section-title"><h2>部署面核对</h2><span>观察日期 {audit.observed_date} · 非实时健康状态</span></div>
              <div className="toolbar"><label className="search"><Search size={16} /><input aria-label="搜索部署面" placeholder="搜索入口或缺口" value={query} onChange={e => setQuery(e.target.value)} /></label><select aria-label="筛选核对状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="ALL">全部状态</option><option value="UNKNOWN">未核实</option><option value="HOLD">待处理</option><option value="OBSERVED">已观察</option></select><button className="icon-button" title="下载盘点快照" aria-label="下载盘点快照" onClick={() => download('deployment-observation.json', audit)}><Download size={17} /></button></div>
              <div className="table-scroll"><table><thead><tr><th>部署面</th><th>核对状态</th><th>已知证据</th><th>下一道验收</th></tr></thead><tbody>{items.map(row => <tr key={row.id}><td className="name">{row.surface}</td><td><Badge tone={row.state === 'HOLD' ? 'amber' : row.state === 'UNKNOWN' ? 'red' : 'neutral'}>{row.state === 'UNKNOWN' ? '未核实' : row.state === 'HOLD' ? '待处理' : '已观察'}</Badge></td><td>{row.evidence}</td><td>{row.next}</td></tr>)}</tbody></table></div>{!items.length && <div className="empty compact">没有匹配的部署面</div>}
            </section>
          </>}
          {tab === 'gateway' && <>
            <section className="gateway-status"><div className="provider-mark"><Activity size={30} /><div><h2>DeepSeek</h2><code>{state.policy.configured_model}</code></div></div><Badge>OFFLINE STUB</Badge><div className="key-status"><KeyRound size={17} />密钥未加载 · 实际模型版本：未调用</div></section>
            <section><div className="section-title"><h2>离线契约演练</h2><span>固定合成输入 · 0 网络 · 非研究证据</span></div><div className="probe-toolbar"><select aria-label="离线用例" value={fixture} disabled={busy || !!pending} onChange={e => setFixture(e.target.value)}><option value="contract-smoke">契约连通性</option><option value="evidence-missing">缺失证据 DATA_BLOCKED</option></select><button className="primary" disabled={busy} onClick={probe}><Play size={16} />{pending ? '重试同一请求' : '运行离线演练'}</button></div></section>
            <section><div className="section-title"><h2>请求回执</h2><span>{state.receipts.length} 条 · WORKFLOW_DEBUG</span></div>{state.receipts.length ? <div className="table-scroll"><table><thead><tr><th>请求 ID</th><th>用例</th><th>结果</th><th>费用</th><th>工件</th></tr></thead><tbody>{state.receipts.map(row => <tr key={row.command_id}><td><code>{row.command_id.slice(0, 18)}…</code></td><td>{row.fixture}</td><td><Badge tone={row.result === 'DATA_BLOCKED' ? 'amber' : 'green'}>{row.result}</Badge></td><td>0 CNY</td><td><button className="icon-button" aria-label={`查看回执 ${row.command_id}`} title="查看回执" onClick={() => setReceipt(row)}><FileCheck2 size={17} /></button></td></tr>)}</tbody></table></div> : <div className="empty"><FileCheck2 size={28} /><h3>尚无离线回执</h3><span>真实模型调用记录：0</span></div>}</section>
          </>}
          {tab === 'configuration' && <section><div className="section-title"><h2>云端部署草稿</h2><Badge>版本 {state.revision} · 未批准</Badge></div><form onSubmit={saveDraft} className="config-form">{Object.entries(fieldLabels).map(([key, label]) => <label key={key}><span>{label}</span>{key === 'currency' ? <select value={draft[key] || ''} onChange={e => setDraft({
                  ...draft,
                  [key]: e.target.value || null
                })}><option value="">待确认</option><option>CNY</option><option>USD</option></select> : <input maxLength={240} autoComplete="off" type="text" inputMode={key === 'monthly_budget' ? 'decimal' : 'text'} value={draft[key] || ''} placeholder={key === 'private_destination' ? 's3://bucket/private-prefix' : '待 Junyan 确认'} onChange={e => setDraft({
                  ...draft,
                  [key]: e.target.value || null
                })} />}</label>)}<div className="form-footer"><span>不接收密码、API key 或签名下载链接</span><button className="primary" type="submit" disabled={busy}><Save size={16} />保存草稿</button></div></form><div className="draft-state"><LockKeyhole size={18} /><div><strong>{state.readiness.status}</strong><p>云资源未创建 · 私有访问策略未验证 · 迁移未授权</p></div><button className="icon-button" title="下载配置草稿" aria-label="下载配置草稿" onClick={() => download('deployment-draft.json', {
                revision: state.revision,
                config: state.config,
                readiness: state.readiness
              })}><Download size={17} /></button></div></section>}
          {tab === 'cutover' && <section><div className="section-title"><h2>生产切换验收序列</h2><span>当前无执行权限</span></div><ol className="gate-list">{state.readiness.required_gates.map((gate, i) => <li key={gate}><span className="step-number">{String(i + 1).padStart(2, '0')}</span><div><h3>{gateLabels[i]}</h3><code>{gate}</code></div><Badge>待验收</Badge></li>)}</ol><div className="cutover-foot"><LockKeyhole size={18} /><span>备份前先停写。canary 前不开放正式账本写入方。失败不自动退回双写。</span></div></section>}
          {tab === 'team' && <section><div className="section-title"><h2>访问与操作权限</h2><Badge>0 个团队授权</Badge></div><div className="table-scroll"><table><thead><tr><th>主体</th><th>权限</th><th>身份状态</th></tr></thead><tbody><tr><td>本机浏览器会话</td><td>盘点查看、配置草稿、合成离线演练</td><td><Badge>开发会话，非人类身份认证</Badge></td></tr><tr><td>团队成员 / 第二台电脑</td><td>无远程访问、无角色授予</td><td><Badge tone="amber">DENY</Badge></td></tr><tr><td>模型 / Agent</td><td>无生产、费用、授权或交易权限</td><td><Badge tone="amber">DENY</Badge></td></tr><tr><td>Junyan</td><td>最终云账号、费用、成员与生产裁决</td><td><Badge>正式身份系统未接入</Badge></td></tr></tbody></table></div></section>}
        </>}
        <footer><span>AR / NONPRODUCTION WORKSPACE</span><span>不是买卖指令；研究信号，human executes.</span></footer>
      </div>
    </main>
    {receipt && <ReceiptDialog receipt={receipt} close={() => setReceipt(null)} />}
  </div>;
}
createRoot(document.getElementById('root')).render(<App />);
