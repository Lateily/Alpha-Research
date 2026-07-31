import React from 'react'
import ReactDOM from 'react-dom/client'
import Dashboard from './Dashboard.jsx'
import TeamProgressPage from './TeamProgress.jsx'

const pathname = window.location.pathname.replace(/\/$/, '')
const isTeamProgressPage = pathname === '/team' || pathname.endsWith('/team')

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isTeamProgressPage ? <TeamProgressPage /> : <Dashboard />}
  </React.StrictMode>
)
