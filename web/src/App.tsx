import { useEffect, useState, type CSSProperties } from 'react'
import './App.css'
import ProductAiosBridgePage from './pages/ProductAiosBridge/ProductAiosBridge.tsx'
import { theme } from './theme'

const pages = [
  { id: 'model', label: '模型组合', question: '模型今天处于什么状态？' },
  { id: 'trades', label: '交易组合', question: '每一笔交易为什么执行？' },
  { id: 'premarket', label: '盘前帧', question: '开盘前，世界发生了什么？' },
  { id: 'rotation', label: '轮动面板', question: '资金正在往哪里移动？' },
  { id: 'macro', label: '宏观面板', question: '哪些宏观事件值得关注？' },
  { id: 'weekly', label: '周报复盘', question: '这周系统学到了什么？' },
  { id: 'charts', label: '图表工作台', question: '价格结构正在表达什么？' },
] as const

const palette = [
  { label: '画布背景', value: theme.colors.background.canvas },
  { label: '卡片表面', value: theme.colors.background.surface },
  { label: '抬升表面', value: theme.colors.background.elevated },
  { label: '琥珀强调', value: theme.colors.accent.amber },
  { label: '上涨', value: theme.colors.market.up },
  { label: '下跌', value: theme.colors.market.down },
] as const

const cssVariables = {
  '--color-canvas': theme.colors.background.canvas,
  '--color-surface': theme.colors.background.surface,
  '--color-elevated': theme.colors.background.elevated,
  '--color-muted-surface': theme.colors.background.muted,
  '--color-border': theme.colors.border.subtle,
  '--color-border-strong': theme.colors.border.strong,
  '--color-text': theme.colors.text.primary,
  '--color-text-secondary': theme.colors.text.secondary,
  '--color-text-muted': theme.colors.text.muted,
  '--color-amber': theme.colors.accent.amber,
  '--color-amber-soft': theme.colors.accent.amberSoft,
  '--color-market-up': theme.colors.market.up,
  '--color-market-down': theme.colors.market.down,
  '--font-sans': theme.typography.fontFamily.sans,
  '--font-mono': theme.typography.fontFamily.mono,
} as CSSProperties

function App() {
  const [activePage, setActivePage] = useState<(typeof pages)[number]['id']>('model')
  const [hashPath, setHashPath] = useState(window.location.hash || '#/')
  const currentPage = pages.find((page) => page.id === activePage) ?? pages[0]

  useEffect(() => {
    const onHashChange = () => setHashPath(window.location.hash || '#/')
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  if (hashPath === '#/aios/bridge') {
    return <ProductAiosBridgePage />
  }

  return (
    <div className="app-shell" style={cssVariables}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">AR</span>
          <div>
            <strong>Alpha Research</strong>
            <span>M0 · PLATFORM SHELL</span>
          </div>
        </div>

        <nav className="page-nav" aria-label="平台页面">
          <span className="nav-label">七个页面</span>
          {pages.map((page, index) => (
            <button
              className={page.id === activePage ? 'nav-item nav-item--active' : 'nav-item'}
              key={page.id}
              onClick={() => setActivePage(page.id)}
              type="button"
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              {page.label}
            </button>
          ))}
        </nav>

        <a className="bridge-nav-link" href="#/aios/bridge">
          <span>AI</span>
          AIOS 任务审核
        </a>

        <p className="evidence-note">只展示研究证据与信号 · human executes</p>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">ISSUE #158 · M0 DESIGN FOUNDATION</span>
            <h1>前端脚手架与设计地基</h1>
          </div>
          <span className="status-pill">SCAFFOLD ONLINE</span>
        </header>

        <section className="hero-card">
          <span className="section-kicker">CURRENT SHELL</span>
          <h2>{currentPage.label}</h2>
          <p>{currentPage.question}</p>
          <div className="data-blocked">
            <span>DATA_BLOCKED</span>
            等待 v2 JSON 契约接入
          </div>
        </section>

        <section className="token-section">
          <div className="section-heading">
            <div>
              <span className="section-kicker">DESIGN TOKENS</span>
              <h2>统一色板</h2>
            </div>
            <code>web/src/theme.ts</code>
          </div>

          <div className="palette-grid">
            {palette.map((token) => (
              <article className="swatch-card" key={token.label}>
                <div className="swatch" style={{ backgroundColor: token.value }} />
                <strong>{token.label}</strong>
                <code>{token.value}</code>
              </article>
            ))}
          </div>
        </section>

        <section className="type-sample">
          <div>
            <span className="section-kicker">TYPOGRAPHY</span>
            <h2>数字使用等宽字体</h2>
          </div>
          <div className="market-sample">
            <span className="market-up">+12.48%</span>
            <span className="market-down">-3.16%</span>
            <span>13:45:09 HKT</span>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
