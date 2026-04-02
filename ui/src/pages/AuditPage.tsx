import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { AuditEvent, PageMeta } from '../lib/api'
import { DataTable } from '../components/DataTable'

export function AuditPage() {
  const [items, setItems] = useState<AuditEvent[] | null>(null)
  const [page, setPage] = useState<PageMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [action, setAction] = useState('')
  const [entityType, setEntityType] = useState('')

  async function load(next?: { offset?: number }) {
    setErr(null)
    const offset = next?.offset ?? page?.offset ?? 0
    try {
      const res = await api.listAudit({
        action: action.trim() || undefined,
        entity_type: entityType.trim() || undefined,
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
    { key: 'id', header: 'ID', className: 'mono', render: (e: AuditEvent) => e.id },
    { key: 'ts', header: 'Время', className: 'mono small', render: (e: AuditEvent) => e.created_at },
    { key: 'action', header: 'Действие', className: 'mono', render: (e: AuditEvent) => e.action },
    { key: 'type', header: 'Сущность', className: 'mono', render: (e: AuditEvent) => e.entity_type },
    { key: 'eid', header: 'ID', className: 'mono', render: (e: AuditEvent) => e.entity_id ?? '—' },
    { key: 'meta', header: 'Meta', className: 'mono small', render: (e: AuditEvent) => JSON.stringify(e.meta) },
  ]

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Аудит</h1>
        <div className="pageSub">Действия оператора (создание/изменение, запуск runs).</div>
      </div>

      {err ? <div className="banner error">{err}</div> : null}

      <section className="card">
        <div className="cardTitle">Фильтры</div>
        <div className="toolbar">
          <label className="field grow">
            <div className="label">action</div>
            <input placeholder="например source.create" value={action} onChange={(e) => setAction(e.target.value)} />
          </label>
          <label className="field grow">
            <div className="label">entity_type</div>
            <input placeholder="например collect_run" value={entityType} onChange={(e) => setEntityType(e.target.value)} />
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

