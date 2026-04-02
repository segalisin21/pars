import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { PageMeta, SuppressionRow } from '../lib/api'
import { DataTable } from '../components/DataTable'

export function SuppressionPage() {
  const [items, setItems] = useState<SuppressionRow[] | null>(null)
  const [page, setPage] = useState<PageMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [reason, setReason] = useState('')
  const [activeOnly, setActiveOnly] = useState(true)

  async function load(next?: { offset?: number }) {
    setErr(null)
    const offset = next?.offset ?? page?.offset ?? 0
    try {
      const res = await api.listSuppression({
        q: q.trim() || undefined,
        reason: reason.trim() || undefined,
        active_only: activeOnly,
        limit: 50,
        offset,
      })
      setItems(res.items)
      setPage(res.page)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load')
      setItems(null)
      setPage(null)
    }
  }

  useEffect(() => {
    void load({ offset: 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rows = items ?? []
  const columns = [
    { key: 'id', header: 'ID', className: 'mono', render: (s: SuppressionRow) => s.id },
    { key: 'tg', header: 'TG ID', className: 'mono', render: (s: SuppressionRow) => s.tg_user_id ?? '—' },
    { key: 'un', header: 'Username', className: 'mono', render: (s: SuppressionRow) => (s.username ? `@${s.username}` : '—') },
    { key: 'reason', header: 'Причина', className: 'mono small', render: (s: SuppressionRow) => s.reason },
    { key: 'until', header: 'До', className: 'mono small', render: (s: SuppressionRow) => s.until ?? '—' },
    { key: 'created', header: 'Создано', className: 'mono small', render: (s: SuppressionRow) => s.created_at },
  ]

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Подавления</h1>
        <div className="pageSub">Кого не трогаем (и почему).</div>
      </div>

      {err ? <div className="banner error">{err}</div> : null}

      <section className="card">
        <div className="cardTitle">Фильтры</div>
        <div className="toolbar">
          <label className="field grow">
            <div className="label">Поиск по username</div>
            <input placeholder="@username" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="field grow">
            <div className="label">Reason</div>
            <input placeholder="например privacy_restricted" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="field">
            <div className="label">Только активные</div>
            <select value={activeOnly ? 'yes' : 'no'} onChange={(e) => setActiveOnly(e.target.value === 'yes')}>
              <option value="yes">Да</option>
              <option value="no">Нет</option>
            </select>
          </label>
          <div className="toolbarRight">
            <button className="btn primary" onClick={() => void load({ offset: 0 })}>
              Применить
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Таблица</div>
        {items === null || page === null ? (
          <div className="muted">Загрузка…</div>
        ) : (
          <DataTable columns={columns} rows={rows} page={page} onPageChange={(p) => void load({ offset: p.offset })} />
        )}
      </section>
    </div>
  )
}

