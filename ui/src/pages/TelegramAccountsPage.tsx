import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, apiBaseUrl } from '../lib/api'
import type { TelegramAccount } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'

export function TelegramAccountsPage() {
  // App credentials
  const [credsConfigured, setCredsConfigured] = useState<boolean | null>(null)
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')

  // Login flow -> session string
  const [phone, setPhone] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [needsPassword, setNeedsPassword] = useState(false)
  const [generatedSessionString, setGeneratedSessionString] = useState<string | null>(null)

  const [items, setItems] = useState<TelegramAccount[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [label, setLabel] = useState('')
  const [sessionString, setSessionString] = useState('')
  const [testBusyId, setTestBusyId] = useState<number | null>(null)

  const canRequest = useMemo(() => phone.trim().length >= 5, [phone])
  const canVerify = useMemo(() => !!token && code.trim().length >= 3, [token, code])

  async function loadCreds() {
    try {
      const r = await api.getTelegramAppCredentials()
      setCredsConfigured(Boolean(r.configured))
      setApiId(r.api_id ? String(r.api_id) : '')
    } catch (e) {
      // Don't block the rest of the page if credentials endpoint fails
      setCredsConfigured(null)
    }
  }

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
    void loadCreds()
  }, [load])

  async function saveCreds(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await api.putTelegramAppCredentials({ api_id: Number(apiId), api_hash: apiHash.trim() })
      setApiHash('')
      await loadCreds()
    } catch (ex) {
      setErr(formatApiError(ex).message)
    } finally {
      setBusy(false)
    }
  }

  async function requestCode() {
    setBusy(true)
    setErr(null)
    setGeneratedSessionString(null)
    setNeedsPassword(false)
    try {
      const r = await api.telegramRequestCode({ phone: phone.trim() })
      if (r.error) {
        setErr(r.error)
        return
      }
      if (!r.token) {
        setErr('Не удалось получить token. Проверьте Telegram App credentials (api_id/api_hash).')
        return
      }
      setToken(r.token)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!token) return
    setBusy(true)
    setErr(null)
    setGeneratedSessionString(null)
    try {
      const r = await api.telegramVerifyCode({ token, code: code.trim(), password: needsPassword ? password : undefined })
      if (r.error === 'NEEDS_PASSWORD') {
        setNeedsPassword(true)
        setErr('Нужен пароль 2FA. Введите пароль и нажмите «Подтвердить».')
        return
      }
      if (!r.success) {
        setErr(r.error || 'Не удалось авторизоваться')
        return
      }
      if (!r.session_string) {
        setErr('SESSION не получен')
        return
      }
      setGeneratedSessionString(r.session_string)
      setSessionString(r.session_string)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

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
      subtitle="Один экран: Telegram App credentials → вход (код) → session string → сохранить аккаунт в пул (шифрование в БД)."
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
        <div className="cardTitle">Telegram App credentials (api_id / api_hash)</div>
        <div className="hint">
          Эти значения нужны для авторизации через Telethon. Храним на сервере в зашифрованном виде (не в браузере).
        </div>
        <form onSubmit={saveCreds} style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 10 }}>
          <label className="field">
            <div className="label">API ID</div>
            <input value={apiId} onChange={(e) => setApiId(e.target.value)} placeholder="123456" inputMode="numeric" />
          </label>
          <label className="field">
            <div className="label">API HASH</div>
            <input value={apiHash} onChange={(e) => setApiHash(e.target.value)} placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
          </label>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <div className="hint">
              Статус: {credsConfigured === null ? '—' : credsConfigured ? 'настроено' : 'не настроено'}
            </div>
            <button type="submit" className="btn primary" disabled={busy || !apiId.trim() || apiHash.trim().length < 8}>
              Сохранить
            </button>
          </div>
        </form>
      </section>

      <section className="card" style={{ marginTop: 16 }}>
        <div className="cardTitle">Вход по номеру (получить session string)</div>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <label className="field grow">
            <div className="label">Телефон</div>
            <input placeholder="+79991234567" value={phone} onChange={(e) => setPhone(e.target.value)} disabled={busy} />
          </label>
          <button type="button" className="btn primary" onClick={() => void requestCode()} disabled={busy || !canRequest}>
            Запросить код
          </button>
        </div>
        {token ? <div className="hint">Token получен. Введите код ниже.</div> : <div className="hint">Token живёт ~10 минут.</div>}

        <div className="row" style={{ gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
          <label className="field grow">
            <div className="label">Код</div>
            <input placeholder="12345" value={code} onChange={(e) => setCode(e.target.value)} disabled={busy || !token} />
          </label>
          <button type="button" className="btn primary" onClick={() => void verify()} disabled={busy || !canVerify}>
            Подтвердить
          </button>
        </div>

        {needsPassword ? (
          <div className="row" style={{ marginTop: 10 }}>
            <label className="field grow">
              <div className="label">Пароль 2FA</div>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} />
            </label>
          </div>
        ) : null}

        {generatedSessionString ? (
          <div style={{ marginTop: 10 }}>
            <div className="hint">Session string получен. Ниже он уже подставлен в форму «Добавить аккаунт».</div>
          </div>
        ) : null}
      </section>

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
                  {a.last_username ? (
                    <div className="mono small" style={{ marginTop: 6 }}>
                      @{a.last_username}
                    </div>
                  ) : null}
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
