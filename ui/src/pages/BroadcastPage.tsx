import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { BroadcastRun, Source } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

function runIsActive(r: BroadcastRun): boolean {
  return r.status === 'queued' || r.status === 'running'
}

export function BroadcastPage() {
  const { runId: runIdParam } = useParams()
  const runId = runIdParam ? Number(runIdParam) : null

  const [sources, setSources] = useState<Source[] | null>(null)
  const [runs, setRuns] = useState<BroadcastRun[] | null>(null)
  const [sourceIds, setSourceIds] = useState<Set<number>>(new Set())
  const [messageKey, setMessageKey] = useState('')
  const [messageBody, setMessageBody] = useState('')
  const [candidateIdsRaw, setCandidateIdsRaw] = useState('')
  const [maxPerMinute, setMaxPerMinute] = useState('2')
  const [maxPerHour, setMaxPerHour] = useState('30')
  const [maxTotal, setMaxTotal] = useState('')
  const [preview, setPreview] = useState<{ eligible: number; scan_total: number } | null>(null)
  const [focusedRun, setFocusedRun] = useState<BroadcastRun | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionBusyId, setActionBusyId] = useState<number | null>(null)
  const [tgAccounts, setTgAccounts] = useState<{ id: number; label: string }[] | null>(null)
  const [accountChoice, setAccountChoice] = useState('')

  const enabledSources = useMemo(() => (sources ?? []).filter((s) => s.enabled), [sources])

  function toggleSource(id: number) {
    setSourceIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function parseCandidateIds(): number[] {
    const parts = candidateIdsRaw.split(/[\s,;]+/).filter(Boolean)
    const out: number[] = []
    for (const p of parts) {
      const n = Number(p)
      if (Number.isInteger(n) && n > 0) out.push(n)
    }
    return [...new Set(out)].sort((a, b) => a - b)
  }

  const load = useCallback(async () => {
    setErr(null)
    try {
      const [s, r] = await Promise.all([api.listSources(), api.listBroadcastRuns()])
      setSources(s.items)
      setRuns(r.items)
      if (runId !== null && !Number.isNaN(runId)) {
        try {
          const one = await api.getBroadcastRun(runId)
          setFocusedRun(one)
        } catch {
          setFocusedRun(null)
        }
      } else {
        setFocusedRun(null)
      }
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setSources(null)
      setRuns(null)
    }
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void api
      .listTelegramAccounts()
      .then((r) => setTgAccounts(r.items.filter((x) => x.enabled).map((x) => ({ id: x.id, label: x.label }))))
      .catch(() => setTgAccounts([]))
  }, [])

  const needsPoll = useMemo(() => (runs ?? []).some(runIsActive), [runs])
  const focusNeedsPoll = useMemo(() => (focusedRun ? runIsActive(focusedRun) : false), [focusedRun])

  useEffect(() => {
    if (!needsPoll && !focusNeedsPoll) return
    let cancelled = false
    let timeoutId: number
    const schedule = () => {
      const delayMs = document.hidden ? 15000 : 5000
      timeoutId = window.setTimeout(async () => {
        if (cancelled) return
        await load()
        if (!cancelled) schedule()
      }, delayMs)
    }
    const onVisibility = () => {
      window.clearTimeout(timeoutId)
      if (!document.hidden) void load()
      schedule()
    }
    document.addEventListener('visibilitychange', onVisibility)
    schedule()
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisibility)
      window.clearTimeout(timeoutId)
    }
  }, [needsPoll, focusNeedsPoll, load])

  async function doPreview() {
    setErr(null)
    setPreview(null)
    setBusy(true)
    try {
      const cids = parseCandidateIds()
      const p = await api.previewBroadcast({
        message_key: messageKey.trim(),
        source_ids: [...sourceIds],
        candidate_ids: cids,
      })
      setPreview({ eligible: p.eligible, scan_total: p.scan_total })
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function start() {
    setErr(null)
    setBusy(true)
    try {
      const cids = parseCandidateIds()
      const mx = maxTotal.trim() === '' ? undefined : Number(maxTotal)
      const policy = {
        max_per_minute: Number(maxPerMinute) || 2,
        max_per_hour: Number(maxPerHour) || 30,
        max_total: mx !== undefined && Number.isFinite(mx) && mx > 0 ? mx : null,
      }
      const acc = accountChoice === '' ? null : Number(accountChoice)
      await api.startBroadcastRun({
        message_key: messageKey.trim(),
        message_body: messageBody,
        source_ids: [...sourceIds],
        candidate_ids: cids,
        policy,
        telegram_account_id: acc,
      })
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function resume(id: number) {
    setErr(null)
    setActionBusyId(id)
    try {
      await api.resumeBroadcastRun(id)
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setActionBusyId(null)
    }
  }

  async function cancel(id: number) {
    setErr(null)
    setActionBusyId(id)
    try {
      await api.cancelBroadcastRun(id)
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setActionBusyId(null)
    }
  }

  if (sources === null || runs === null) {
    return (
      <PageLayout title="Рассылка" subtitle="Личные сообщения по контактам workspace">
        <SkeletonBlock lines={6} />
      </PageLayout>
    )
  }

  return (
    <PageLayout
      title="Рассылка"
      subtitle="Текст, ключ идемпотентности (message_key), источники и лимиты. Повтор с тем же ключом не шлёт повторно уже доставленным."
    >
      {err ? <UiBanner variant="error">{err}</UiBanner> : null}

      {focusedRun ? (
        <section className="card">
          <div className="cardTitle">Запуск #{focusedRun.id}</div>
          <p className="muted">
            Статус: <strong>{focusedRun.status}</strong> · ключ <code>{focusedRun.message_key}</code>
          </p>
          <div className="mono small" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(focusedRun.stats, null, 2)}
          </div>
          <Link to="/broadcast" className="btn" style={{ marginTop: 12, display: 'inline-block' }}>
            Ко всем запускам
          </Link>
        </section>
      ) : null}

      <section className="card">
        <div className="cardTitle">Новая рассылка</div>
        <label className="field">
          <div className="label">Ключ сообщения (message_key)</div>
          <input
            value={messageKey}
            onChange={(e) => setMessageKey(e.target.value)}
            placeholder="например promo_apr2026_v1"
            autoComplete="off"
            disabled={busy}
          />
          <div className="hint">Буквы, цифры, _, -, . · не более одной успешной доставки на пару (ключ, tg_user_id)</div>
        </label>
        <label className="field">
          <div className="label">Текст сообщения</div>
          <textarea rows={6} value={messageBody} onChange={(e) => setMessageBody(e.target.value)} maxLength={4096} disabled={busy} />
          <div className="hint">{messageBody.length} / 4096</div>
        </label>
        <label className="field">
          <div className="label">ID кандидатов (опционально)</div>
          <textarea
            rows={2}
            value={candidateIdsRaw}
            onChange={(e) => setCandidateIdsRaw(e.target.value)}
            placeholder="Через запятую или пробел: 12 34 56"
            disabled={busy}
          />
          <div className="hint">Пусто — по источникам ниже или по всем контактам workspace</div>
        </label>
        {enabledSources.length > 0 ? (
          <>
            <div className="label" style={{ marginTop: 14 }}>
              Ограничить по источникам (опционально)
            </div>
            <div className="chips" style={{ marginTop: 6 }}>
              {enabledSources.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={sourceIds.has(s.id) ? 'chip selected' : 'chip'}
                  onClick={() => toggleSource(s.id)}
                  disabled={busy}
                  title={`#${s.id} @${s.identifier}`}
                >
                  #{s.id} @{s.identifier}
                </button>
              ))}
            </div>
            <div className="hint" style={{ marginTop: 8 }}>
              Ничего не выбрано — берутся все кандидаты workspace (или пересечение с полем ID выше).
            </div>
          </>
        ) : (
          <div className="hint" style={{ marginTop: 10 }}>
            Нет активных источников — рассылка пойдёт по всем кандидатам (или только по указанным ID).
          </div>
        )}
        <div className="row" style={{ flexWrap: 'wrap', gap: 12, marginTop: 14 }}>
          <label className="field">
            <div className="label">В минуту</div>
            <input type="number" min={1} max={60} value={maxPerMinute} onChange={(e) => setMaxPerMinute(e.target.value)} disabled={busy} style={{ width: 100 }} />
          </label>
          <label className="field">
            <div className="label">В час</div>
            <input type="number" min={1} max={10000} value={maxPerHour} onChange={(e) => setMaxPerHour(e.target.value)} disabled={busy} style={{ width: 100 }} />
          </label>
          <label className="field">
            <div className="label">Всего успешных</div>
            <input
              type="number"
              min={1}
              max={100000}
              placeholder="без лимита"
              value={maxTotal}
              onChange={(e) => setMaxTotal(e.target.value)}
              disabled={busy}
              style={{ width: 120 }}
            />
          </label>
          {tgAccounts && tgAccounts.length > 0 ? (
            <label className="field">
              <div className="label">Telegram аккаунт</div>
              <select value={accountChoice} onChange={(e) => setAccountChoice(e.target.value)} disabled={busy}>
                <option value="">Авто</option>
                {tgAccounts.map((a) => (
                  <option key={a.id} value={String(a.id)}>
                    {a.label || `#${a.id}`}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button type="button" className="btn" disabled={busy || !messageKey.trim()} onClick={() => void doPreview()}>
            Оценить охват
          </button>
          <button type="button" className="btn primary" disabled={busy || !messageKey.trim() || !messageBody.trim()} onClick={() => void start()}>
            {busy ? 'Запуск…' : 'Запустить'}
          </button>
        </div>
        {preview ? (
          <p className="muted" style={{ marginTop: 10 }}>
            Охват: в выборке {preview.scan_total}, готовы к отправке сейчас ~{preview.eligible}
          </p>
        ) : null}
        <div className="hint" style={{ marginTop: 10 }}>
          При <code>paused</code> используйте планировщик <code>python -m app.invite_scheduler</code> (обрабатывает и инвайты, и
          рассылки) или кнопку «Возобновить».
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs.length === 0 ? (
          <EmptyState title="Пока нет запусков" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статус</th>
                <th>Ключ</th>
                <th>Успех</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const st = r.stats as Record<string, unknown>
                const ok = typeof st.success === 'number' ? st.success : '—'
                return (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/broadcast/${r.id}`}>{r.id}</Link>
                    </td>
                    <td>{r.status}</td>
                    <td>
                      <code>{r.message_key}</code>
                    </td>
                    <td>{ok}</td>
                    <td>
                      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                        {r.status === 'paused' ? (
                          <button type="button" className="btn" disabled={actionBusyId === r.id} onClick={() => void resume(r.id)}>
                            Возобновить
                          </button>
                        ) : null}
                        {r.status === 'queued' || r.status === 'paused' ? (
                          <button type="button" className="btn danger" disabled={actionBusyId === r.id} onClick={() => void cancel(r.id)}>
                            Отмена
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </PageLayout>
  )
}
