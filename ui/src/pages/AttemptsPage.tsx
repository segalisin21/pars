import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { InviteAttempt, PageMeta } from '../lib/api'
import { DataTable } from '../components/DataTable'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'

export function AttemptsPage() {
  const [searchParams] = useSearchParams()
  const [items, setItems] = useState<InviteAttempt[] | null>(null)
  const [page, setPage] = useState<PageMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)

  const [inviteRunId, setInviteRunId] = useState(() => searchParams.get('invite_run_id') ?? '')
  const [candidateId, setCandidateId] = useState('')
  const [errorCode, setErrorCode] = useState('')

  async function load(next?: { offset?: number; inviteRunId?: string }) {
    setErr(null)
    setErrCode(null)
    const offset = next?.offset ?? page?.offset ?? 0
    const ir = (next?.inviteRunId ?? inviteRunId).trim()
    try {
      const res = await api.listInviteAttempts({
        invite_run_id: ir ? Number(ir) : undefined,
        candidate_id: candidateId.trim() ? Number(candidateId) : undefined,
        error_code: errorCode.trim() || undefined,
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
    const fromUrl = searchParams.get('invite_run_id') ?? ''
    setInviteRunId(fromUrl)
    void load({ offset: 0, inviteRunId: fromUrl })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  const rows = items ?? []
  const columns = [
    { key: 'id', header: 'ID', className: 'mono', render: (a: InviteAttempt) => a.id },
    { key: 'run', header: 'Run', className: 'mono', render: (a: InviteAttempt) => a.invite_run_id },
    { key: 'target', header: 'Target', className: 'mono', render: (a: InviteAttempt) => a.target_id },
    { key: 'cand', header: 'Candidate', className: 'mono', render: (a: InviteAttempt) => a.candidate_id },
    {
      key: 'status',
      header: 'Статус',
      render: (a: InviteAttempt) => {
        const cls = a.status === 'success' ? 'badge ok' : a.status === 'skipped' ? 'badge' : 'badge err'
        return <span className={cls}>{a.status}</span>
      },
    },
    { key: 'error', header: 'Ошибка', className: 'mono small', render: (a: InviteAttempt) => a.error_code ?? '—' },
    { key: 'ts', header: 'Время', className: 'mono small', render: (a: InviteAttempt) => a.attempted_at },
  ]

  return (
    <PageLayout title="Попытки" subtitle="История попыток инвайта по каждому контакту.">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load({ offset: page?.offset ?? 0 })}>
          {err}
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="cardTitle">Фильтры</div>
        <div className="toolbar">
          <label className="field">
            <div className="label">Invite run id</div>
            <input placeholder="например 12" value={inviteRunId} onChange={(e) => setInviteRunId(e.target.value)} />
          </label>
          <label className="field">
            <div className="label">Candidate id</div>
            <input placeholder="например 55" value={candidateId} onChange={(e) => setCandidateId(e.target.value)} />
          </label>
          <label className="field grow">
            <div className="label">error_code</div>
            <input placeholder="например flood_wait" value={errorCode} onChange={(e) => setErrorCode(e.target.value)} />
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
          <DataTable
            columns={columns}
            rows={rows}
            page={page}
            onPageChange={(p) => void load({ offset: p.offset })}
            empty={<div className="muted">Нет записей по фильтрам.</div>}
          />
        )}
      </section>
    </PageLayout>
  )
}
