import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { PageMeta, SuppressionRow } from '../lib/api'
import { DataTable } from '../components/DataTable'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'
import { maskTelegramUserId } from '../lib/maskId'

export function SuppressionPage() {
  const [items, setItems] = useState<SuppressionRow[] | null>(null)
  const [page, setPage] = useState<PageMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [reason, setReason] = useState('')
  const [activeOnly, setActiveOnly] = useState(true)

  async function load(next?: { offset?: number }) {
    setErr(null)
    setErrCode(null)
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
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
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
    {
      key: 'tg',
      header: 'TG ID',
      className: 'mono',
      render: (s: SuppressionRow) => (s.tg_user_id != null ? maskTelegramUserId(s.tg_user_id) : '—'),
    },
    { key: 'un', header: 'Username', className: 'mono', render: (s: SuppressionRow) => (s.username ? `@${s.username}` : '—') },
    { key: 'reason', header: 'Причина', className: 'mono small', render: (s: SuppressionRow) => s.reason },
    { key: 'until', header: 'До', className: 'mono small', render: (s: SuppressionRow) => s.until ?? '—' },
    { key: 'created', header: 'Создано', className: 'mono small', render: (s: SuppressionRow) => s.created_at },
  ]

  return (
    <PageLayout title="Подавления" subtitle="Кого не трогаем (глобальный список).">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load({ offset: page?.offset ?? 0 })}>
          {err}
        </UiBanner>
      ) : null}

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
            <button type="button" className="btn primary" onClick={() => void load({ offset: 0 })}>
              Применить
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Таблица</div>
        {items === null || page === null ? (
          <SkeletonBlock lines={5} />
        ) : (
          <DataTable columns={columns} rows={rows} page={page} onPageChange={(p) => void load({ offset: p.offset })} />
        )}
      </section>
    </PageLayout>
  )
}
