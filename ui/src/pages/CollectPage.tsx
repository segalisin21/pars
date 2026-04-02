import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, apiBaseUrl } from '../lib/api'
import type { CollectRun, Source } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

function runIsActive(r: CollectRun): boolean {
  return r.status === 'queued' || r.status === 'running'
}

export function CollectPage() {
  const { runId: runIdParam } = useParams()
  const runId = runIdParam ? Number(runIdParam) : null

  const [sources, setSources] = useState<Source[] | null>(null)
  const [runs, setRuns] = useState<CollectRun[] | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [focusedRun, setFocusedRun] = useState<CollectRun | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const didInitSelection = useRef(false)

  const enabledSources = useMemo(() => (sources ?? []).filter((s) => s.enabled), [sources])
  const canStart = enabledSources.length > 0 && selectedIds.size > 0

  const load = useCallback(async () => {
    setErr(null)
    setErrCode(null)
    try {
      const [s, r] = await Promise.all([api.listSources(), api.listCollectRuns()])
      setSources(s.items)
      setRuns(r.items)
      if (!didInitSelection.current && s.items.length > 0) {
        didInitSelection.current = true
        setSelectedIds(new Set(s.items.filter((x) => x.enabled).map((x) => x.id)))
      }
      if (runId !== null && !Number.isNaN(runId)) {
        try {
          const one = await api.getCollectRun(runId)
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
      setSources(null)
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
    const t = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(t)
  }, [needsPoll, focusNeedsPoll, load])

  function toggle(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function start() {
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.startCollectRun({ source_ids: Array.from(selectedIds) })
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
    <PageLayout title="Сбор" subtitle="Запуск сбора кандидатов и история запусков.">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load()}>
          {err}
          {netHint ? (
            <div className="hint" style={{ marginTop: 8 }}>
              Проверьте <code>VITE_API_BASE_URL</code> (сейчас: <code>{apiBaseUrl()}</code>) и CORS: на API задайте <code>CORS_ALLOWED_ORIGINS</code> на URL этого UI.
            </div>
          ) : null}
        </UiBanner>
      ) : null}

      {runId !== null && !Number.isNaN(runId) ? (
        <section className="card">
          <div className="cardTitle">Запуск #{runId}</div>
          {focusedRun ? (
            <>
              <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                <span
                  className={
                    focusedRun.status === 'succeeded'
                      ? 'badge ok'
                      : focusedRun.status === 'failed'
                        ? 'badge err'
                        : 'badge'
                  }
                >
                  {focusedRun.status}
                </span>
                {runIsActive(focusedRun) ? <span className="badge warn">обновление…</span> : null}
              </div>
              <div className="mono small" style={{ marginTop: 8 }}>
                Источники: {focusedRun.source_ids.join(', ')}
              </div>
              <div className="mono small">Старт: {focusedRun.started_at}</div>
            </>
          ) : (
            <div className="muted">Запуск не найден или не загружен.</div>
          )}
          <div style={{ marginTop: 10 }}>
            <Link to="/collect" className="btn">
              Ко всем запускам
            </Link>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="cardTitle">Запуск сбора</div>
        {sources === null ? (
          <SkeletonBlock lines={2} />
        ) : enabledSources.length === 0 ? (
          <EmptyState title="Нет активных источников" hint="Включите хотя бы один источник на странице «Источники»." />
        ) : (
          <>
            <div className="chips">
              {enabledSources.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={selectedIds.has(s.id) ? 'chip selected' : 'chip'}
                  onClick={() => toggle(s.id)}
                  disabled={busy}
                  title={
                    [
                      s.telegram_title,
                      s.telegram_participants_count != null
                        ? `~${s.telegram_participants_count.toLocaleString()} подписчиков (из API; сбор может дать меньше)`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || `@${s.identifier}`
                  }
                >
                  <span>
                    #{s.id} @{s.identifier}
                  </span>
                  {s.telegram_title ? <span className="chipSub">{s.telegram_title}</span> : null}
                  {s.telegram_participants_count != null ? (
                    <span className="chipSub">~{s.telegram_participants_count.toLocaleString()} в канале</span>
                  ) : null}
                </button>
              ))}
            </div>
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button type="button" className="btn primary" onClick={() => void start()} disabled={busy || !canStart}>
                {busy ? 'Запуск…' : 'Запустить сбор'}
              </button>
            </div>
          </>
        )}
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs === null ? (
          <SkeletonBlock lines={4} />
        ) : runs.length === 0 ? (
          <EmptyState title="Запусков пока нет" hint="Стартуйте первый сбор выше." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статус</th>
                <th>Источники</th>
                <th>Старт</th>
                <th>Итоги</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const s = r.stats ?? {}
                const active = runIsActive(r)
                return (
                  <tr key={r.id}>
                    <td className="mono">
                      <Link to={`/collect/${r.id}`}>{r.id}</Link>
                    </td>
                    <td>
                      <span className={r.status === 'succeeded' ? 'badge ok' : r.status === 'failed' ? 'badge err' : 'badge'}>
                        {r.status}
                      </span>
                      {active ? <span className="badge warn">обновление</span> : null}
                    </td>
                    <td className="mono small">{r.source_ids.join(', ')}</td>
                    <td className="mono small">{r.started_at}</td>
                    <td>
                      <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap' }}>
                        <span className="badge">discovered {String(s.discovered_total ?? 0)}</span>
                        <span className="badge ok">new {String(s.new_candidates ?? 0)}</span>
                        <span className="badge">updated {String(s.updated_candidates ?? 0)}</span>
                      </div>
                      {s.by_source_id && typeof s.by_source_id === 'object' ? (
                        <div className="mono small muted" style={{ marginTop: 6 }}>
                          по источникам:{' '}
                          {Object.entries(s.by_source_id as Record<string, { discovered?: number; new_candidates?: number }>)
                            .map(([id, st]) => `#${id}: d${st.discovered ?? 0} n${st.new_candidates ?? 0}`)
                            .join(' · ')}
                        </div>
                      ) : null}
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
