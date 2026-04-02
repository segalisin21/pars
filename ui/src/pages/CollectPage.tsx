import { useEffect, useMemo, useState } from 'react'
import { api, apiBaseUrl } from '../lib/api'
import type { CollectRun, Source } from '../lib/api'

export function CollectPage() {
  const [sources, setSources] = useState<Source[] | null>(null)
  const [runs, setRuns] = useState<CollectRun[] | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const enabledSources = useMemo(() => (sources ?? []).filter((s) => s.enabled), [sources])
  const canStart = enabledSources.length > 0 && selectedIds.size > 0

  async function load() {
    setErr(null)
    try {
      const [s, r] = await Promise.all([api.listSources(), api.listCollectRuns()])
      setSources(s.items)
      setRuns(r.items)
      // default select all enabled sources on first load
      if (selectedIds.size === 0) {
        setSelectedIds(new Set(s.items.filter((x) => x.enabled).map((x) => x.id)))
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load')
      setSources(null)
      setRuns(null)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    try {
      await api.startCollectRun({ source_ids: Array.from(selectedIds) })
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Start failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Сбор</h1>
        <div className="pageSub">Запуск сбора и история запусков.</div>
      </div>

      {err ? (
        <div className="banner error">
          {err}
          {err.toLowerCase().includes('failed to fetch') ? (
            <div className="hint" style={{ marginTop: 8 }}>
              Не удалось достучаться до API. Проверьте: <code>VITE_API_BASE_URL</code> (сейчас: <code>{apiBaseUrl()}</code>) и
              CORS (<code>CORS_ALLOWED_ORIGINS</code> на API = URL UI).
            </div>
          ) : null}
        </div>
      ) : null}

      <section className="card">
        <div className="cardTitle">Запуск сбора</div>
        {sources === null ? (
          <div className="muted">Загрузка…</div>
        ) : enabledSources.length === 0 ? (
          <div className="muted">Сначала включите хотя бы один источник.</div>
        ) : (
          <>
            <div className="chips">
              {enabledSources.map((s) => (
                <button
                  key={s.id}
                  className={selectedIds.has(s.id) ? 'chip selected' : 'chip'}
                  onClick={() => toggle(s.id)}
                  disabled={busy}
                  title={`@${s.identifier}`}
                >
                  #{s.id} @{s.identifier}
                </button>
              ))}
            </div>
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button className="btn primary" onClick={start} disabled={busy || !canStart}>
                Запустить сбор
              </button>
            </div>
          </>
        )}
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs === null ? (
          <div className="muted">Загрузка…</div>
        ) : runs.length === 0 ? (
          <div className="muted">Запусков пока нет.</div>
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
                const s: any = r.stats ?? {}
                return (
                  <tr key={r.id}>
                    <td className="mono">{r.id}</td>
                    <td>
                      <span className={r.status === 'succeeded' ? 'badge ok' : r.status === 'failed' ? 'badge err' : 'badge'}>
                        {r.status}
                      </span>
                    </td>
                    <td className="mono small">{r.source_ids.join(', ')}</td>
                    <td className="mono small">{r.started_at}</td>
                    <td>
                      <div className="row" style={{ alignItems: 'center' }}>
                        <span className="badge">discovered {s.discovered_total ?? 0}</span>
                        <span className="badge ok">new {s.new_candidates ?? 0}</span>
                        <span className="badge">updated {s.updated_candidates ?? 0}</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

