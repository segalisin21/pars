import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Target } from '../lib/api'

export function TargetsPage() {
  const [items, setItems] = useState<Target[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [identifier, setIdentifier] = useState('')
  const canSubmit = useMemo(() => identifier.trim().length > 0, [identifier])

  async function load() {
    setErr(null)
    try {
      const r = await api.listTargets()
      setItems(r.items)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load')
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
    try {
      await api.createTarget({ identifier: identifier.trim(), enabled: true })
      setIdentifier('')
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  async function onToggle(t: Target) {
    setBusy(true)
    setErr(null)
    try {
      await api.patchTarget(t.id, { enabled: !t.enabled })
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Цели</h1>
        <div className="pageSub">Группы/чаты, куда приглашаем пользователей.</div>
      </div>

      {err ? <div className="banner error">{err}</div> : null}

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
          <button className="btn primary" onClick={onCreate} disabled={busy || !canSubmit}>
            Добавить
          </button>
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Список</div>
        {items === null ? (
          <div className="muted">Загрузка…</div>
        ) : items.length === 0 ? (
          <div className="muted">Целей пока нет. Добавьте первую цель.</div>
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
              {items.map((t) => (
                <tr key={t.id} className={t.enabled ? '' : 'disabled'}>
                  <td>{t.id}</td>
                  <td className="mono">@{t.identifier}</td>
                  <td>{t.enabled ? 'Включена' : 'Выключена'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn" onClick={() => void onToggle(t)} disabled={busy}>
                      {t.enabled ? 'Выключить' : 'Включить'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

