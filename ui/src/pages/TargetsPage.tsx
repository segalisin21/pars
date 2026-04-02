import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Target } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

export function TargetsPage() {
  const [items, setItems] = useState<Target[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [identifier, setIdentifier] = useState('')
  const [filter, setFilter] = useState('')
  const canSubmit = useMemo(() => identifier.trim().length > 0, [identifier])
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return items ?? []
    return (items ?? []).filter((x) => x.identifier.toLowerCase().includes(f) || String(x.id).includes(f))
  }, [items, filter])

  async function load() {
    setErr(null)
    setErrCode(null)
    try {
      const r = await api.listTargets()
      setItems(r.items)
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
      setItems(null)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function onCreate() {
    if (!canSubmit) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.createTarget({ identifier: identifier.trim(), enabled: true })
      setIdentifier('')
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function onToggle(t: Target) {
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.patchTarget(t.id, { enabled: !t.enabled })
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageLayout title="Цели" subtitle="Группы/чаты, куда приглашаем пользователей.">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load()}>
          {err}
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="cardTitle">Добавить цель</div>
        <div className="row">
          <label className="field grow">
            <div className="label">Идентификатор</div>
            <input
              placeholder="@целевая_группа"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              disabled={busy}
            />
          </label>
          <button type="button" className="btn primary" onClick={() => void onCreate()} disabled={busy || !canSubmit}>
            Добавить
          </button>
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Список</div>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <label className="field grow">
            <div className="label">Поиск</div>
            <input placeholder="id / username" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <div className="toolbarRight">
            <span className="badge">всего {items?.length ?? 0}</span>
            <span className="badge">показано {filtered.length}</span>
          </div>
        </div>
        {items === null ? (
          <SkeletonBlock lines={4} />
        ) : items.length === 0 ? (
          <EmptyState title="Целей пока нет" hint="Добавьте первую цель выше." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Идентификатор</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.id} className={t.enabled ? '' : 'disabled'}>
                  <td>{t.id}</td>
                  <td className="mono">@{t.identifier}</td>
                  <td>{t.enabled ? 'Включена' : 'Выключена'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button type="button" className="btn" onClick={() => void onToggle(t)} disabled={busy}>
                      {t.enabled ? 'Выключить' : 'Включить'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </PageLayout>
  )
}
