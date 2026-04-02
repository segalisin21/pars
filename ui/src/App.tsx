import { NavLink, Route, Routes } from 'react-router-dom'
import './App.css'

import { CollectPage } from './pages/CollectPage'
import { InvitePage } from './pages/InvitePage'
import { SourcesPage } from './pages/SourcesPage'
import { TargetsPage } from './pages/TargetsPage'

function App() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandTitle">Telegram Панель</div>
          <div className="brandSub">сбор и инвайтинг v1</div>
        </div>
        <nav className="nav">
          <NavLink to="/sources" className={({ isActive }) => (isActive ? 'navItem active' : 'navItem')}>
            Источники
          </NavLink>
          <NavLink to="/targets" className={({ isActive }) => (isActive ? 'navItem active' : 'navItem')}>
            Цели
          </NavLink>
          <NavLink to="/collect" className={({ isActive }) => (isActive ? 'navItem active' : 'navItem')}>
            Сбор
          </NavLink>
          <NavLink to="/invite" className={({ isActive }) => (isActive ? 'navItem active' : 'navItem')}>
            Инвайт
          </NavLink>
        </nav>
        <div className="sidebarFooter">
          <div className="hint">
            Укажите <code>VITE_API_BASE_URL</code> и при необходимости <code>VITE_ADMIN_TOKEN</code>.
          </div>
        </div>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<SourcesPage />} />
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/targets" element={<TargetsPage />} />
          <Route path="/collect" element={<CollectPage />} />
          <Route path="/invite" element={<InvitePage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
