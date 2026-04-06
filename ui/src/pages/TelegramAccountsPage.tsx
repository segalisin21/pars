import { useCallback, useEffect, useState } from 'react'
import { api, apiBaseUrl } from '../lib/api'
import type { TelegramAccount } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'

export function TelegramAccountsPage() {
  const [items, setItems] = useState<TelegramAccount[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [label, setLabel] = useState('')
  const [sessionString, setSessionString] = useState('')
  const [testBusyId, setTestBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await api.listTelegramAccounts()
      setItems(r.items)
    } catch (e) {
      setErr(formatApiError(e).message)
      setItems(null)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await api.createTelegramAccount({ label: label.trim(), session_string: sessionString.trim() })
      setLabel('')
      setSessionString('')
      await load()
    } catch (ex) {
      setErr(formatApiError(ex).message)
    } finally {
      setBusy(false)
    }
  }

  async function toggleEnabled(a: TelegramAccount) {
    setBusy(true)
    setErr(null)
    try {
      await api.patchTelegramAccount(a.id, { enabled: !a.enabled })
      await load()
    } catch (ex) {
      setErr(formatApiError(ex).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: number) {
    if (!window.confirm('Удалить аккаунт из системы?')) return
    setBusy(true)
    setErr(null)
    try {
      await api.deleteTelegramAccount(id)
      await load()
    } catch (ex) {
      setErr(formatApiError(ex).message)
    } finally {
      setBusy(false)
    }
  }

  async function test(id: number) {
    setTestBusyId(id)
    setErr(null)
    try {
      const r = await api.testTelegramAccount(id)
      if (!r.ok) {
        setErr(r.error || 'Проверка не прошла')
      } else {
        await load()
      }
    } catch (ex) {
      setErr(formatApiError(ex).message)
    } finally {
      setTestBusyId(null)
    }
  }

  return (
    <PageLayout
      title="Telegram аккаунты"
      subtitle="Глобальный пул сессий для worker (сбор, инвайт, мета). Сессии хранятся в БД в зашифрованном виде (APP_ENCRYPTION_KEY на сервере)."
    >
      {err ? (
        <UiBanner variant="error" title="Ошибка" onRetry={() => void load()}>
          {err}
          <div className="hint" style={{ marginTop: 8 }}>
            API: <code>{apiBaseUrl()}</code>, нужен <code>VITE_ADMIN_TOKEN</code> и <code>APP_ENCRYPTION_KEY</code> на бэкенде.
          </div>
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="cardTitle">Добавить аккаунт</div>
        <form onSubmit={onCreate} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <label className="field">
            <div className="label">Подпись</div>
            <input
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="например, аккаунт 1"
              maxLength={128}
            />
          </label>
          <label className="field">
            <div className="label">Session string (StringSession)</div>
            <textarea
              value={sessionString}
              onChange={(e) => setSessionString(e.target.value)}
              rows={3}
              placeholder="Вставьте строку сессии после входа (Telegram вход / Telethon)"
              required
            />
          </label>
          <button type="submit" className="btn primary" disabled={busy}>
            Сохранить
          </button>
        </form>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="cardTitle">Список</div>
        {items === null ? (
          <SkeletonBlock lines={4} />
        ) : items.length === 0 ? (
          <div className="muted">Записей пока нет.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {items.map((a) => (
              <div key={a.id} className="card" style={{ padding: '12px 14px' }}>
                <div>
                  <strong>{a.label || `#${a.id}`}</strong>{' '}
                  <span className={`badge ${a.enabled ? 'ok' : 'muted'}`}>{a.enabled ? 'вкл' : 'выкл'}</span>
                  {a.last_error_code ? <span className="badge err">{a.last_error_code}</span> : null}
                  <div className="mono small" style={{ marginTop: 6 }}>
                    id={a.id} · cooldown {a.cooldown_until ?? '—'}
                  </div>
                </div>
                <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                  <button type="button" className="btn" onClick={() => void test(a.id)} disabled={testBusyId === a.id || busy}>
                    {testBusyId === a.id ? 'Проверка…' : 'Проверить'}
                  </button>
                  <button type="button" className="btn" onClick={() => void toggleEnabled(a)} disabled={busy}>
                    {a.enabled ? 'Отключить' : 'Включить'}
                  </button>
                  <button type="button" className="btn danger" onClick={() => void remove(a.id)} disabled={busy}>
                    Удалить
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </PageLayout>
  )
}
