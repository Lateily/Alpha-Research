import React from 'react'
import ReactDOM from 'react-dom/client'
import Dashboard from './Dashboard.jsx'
import AiosDeepSeekPage from './AiosDeepSeek.jsx'
import TeamProgressPage from './TeamProgress.jsx'

const pathname = window.location.pathname.replace(/\/$/, '')
const hashPath = window.location.hash.replace(/^#/, '').replace(/\/$/, '')
const isTeamProgressPage = pathname === '/team' || pathname.endsWith('/team') || hashPath === '/team'
const isAiosDeepSeekPage =
  pathname === '/aios/deepseek' ||
  pathname.endsWith('/aios/deepseek') ||
  hashPath === '/aios/deepseek'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isTeamProgressPage ? <TeamProgressPage /> : isAiosDeepSeekPage ? <AiosDeepSeekPage /> : <Dashboard />}
  </React.StrictMode>
)
