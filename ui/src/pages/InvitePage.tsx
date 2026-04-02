import { useEffect, useMemo, useState } from 'react'
import { api, apiBaseUrl } from '../lib/api'
import type { InviteRun, Target } from '../lib/api'

export function InvitePage() {
  const [targets, setTargets] = useState<Target[] | null>(null)
  const [runs, setRuns] = useState<InviteRun[] | null>(null)
  const [targetId, setTargetId] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const enabledTargets = useMemo(() => (targets ?? []).filter((t) => t.enabled), [targets])
  const canStart = targetId !== null

  async function load() {
    setErr(null)
    try {
      const [t, r] = await Promise.all([api.listTargets(), api.listInviteRuns()])
      setTargets(t.items)
      setRuns(r.items)
      if (targetId === null) {
        const first = t.items.find((x) => x.enabled)
        setTargetId(first ? first.id : null)
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load')
      setTargets(null)
      setRuns(null)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function start() {
    if (targetId === null) return
    setBusy(true)
    setErr(null)
    try {
      await api.startInviteRun({
        target_id: targetId,
        policy: { max_per_minute: 2, max_per_hour: 30, cooldown_minutes: 0 },
      })
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Start failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="pageHeader">
        <h1>Инвайт</h1>
        <div className="pageSub">Запуск инвайта и история результатов.</div>
      </div>

      {err ? (
        <div className="banner error">
          {err}
          {err.toLowerCase().includes('failed to fetch') ? (
            <div className="hint" style={{ marginTop: 8 }}>
              Не удалось достучаться до API. Проверьте: <code>VITE_API_BASE_URL</code> (сейчас: <code>{apiBaseUrl()}</code>) и
              CORS (<code>CORS_ALLOWED_ORIGINS</code> на API = URL UI).
            </div>
          ) : null}
        </div>
      ) : null}

      <section className="card">
        <div className="cardTitle">Запуск инвайта</div>
        {targets === null ? (
          <div className="muted">Загрузка…</div>
        ) : enabledTargets.length === 0 ? (
          <div className="muted">Сначала включите цель.</div>
        ) : (
          <div className="row">
            <label className="field grow">
              <div className="label">Цель</div>
              <select
                value={targetId ?? ''}
                onChange={(e) => setTargetId(e.target.value ? Number(e.target.value) : null)}
                disabled={busy}
              >
                {enabledTargets.map((t) => (
                  <option key={t.id} value={t.id}>
                    #{t.id} @{t.identifier}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn primary" onClick={start} disabled={busy || !canStart}>
              Запустить инвайт
            </button>
          </div>
        )}
        <div className="hint">
          В v1 применяется безопасный режим (жёсткая пауза по лимитам). Если run стал <code>paused</code> — запустите позже.
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs === null ? (
          <div className="muted">Загрузка…</div>
        ) : runs.length === 0 ? (
          <div className="muted">Запусков пока нет.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статус</th>
                <th>Цель</th>
                <th>Старт</th>
                <th>Итоги</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const s: any = r.stats ?? {}
                const pauseReason = s.pause_reason ? String(s.pause_reason) : null
                return (
                  <tr key={r.id} className={r.status === 'paused' ? 'warn' : ''}>
                    <td className="mono">{r.id}</td>
                    <td>
                      <span
                        className={
                          r.status === 'succeeded'
                            ? 'badge ok'
                            : r.status === 'paused'
                              ? 'badge warn'
                              : r.status === 'failed'
                                ? 'badge err'
                                : 'badge'
                        }
                      >
                        {r.status}
                      </span>
                      {pauseReason ? (
                        <span className="badge" style={{ marginLeft: 8 }}>
                          {pauseReason}
                        </span>
                      ) : null}
                    </td>
                    <td className="mono small">{r.target_id}</td>
                    <td className="mono small">{r.started_at}</td>
                    <td>
                      <div className="row" style={{ alignItems: 'center' }}>
                        <span className="badge">attempted {s.attempted ?? 0}</span>
                        <span className="badge ok">success {s.success ?? 0}</span>
                        <span className="badge">skipped {s.skipped ?? 0}</span>
                        <span className="badge err">failed {s.failed ?? 0}</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

