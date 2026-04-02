import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
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

      {err ? <div className="banner error">{err}</div> : null}

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
                <th>Статистика</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.status}</td>
                  <td className="mono">{r.source_ids.join(', ')}</td>
                  <td className="mono">{r.started_at}</td>
                  <td className="mono small">{JSON.stringify(r.stats)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

