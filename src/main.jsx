import React from 'react'
import ReactDOM from 'react-dom/client'
import Dashboard from './Dashboard.jsx'
import AiosDeepSeekPage from './AiosDeepSeek.jsx'
import TeamProgressPage from './TeamProgress.jsx'

const pathname = window.location.pathname.replace(/\/$/, '')
const isTeamProgressPage = pathname === '/team' || pathname.endsWith('/team')
const isAiosDeepSeekPage = pathname === '/aios/deepseek' || pathname.endsWith('/aios/deepseek')

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isTeamProgressPage ? <TeamProgressPage /> : isAiosDeepSeekPage ? <AiosDeepSeekPage /> : <Dashboard />}
  </React.StrictMode>
)
