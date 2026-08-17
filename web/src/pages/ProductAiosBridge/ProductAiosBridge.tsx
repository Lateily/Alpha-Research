import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import {
  BRIDGE_STATUSES,
  validateProductAiosBridgeFixtureSet,
  validateProductAiosBridgePacket,
  type BridgeStatus,
  type ProductAiosBridgePacket,
} from '../../contracts/productAiosBridge.ts'
import { theme } from '../../theme.ts'
import './ProductAiosBridge.css'

const journey = ['产品需求', 'AIOS Task', 'Agent 输出', '人工审核', '页面展示']

const statusLabels: Record<BridgeStatus, string> = {
  COMPLETE: '完整',
  PARTIAL: '部分',
  STALE: '陈旧',
  BLOCKED: '阻断',
  ERROR: '错误',
}

const bridgeVariables = {
  '--bridge-canvas': theme.colors.background.canvas,
  '--bridge-surface': theme.colors.background.surface,
  '--bridge-elevated': theme.colors.background.elevated,
  '--bridge-muted': theme.colors.background.muted,
  '--bridge-border': theme.colors.border.subtle,
  '--bridge-border-strong': theme.colors.border.strong,
  '--bridge-text': theme.colors.text.primary,
  '--bridge-text-secondary': theme.colors.text.secondary,
  '--bridge-text-muted': theme.colors.text.muted,
  '--bridge-amber': theme.colors.accent.amber,
  '--bridge-up': theme.colors.market.up,
  '--bridge-down': theme.colors.market.down,
  '--bridge-font': theme.typography.fontFamily.sans,
  '--bridge-mono': theme.typography.fontFamily.mono,
} as CSSProperties

function ValueList({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return (
    <section className="bridge-list">
      <h2>{title}</h2>
      {values.length > 0 ? (
        <ul>
          {values.map((value) => <li key={value}>{value}</li>)}
        </ul>
      ) : (
        <p className="bridge-empty">{empty}</p>
      )}
    </section>
  )
}

export default function ProductAiosBridgePage() {
  const [selectedStatus, setSelectedStatus] = useState<BridgeStatus>('COMPLETE')
  const [fixtures, setFixtures] = useState<Record<BridgeStatus, ProductAiosBridgePacket> | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    const fixtureUrl = `${import.meta.env.BASE_URL}data/v2/aios/product-aios-bridge-fixtures.v0.json`
    fetch(fixtureUrl, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP_${response.status}`)
        return response.json() as Promise<unknown>
      })
      .then((value) => {
        const result = validateProductAiosBridgeFixtureSet(value)
        if (!result.ok || !result.fixtures) throw new Error(result.errors.join(' · '))
        setFixtures(result.fixtures)
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return
        setLoadError(error instanceof Error ? error.message : 'UNKNOWN_LOAD_ERROR')
      })
    return () => controller.abort()
  }, [])

  const validation = useMemo(
    () => fixtures ? validateProductAiosBridgePacket(fixtures[selectedStatus]) : null,
    [fixtures, selectedStatus],
  )
  const packet = validation?.packet ?? null

  return (
    <main className="bridge-page" style={bridgeVariables}>
      <header className="bridge-header">
        <div>
          <a className="bridge-back" href="#/">AR Platform</a>
          <p className="bridge-eyebrow">PRODUCT OS / AIOS BRIDGE / SHADOW</p>
          <h1>AIOS 任务审核</h1>
        </div>
        <div className="bridge-header-meta">
          <span className="bridge-schema">product-aios-bridge.v0</span>
          <span className="bridge-offline">OFFLINE · ¥0</span>
        </div>
      </header>

      <nav className="bridge-status-tabs" aria-label="任务样例状态">
        {BRIDGE_STATUSES.map((status) => (
          <button
            aria-pressed={selectedStatus === status}
            className={selectedStatus === status ? `bridge-tab is-active tone-${status.toLowerCase()}` : 'bridge-tab'}
            key={status}
            onClick={() => setSelectedStatus(status)}
            type="button"
          >
            <span>{statusLabels[status]}</span>
            <strong>{status}</strong>
          </button>
        ))}
      </nav>

      {loadError ? (
        <section className="bridge-contract-error" role="alert">
          <strong>DATA_LOAD_ERROR</strong>
          <p>{loadError}</p>
        </section>
      ) : !fixtures ? (
        <section className="bridge-loading" aria-live="polite">
          <strong>LOADING</strong>
          <span>读取版本化任务投影</span>
        </section>
      ) : !packet ? (
        <section className="bridge-contract-error" role="alert">
          <strong>CONTRACT_BLOCKED</strong>
          <p>{validation?.errors.join(' · ')}</p>
        </section>
      ) : (
        <>
          <section className="bridge-journey" aria-label="Product AIOS 工作流">
            {journey.map((step, index) => (
              <div className="bridge-step" key={step}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{step}</strong>
              </div>
            ))}
          </section>

          <section className="bridge-summary-band">
            <div>
              <p className="bridge-eyebrow">{packet.task.task_id}</p>
              <h2>{packet.task.objective}</h2>
              <p>{packet.artifact.summary}</p>
            </div>
            <span className={`bridge-status tone-${packet.status.toLowerCase()}`}>{packet.status}</span>
          </section>

          <section className="bridge-metrics" aria-label="任务状态摘要">
            <div><span>Task</span><strong>{packet.task.state}</strong></div>
            <div><span>Run</span><strong>{packet.run.state}</strong></div>
            <div><span>Freshness</span><strong>{packet.freshness.status}</strong></div>
            <div><span>Human Review</span><strong>{packet.human_review.state}</strong></div>
            <div><span>Cost</span><strong>¥{packet.run.cost_cny}</strong></div>
          </section>

          <div className="bridge-grid">
            <section className="bridge-detail">
              <div className="bridge-section-heading">
                <p className="bridge-eyebrow">RUN CONTRACT</p>
                <h2>执行边界</h2>
              </div>
              <dl>
                <div><dt>Run ID</dt><dd>{packet.run.run_id}</dd></div>
                <div><dt>Executor</dt><dd>{packet.run.executor}</dd></div>
                <div><dt>Owner / Reviewer</dt><dd>{packet.task.human_owner} / {packet.task.reviewer}</dd></div>
                <div><dt>Mode / Network</dt><dd>{packet.run.mode} / {packet.run.network_policy}</dd></div>
                <div><dt>Data cutoff</dt><dd>{packet.freshness.data_cutoff}</dd></div>
              </dl>
            </section>

            <section className="bridge-detail">
              <div className="bridge-section-heading">
                <p className="bridge-eyebrow">HUMAN GATE</p>
                <h2>人工审核</h2>
              </div>
              <dl>
                <div><dt>Reviewer</dt><dd>{packet.human_review.reviewer ?? '尚未指定'}</dd></div>
                <div><dt>Decision ref</dt><dd>{packet.human_review.decision_ref ?? '尚无决定'}</dd></div>
                <div><dt>Final authority</dt><dd>{packet.human_review.final_merge_authority}</dd></div>
                <div><dt>Final merge</dt><dd>未授权</dd></div>
                <div><dt>Memory</dt><dd>{packet.memory_candidate.state} · 未晋升</dd></div>
              </dl>
            </section>
          </div>

          <div className="bridge-grid bridge-grid-lists">
            <ValueList title="证据" values={packet.artifact.evidence_refs} empty="没有可展示的证据" />
            <ValueList title="缺失证据" values={packet.artifact.missing_evidence} empty="未记录缺失项" />
            <ValueList title="阻断原因" values={packet.artifact.blocking_reasons} empty="没有阻断原因" />
            <ValueList title="警告" values={packet.artifact.warnings} empty="没有额外警告" />
          </div>

          <footer className="bridge-footer">
            <span>外部内容：{packet.artifact.external_content_trust}</span>
            <span>只展示证据，不构成买卖指令</span>
            <strong>no_trade_flag=true</strong>
          </footer>
        </>
      )}
    </main>
  )
}
