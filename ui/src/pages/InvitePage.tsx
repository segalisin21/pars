import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, apiBaseUrl } from '../lib/api'
import type { InviteRun, Target } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

function runIsActive(r: InviteRun): boolean {
  return r.status === 'queued' || r.status === 'running'
}

export function InvitePage() {
  const { runId: runIdParam } = useParams()
  const runId = runIdParam ? Number(runIdParam) : null

  const [targets, setTargets] = useState<Target[] | null>(null)
  const [runs, setRuns] = useState<InviteRun[] | null>(null)
  const [targetId, setTargetId] = useState<number | null>(null)
  const [focusedRun, setFocusedRun] = useState<InviteRun | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const didInitTarget = useRef(false)

  const enabledTargets = useMemo(() => (targets ?? []).filter((t) => t.enabled), [targets])
  const canStart = targetId !== null

  const load = useCallback(async () => {
    setErr(null)
    setErrCode(null)
    try {
      const [t, r] = await Promise.all([api.listTargets(), api.listInviteRuns()])
      setTargets(t.items)
      setRuns(r.items)
      if (!didInitTarget.current && t.items.length > 0) {
        didInitTarget.current = true
        const first = t.items.find((x) => x.enabled)
        setTargetId(first ? first.id : null)
      }
      if (runId !== null && !Number.isNaN(runId)) {
        try {
          const one = await api.getInviteRun(runId)
          setFocusedRun(one)
        } catch {
          setFocusedRun(null)
        }
      } else {
        setFocusedRun(null)
      }
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
      setTargets(null)
      setRuns(null)
    }
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

  const needsPoll = useMemo(() => (runs ?? []).some(runIsActive), [runs])
  const focusNeedsPoll = useMemo(() => (focusedRun ? runIsActive(focusedRun) : false), [focusedRun])

  useEffect(() => {
    if (!needsPoll && !focusNeedsPoll) return
    let cancelled = false
    let timeoutId: number
    const schedule = () => {
      const delayMs = document.hidden ? 15000 : 5000
      timeoutId = window.setTimeout(async () => {
        if (cancelled) return
        await load()
        if (!cancelled) schedule()
      }, delayMs)
    }
    const onVisibility = () => {
      window.clearTimeout(timeoutId)
      if (!document.hidden) void load()
      schedule()
    }
    document.addEventListener('visibilitychange', onVisibility)
    schedule()
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisibility)
      window.clearTimeout(timeoutId)
    }
  }, [needsPoll, focusNeedsPoll, load])

  async function start() {
    if (targetId === null) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.startInviteRun({
        target_id: targetId,
        policy: { max_per_minute: 2, max_per_hour: 30, cooldown_minutes: 0 },
      })
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  const netHint = err && err.toLowerCase().includes('failed to fetch')

  return (
    <PageLayout title="Инвайт" subtitle="Запуск приглашений и история с паузами (FloodWait, лимиты).">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load()}>
          {err}
          {netHint ? (
            <div className="hint" style={{ marginTop: 8 }}>
              Проверьте <code>VITE_API_BASE_URL</code> (сейчас: <code>{apiBaseUrl()}</code>) и CORS.
            </div>
          ) : null}
        </UiBanner>
      ) : null}

      {runId !== null && !Number.isNaN(runId) ? (
        <section className="card">
          <div className="cardTitle">Запуск #{runId}</div>
          {focusedRun ? (
            <>
              <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <span
                  className={
                    focusedRun.status === 'succeeded'
                      ? 'badge ok'
                      : focusedRun.status === 'failed'
                        ? 'badge err'
                        : focusedRun.status === 'paused'
                          ? 'badge warn'
                          : 'badge'
                  }
                >
                  {focusedRun.status}
                </span>
                {runIsActive(focusedRun) ? <span className="badge warn">обновление…</span> : null}
              </div>
              <div className="mono small" style={{ marginTop: 8 }}>
                Цель id: {focusedRun.target_id}
              </div>
              {(() => {
                const st = focusedRun.stats ?? {}
                const pr = st.pause_reason ? String(st.pause_reason) : null
                const fw = st.flood_wait_seconds != null ? String(st.flood_wait_seconds) : null
                return (
                  <>
                    {pr ? (
                      <div className="badge warn" style={{ marginTop: 8 }}>
                        {pr}
                        {fw ? ` · ${fw}s` : ''}
                      </div>
                    ) : null}
                  </>
                )
              })()}
            </>
          ) : (
            <div className="muted">Запуск не найден.</div>
          )}
          <div style={{ marginTop: 10 }}>
            <Link to="/invite" className="btn">
              Ко всем запускам
            </Link>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="cardTitle">Запуск инвайта</div>
        {targets === null ? (
          <SkeletonBlock lines={2} />
        ) : enabledTargets.length === 0 ? (
          <EmptyState title="Нет активных целей" hint="Создайте и включите цель на странице «Цели»." />
        ) : (
          <div className="row">
            <label className="field grow">
              <div className="label">Цель</div>
              <select
                value={targetId ?? ''}
                onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : null)}
                disabled={busy}
              >
                {enabledTargets.map((t) => (
                  <option key={t.id} value={t.id}>
                    #{t.id} @{t.identifier}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn primary" onClick={() => void start()} disabled={busy || !canStart}>
              {busy ? 'Запуск…' : 'Запустить инвайт'}
            </button>
          </div>
        )}
        <div className="hint" style={{ marginTop: 10 }}>
          Если статус <code>paused</code> — проверьте причину в таблице; при <code>flood_wait</code> подождите и запустите снова позже.
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs === null ? (
          <SkeletonBlock lines={4} />
        ) : runs.length === 0 ? (
          <EmptyState title="Запусков пока нет" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статус</th>
                <th>Цель</th>
                <th>Старт</th>
                <th>Итоги</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const s = r.stats ?? {}
                const pauseReason = s.pause_reason ? String(s.pause_reason) : null
                const active = runIsActive(r)
                return (
                  <tr key={r.id} className={r.status === 'paused' ? 'warn' : ''}>
                    <td className="mono">
                      <Link to={`/invite/${r.id}`}>{r.id}</Link>
                    </td>
                    <td>
                      <span
                        className={
                          r.status === 'succeeded'
                            ? 'badge ok'
                            : r.status === 'paused'
                              ? 'badge warn'
                              : r.status === 'failed'
                                ? 'badge err'
                                : 'badge'
                        }
                      >
                        {r.status}
                      </span>
                      {active ? <span className="badge warn">обновление</span> : null}
                      {pauseReason ? (
                        <span className="badge" style={{ marginLeft: 8 }}>
                          {pauseReason}
                        </span>
                      ) : null}
                    </td>
                    <td className="mono small">{r.target_id}</td>
                    <td className="mono small">{r.started_at}</td>
                    <td>
                      <div className="row" style={{ alignItems: 'center' }}>
                        <span className="badge">attempted {String(s.attempted ?? 0)}</span>
                        <span className="badge ok">success {String(s.success ?? 0)}</span>
                        <span className="badge">skipped {String(s.skipped ?? 0)}</span>
                        <span className="badge err">failed {String(s.failed ?? 0)}</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </PageLayout>
  )
}
