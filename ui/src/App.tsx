import { lazy, Suspense, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import './App.css'

import { SkeletonBlock } from './components/SkeletonBlock'
import { useApiHealth } from './hooks/useApiHealth'
import { apiBaseUrl } from './lib/api'

const SourcesPage = lazy(() => import('./pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const TargetsPage = lazy(() => import('./pages/TargetsPage').then((m) => ({ default: m.TargetsPage })))
const CollectPage = lazy(() => import('./pages/CollectPage').then((m) => ({ default: m.CollectPage })))
const InvitePage = lazy(() => import('./pages/InvitePage').then((m) => ({ default: m.InvitePage })))
const BroadcastPage = lazy(() => import('./pages/BroadcastPage').then((m) => ({ default: m.BroadcastPage })))
const TargetingPage = lazy(() => import('./pages/TargetingPage').then((m) => ({ default: m.TargetingPage })))
const CandidatesPage = lazy(() => import('./pages/CandidatesPage').then((m) => ({ default: m.CandidatesPage })))
const AttemptsPage = lazy(() => import('./pages/AttemptsPage').then((m) => ({ default: m.AttemptsPage })))
const SuppressionPage = lazy(() => import('./pages/SuppressionPage').then((m) => ({ default: m.SuppressionPage })))
const AuditPage = lazy(() => import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })))
const TelegramAuthPage = lazy(() => import('./pages/TelegramAuthPage').then((m) => ({ default: m.TelegramAuthPage })))
const TelegramAccountsPage = lazy(() =>
  import('./pages/TelegramAccountsPage').then((m) => ({ default: m.TelegramAccountsPage })),
)
const TelegramAccountsStatusPage = lazy(() =>
  import('./pages/TelegramAccountsStatusPage').then((m) => ({ default: m.TelegramAccountsStatusPage })),
)

function RouteFallback() {
  return (
    <div className="pageFallback">
      <SkeletonBlock lines={5} />
    </div>
  )
}

function NavBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <div className="navSectionLabel">{label}</div>
      <nav className="nav">{children}</nav>
    </>
  )
}

function ShellNavLinks({ onNavigate }: { onNavigate: () => void }) {
  const linkCls = ({ isActive }: { isActive: boolean }) => (isActive ? 'navItem active' : 'navItem')
  return (
    <>
      <NavBlock label="Конфигурация">
        <NavLink to="/sources" className={linkCls} onClick={onNavigate}>
          Источники
        </NavLink>
        <NavLink to="/targets" className={linkCls} onClick={onNavigate}>
          Цели
        </NavLink>
      </NavBlock>
      <NavBlock label="Операции">
        <NavLink to="/collect" className={linkCls} onClick={onNavigate}>
          Сбор
        </NavLink>
        <NavLink to="/invite" className={linkCls} onClick={onNavigate}>
          Инвайт
        </NavLink>
        <NavLink to="/targeting" className={linkCls} onClick={onNavigate}>
          Таргетинг
        </NavLink>
        <NavLink to="/broadcast" className={linkCls} onClick={onNavigate}>
          Рассылка
        </NavLink>
      </NavBlock>
      <NavBlock label="Данные">
        <NavLink to="/candidates" className={linkCls} onClick={onNavigate}>
          Контакты
        </NavLink>
        <NavLink to="/attempts" className={linkCls} onClick={onNavigate}>
          Попытки
        </NavLink>
        <NavLink to="/suppression" className={linkCls} onClick={onNavigate}>
          Подавления
        </NavLink>
      </NavBlock>
      <NavBlock label="Система">
        <NavLink to="/audit" className={linkCls} onClick={onNavigate}>
          Аудит
        </NavLink>
        <NavLink to="/telegram-accounts" className={linkCls} onClick={onNavigate}>
          Telegram аккаунты
        </NavLink>
        <NavLink to="/telegram-accounts/status" className={linkCls} onClick={onNavigate}>
          Telegram статусы
        </NavLink>
      </NavBlock>
    </>
  )
}

function HealthDot({ health }: { health: ReturnType<typeof useApiHealth> }) {
  const cls = health === 'ok' ? 'apiHealthDot ok' : health === 'error' ? 'apiHealthDot err' : 'apiHealthDot'
  const label = health === 'ok' ? 'API' : health === 'error' ? 'Нет связи' : '…'
  return (
    <div className="apiHealth" title={`${label} · ${apiBaseUrl()}`}>
      <span className={cls} />
      <span>{label}</span>
    </div>
  )
}

function App() {
  const [navOpen, setNavOpen] = useState(false)
  const health = useApiHealth()

  const closeNav = () => setNavOpen(false)

  return (
    <div className="shell">
      <div className="mobileTop">
        <button type="button" className="mobileMenuBtn" onClick={() => setNavOpen(true)} aria-label="Открыть меню">
          Меню
        </button>
        <div className="mobileTopTitle">Telegram панель</div>
        <HealthDot health={health} />
      </div>

      {navOpen ? <button type="button" className="sidebarBackdrop" onClick={closeNav} aria-label="Закрыть меню" /> : null}

      <aside className={`sidebar ${navOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="brandTitle">Telegram панель</div>
          <div className="brandSub">сбор и инвайтинг</div>
        </div>
        <HealthDot health={health} />
        <ShellNavLinks onNavigate={closeNav} />
        <div className="sidebarFooter">
          <div className="hint">
            <code>VITE_API_BASE_URL</code>
            {import.meta.env.VITE_ADMIN_TOKEN ? (
              <>
                {' '}
                · токен задан
              </>
            ) : (
              <>
                {' '}
                · без <code>VITE_ADMIN_TOKEN</code> запись может не пройти
              </>
            )}
          </div>
        </div>
      </aside>

      <main className="main">
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<SourcesPage />} />
            <Route path="/sources" element={<SourcesPage />} />
            <Route path="/targets" element={<TargetsPage />} />
            <Route path="/collect" element={<CollectPage />} />
            <Route path="/collect/:runId" element={<CollectPage />} />
            <Route path="/invite" element={<InvitePage />} />
            <Route path="/invite/:runId" element={<InvitePage />} />
            <Route path="/targeting" element={<TargetingPage />} />
            <Route path="/broadcast" element={<BroadcastPage />} />
            <Route path="/broadcast/:runId" element={<BroadcastPage />} />
            <Route path="/candidates" element={<CandidatesPage />} />
            <Route path="/attempts" element={<AttemptsPage />} />
            <Route path="/suppression" element={<SuppressionPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/telegram-accounts" element={<TelegramAccountsPage />} />
            <Route path="/telegram-accounts/status" element={<TelegramAccountsStatusPage />} />
            <Route path="/telegram-auth" element={<TelegramAuthPage />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}

export default App
