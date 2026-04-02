import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Source } from '../lib/api'

export function SourcesPage() {
  const [items, setItems] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [type, setType] = useState<'group' | 'chat' | 'channel'>('group')
  const [identifier, setIdentifier] = useState('')
  const canSubmit = useMemo(() => identifier.trim().length > 0, [identifier])

  async function load() {
    setErr(null)
    try {
      const r = await api.listSources()
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
      await api.createSource({ type, identifier: identifier.trim(), enabled: true })
      setIdentifier('')
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  async function onToggle(src: Source) {
    setBusy(true)
    setErr(null)
    try {
      await api.patchSource(src.id, { enabled: !src.enabled })
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
        <h1>Источники</h1>
        <div className="pageSub">Чаты / группы / каналы, откуда собираем кандидатов.</div>
      </div>

      {err ? <div className="banner error">{err}</div> : null}

      <section className="card">
        <div className="cardTitle">Добавить источник</div>
        <div className="row">
          <label className="field">
            <div className="label">Тип</div>
            <select value={type} onChange={(e) => setType(e.target.value as any)} disabled={busy}>
              <option value="group">group</option>
              <option value="chat">chat</option>
              <option value="channel">channel</option>
            </select>
          </label>

          <label className="field grow">
            <div className="label">Идентификатор</div>
            <input
              placeholder="@публичное_имя или id"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              disabled={busy}
            />
          </label>

          <button className="btn primary" onClick={onCreate} disabled={busy || !canSubmit}>
            Добавить
          </button>
        </div>
        <div className="hint">
          Важно: операции записи требуют <code>VITE_ADMIN_TOKEN</code>, если на API установлен <code>ADMIN_TOKEN</code>.
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Список</div>
        {items === null ? (
          <div className="muted">Загрузка…</div>
        ) : items.length === 0 ? (
          <div className="muted">Источников пока нет. Добавьте первый источник.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Тип</th>
                <th>Идентификатор</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} className={s.enabled ? '' : 'disabled'}>
                  <td>{s.id}</td>
                  <td>{s.type}</td>
                  <td className="mono">@{s.identifier}</td>
                  <td>{s.enabled ? 'Включен' : 'Выключен'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn" onClick={() => void onToggle(s)} disabled={busy}>
                      {s.enabled ? 'Выключить' : 'Включить'}
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

