import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { formatApiError } from '../lib/formatError'

export function TelegramAuthPage() {
  const [phone, setPhone] = useState('')
  const [token, setToken] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [needsPassword, setNeedsPassword] = useState(false)
  const [sessionString, setSessionString] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const canRequest = useMemo(() => phone.trim().length >= 5, [phone])
  const canVerify = useMemo(() => !!token && code.trim().length >= 3, [token, code])

  async function requestCode() {
    setBusy(true)
    setErr(null)
    setErrCode(null)
    setSessionString(null)
    setNeedsPassword(false)
    try {
      const r = await api.telegramRequestCode({ phone: phone.trim() })
      if (r.error) {
        setErr(r.error)
        return
      }
      if (!r.token) {
        setErr('Не удалось получить token (проверьте TG_API_ID/TG_API_HASH на API).')
        return
      }
      setToken(r.token)
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!token) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    setSessionString(null)
    try {
      const r = await api.telegramVerifyCode({
        token,
        code: code.trim(),
        password: needsPassword ? password : undefined,
      })
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
      setSessionString(r.session_string)
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function copySession() {
    if (!sessionString) return
    await navigator.clipboard.writeText(sessionString)
  }

  return (
    <PageLayout
      title="Telegram вход"
      subtitle="Получите строку сессии для переменной TG_SESSION_STRING в сервисе worker (Railway)."
    >
      <UiBanner variant="info">
        Не сохраняйте session string в браузере (localStorage) и не коммитьте в репозиторий. Скопируйте один раз и вставьте только в
        секреты worker.
      </UiBanner>

      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined}>
          {err}
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="cardTitle">Шаг 1 — запросить код</div>
        <div className="row">
          <label className="field grow">
            <div className="label">Телефон</div>
            <input placeholder="+79991234567" value={phone} onChange={(e) => setPhone(e.target.value)} disabled={busy} />
          </label>
          <button type="button" className="btn primary" onClick={() => void requestCode()} disabled={busy || !canRequest}>
            Запросить код
          </button>
        </div>
        {token ? (
          <div className="hint">Token получен. Переходите к шагу 2. (Token живёт ~10 минут, хранится только в памяти API.)</div>
        ) : (
          <div className="hint">
            Требуется: на сервисе <b>api</b> должны быть заданы <code>TG_API_ID</code> и <code>TG_API_HASH</code>.
          </div>
        )}
      </section>

      <section className="card">
        <div className="cardTitle">Шаг 2 — подтвердить код</div>
        <div className="row">
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
              <input
                type="password"
                placeholder="Пароль"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={busy}
              />
            </label>
          </div>
        ) : null}

        <div className="hint">
          Нужны <code>VITE_ADMIN_TOKEN</code> в UI и <code>ADMIN_TOKEN</code> на API, если токен включён.
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Результат</div>
        {sessionString ? (
          <>
            <div className="hint">
              Скопируйте строку и добавьте в Railway переменную <code>TG_SESSION_STRING</code> <b>только</b> в сервис <b>worker</b>.
            </div>
            <textarea
              className="mono"
              style={{
                width: '100%',
                minHeight: 120,
                marginTop: 10,
                background: 'rgba(5,10,20,0.6)',
                color: '#e6e9ef',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: 10,
                padding: 10,
              }}
              readOnly
              value={sessionString}
            />
            <div className="row" style={{ justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" className="btn" onClick={() => void copySession()}>
                Скопировать
              </button>
            </div>
          </>
        ) : (
          <div className="muted">Пока нет session string.</div>
        )}
      </section>
    </PageLayout>
  )
}
