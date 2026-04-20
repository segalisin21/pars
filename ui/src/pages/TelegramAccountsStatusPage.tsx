import { useCallback, useEffect, useState } from 'react'
import { api, apiBaseUrl, type TelegramAccountStatus } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'

function fmtBusy(busy: TelegramAccountStatus['busy']): string {
  if (!busy) return '—'
  return `${busy.kind} #${busy.run_id} · ${busy.status}`
}

export function TelegramAccountsStatusPage() {
  const [items, setItems] = useState<TelegramAccountStatus[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [actionBusyId, setActionBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const r = await api.listTelegramAccountsStatus()
      setItems(r.items)
    } catch (e) {
      setErr(formatApiError(e).message)
      setItems(null)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function testSession(id: number) {
    setActionBusyId(id)
    setErr(null)
    try {
      const r = await api.testTelegramAccount(id)
      if (!r.ok) setErr(r.error || 'Проверка не прошла')
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setActionBusyId(null)
    }
  }

  async function checkSpamBot(id: number) {
    setActionBusyId(id)
    setErr(null)
    try {
      await api.checkTelegramAccountSpamBot(id)
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setActionBusyId(null)
    }
  }

  return (
    <PageLayout title="Telegram статусы" subtitle="Сессия, занятость, cooldown/ошибки, @SpamBot статус.">
      {err ? (
        <UiBanner variant="error" title="Ошибка" onRetry={() => void load()}>
          {err}
          <div className="hint" style={{ marginTop: 8 }}>
            API: <code>{apiBaseUrl()}</code>
          </div>
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <div className="cardTitle">Список</div>
          <button type="button" className="btn" disabled={actionBusyId !== null} onClick={() => void load()}>
            Обновить
          </button>
        </div>
        {items === null ? (
          <SkeletonBlock lines={6} />
        ) : items.length === 0 ? (
          <div className="muted">Аккаунтов пока нет.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {items.map((it) => {
              const a = it.account
              return (
                <div key={a.id} className="card" style={{ padding: '12px 14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                    <div>
                      <strong>{a.label || `#${a.id}`}</strong>{' '}
                      <span className={`badge ${a.enabled ? 'ok' : 'muted'}`}>{a.enabled ? 'вкл' : 'выкл'}</span>
                      {a.last_error_code ? <span className="badge err">{a.last_error_code}</span> : null}
                      <div className="mono small" style={{ marginTop: 6 }}>
                        id={a.id} · @{a.last_username ?? '—'}
                      </div>
                      <div className="mono small" style={{ marginTop: 6 }}>
                        busy {fmtBusy(it.busy)}
                      </div>
                      <div className="mono small" style={{ marginTop: 6 }}>
                        cooldown {a.cooldown_until ?? '—'}
                      </div>
                    </div>

                    <div style={{ minWidth: 320, flex: 1 }}>
                      <div className="label">SpamBot</div>
                      <div className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                        {it.spambot_error ? `error: ${it.spambot_error}` : null}
                        {it.spambot_status_text ? it.spambot_status_text : !it.spambot_error ? '—' : null}
                        {it.spambot_checked_at ? `\nchecked_at: ${it.spambot_checked_at}` : null}
                      </div>
                    </div>
                  </div>

                  <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void testSession(a.id)}
                      disabled={actionBusyId === a.id}
                    >
                      {actionBusyId === a.id ? '…' : 'Проверить сессию'}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => void checkSpamBot(a.id)}
                      disabled={actionBusyId === a.id || !a.enabled}
                    >
                      {actionBusyId === a.id ? '…' : 'Проверить @SpamBot'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>
    </PageLayout>
  )
}

