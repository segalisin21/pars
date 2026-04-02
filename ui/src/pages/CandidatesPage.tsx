import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Candidate, PageMeta, Source } from '../lib/api'
import { DataTable } from '../components/DataTable'
import { Drawer } from '../components/Drawer'

function fmtUser(c: Candidate): string {
  if (c.username) return `@${c.username}`
  if (c.tg_user_id) return String(c.tg_user_id)
  return `#${c.id}`
}

export function CandidatesPage() {
  const [sources, setSources] = useState<Source[] | null>(null)
  const [items, setItems] = useState<Candidate[] | null>(null)
  const [page, setPage] = useState<PageMeta | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const [q, setQ] = useState('')
  const [sourceId, setSourceId] = useState<number | ''>('')
  const [hasTgId, setHasTgId] = useState<'all' | 'yes' | 'no'>('all')
  const [offset, setOffset] = useState(0)

  const [openId, setOpenId] = useState<number | null>(null)
  const [detail, setDetail] = useState<Candidate | null>(null)

  const has_tg_user_id = useMemo(() => {
    if (hasTgId === 'all') return undefined
    return hasTgId === 'yes'
  }, [hasTgId])

  async function load(next?: { offset?: number }) {
    const nextOffset = next?.offset ?? offset
    setErr(null)
    try {
      const [srcs, res] = await Promise.all([
        api.listSources(),
        api.listCandidates({
          q: q.trim() || undefined,
          source_id: sourceId === '' ? undefined : Number(sourceId),
          has_tg_user_id,
          limit: 50,
          offset: nextOffset,
        }),
      ])
      setSources(srcs.items)
      setItems(res.items)
      setPage(res.page)
      setOffset(nextOffset)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load')
      setSources(null)
      setItems(null)
      setPage(null)
    }
  }

  useEffect(() => {
    void load({ offset: 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function openCandidate(id: number) {
    setOpenId(id)
    setDetail(null)
    try {
      const r = await api.getCandidate(id)
      setDetail(r)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Не удалось загрузить детали')
    }
  }

  const rows = items ?? []
  const columns = [
    { key: 'id', header: 'ID', className: 'mono', render: (c: Candidate) => c.id },
    {
      key: 'user',
      header: 'Контакт',
      render: (c: Candidate) => (
        <button className="btn" onClick={() => void openCandidate(c.id)}>
          {fmtUser(c)}
        </button>
      ),
    },
    { key: 'name', header: 'Имя', render: (c: Candidate) => c.display_name ?? <span className="muted">—</span> },
    {
      key: 'sources',
      header: 'Источники',
      render: (c: Candidate) =>
        c.sources.length ? (
          <span className="mono small">{c.sources.map((s) => `#${s.id} @${s.identifier}`).join(', ')}</span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: 'seen', header: 'Последний раз', className: 'mono small', render: (c: Candidate) => c.last_seen_at },
  ]

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Контакты</h1>
        <div className="pageSub">Кандидаты из базы: кто сохранён и из каких источников.</div>
      </div>

      {err ? <div className="banner error">{err}</div> : null}

      <section className="card">
        <div className="cardTitle">Фильтры</div>
        <div className="toolbar">
          <label className="field grow">
            <div className="label">Поиск</div>
            <input placeholder="@username или имя" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="field">
            <div className="label">Источник</div>
            <select value={sourceId} onChange={(e) => setSourceId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Все</option>
              {(sources ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  #{s.id} @{s.identifier}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <div className="label">TG ID</div>
            <select value={hasTgId} onChange={(e) => setHasTgId(e.target.value as any)}>
              <option value="all">Все</option>
              <option value="yes">Есть</option>
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
          <DataTable
            columns={columns}
            rows={rows}
            page={page}
            onPageChange={(p) => void load({ offset: p.offset })}
            empty={<div className="muted">Контактов пока нет.</div>}
          />
        )}
      </section>

      <Drawer open={openId !== null} title={openId ? `Контакт ${openId}` : 'Контакт'} onClose={() => setOpenId(null)}>
        {!openId ? null : detail ? (
          <>
            <div className="row" style={{ alignItems: 'center' }}>
              <span className="badge ok">ID {detail.id}</span>
              <span className="badge">{fmtUser(detail)}</span>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="muted small">Имя</div>
              <div>{detail.display_name ?? <span className="muted">—</span>}</div>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="muted small">Источники</div>
              {detail.sources.length ? (
                <div className="mono small">{detail.sources.map((s) => `#${s.id} @${s.identifier}`).join('\n')}</div>
              ) : (
                <div className="muted">—</div>
              )}
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="muted small">First seen</div>
              <div className="mono small">{detail.first_seen_at}</div>
            </div>
            <div style={{ marginTop: 12 }}>
              <div className="muted small">Last seen</div>
              <div className="mono small">{detail.last_seen_at}</div>
            </div>
          </>
        ) : (
          <div className="muted">Загрузка…</div>
        )}
      </Drawer>
    </div>
  )
}

