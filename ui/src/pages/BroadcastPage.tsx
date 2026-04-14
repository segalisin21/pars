import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { BroadcastDelivery, BroadcastPreview, BroadcastRun, DmRecipient, Source, TargetingProfile } from '../lib/api'
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
  const [dmRecipient, setDmRecipient] = useState<DmRecipient>('tg_user_id')
  const [preview, setPreview] = useState<BroadcastPreview | null>(null)
  const [focusedRun, setFocusedRun] = useState<BroadcastRun | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionBusyId, setActionBusyId] = useState<number | null>(null)
  const [tgAccounts, setTgAccounts] = useState<{ id: number; label: string }[] | null>(null)
  const [accountChoice, setAccountChoice] = useState('')
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null)
  const [deliveries, setDeliveries] = useState<BroadcastDelivery[]>([])
  const [deliveriesTotal, setDeliveriesTotal] = useState(0)
  const [deliveriesOffset, setDeliveriesOffset] = useState(0)
  const [deliveriesLoading, setDeliveriesLoading] = useState(false)
  const [editMessageBody, setEditMessageBody] = useState('')
  const [savingMessageRunId, setSavingMessageRunId] = useState<number | null>(null)
  const [targetingPreview, setTargetingPreview] = useState<Awaited<ReturnType<typeof api.previewTargeting>> | null>(null)
  const [targetingProfiles, setTargetingProfiles] = useState<TargetingProfile[] | null>(null)
  const [targetingQuery, setTargetingQuery] = useState('')
  const [targetingLangMode, setTargetingLangMode] = useState<'ru' | 'mixed'>('mixed')
  const [targetingProfileId, setTargetingProfileId] = useState('')
  const [targetingProfilePreview, setTargetingProfilePreview] = useState<Awaited<ReturnType<typeof api.previewTargetingProfile>> | null>(
    null,
  )

  const enabledSources = useMemo(() => (sources ?? []).filter((s) => s.enabled), [sources])

  const accountLabel = useCallback(
    (id: number | null | undefined) => {
      if (id == null) return 'Авто (аккаунт выбирается при старте воркера)'
      const a = (tgAccounts ?? []).find((x) => x.id === id)
      return a?.label?.trim() ? a.label : `#${id}`
    },
    [tgAccounts],
  )

  const fetchDeliveriesPage = useCallback(async (runId: number, offset: number, append: boolean) => {
    setDeliveriesLoading(true)
    try {
      const res = await api.listBroadcastDeliveries(runId, { limit: 50, offset })
      setDeliveriesTotal(res.page.total)
      if (append) {
        setDeliveries((prev) => [...prev, ...res.items])
        setDeliveriesOffset(offset + res.items.length)
      } else {
        setDeliveries(res.items)
        setDeliveriesOffset(res.items.length)
      }
    } catch {
      if (!append) {
        setDeliveries([])
        setDeliveriesTotal(0)
        setDeliveriesOffset(0)
      }
    } finally {
      setDeliveriesLoading(false)
    }
  }, [])

  function toggleRunExpanded(r: BroadcastRun) {
    if (expandedRunId === r.id) {
      setExpandedRunId(null)
      setDeliveries([])
      setDeliveriesTotal(0)
      setDeliveriesOffset(0)
      setEditMessageBody('')
      return
    }
    setExpandedRunId(r.id)
    setEditMessageBody(r.message_body)
    void fetchDeliveriesPage(r.id, 0, false)
  }

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

  useEffect(() => {
    void api
      .listTargetingProfiles()
      .then((r) => setTargetingProfiles(r.items))
      .catch(() => setTargetingProfiles([]))
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
    setTargetingPreview(null)
    setBusy(true)
    try {
      const cids = parseCandidateIds()
      const p = await api.previewBroadcast({
        message_key: messageKey.trim(),
        source_ids: [...sourceIds],
        candidate_ids: cids,
        dm_recipient: dmRecipient,
      })
      setPreview(p)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function doTargetingPreview() {
    setErr(null)
    setTargetingPreview(null)
    setBusy(true)
    try {
      const cids = parseCandidateIds()
      const tp = await api.previewTargeting({
        source_ids: [...sourceIds],
        candidate_ids: cids,
        segment: 'any',
        limit: 50,
      })
      setTargetingPreview(tp)
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
        dm_recipient: dmRecipient,
        targeting_profile_id: targetingProfileId.trim() ? Number(targetingProfileId) : null,
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

  async function suggestProfile() {
    setErr(null)
    setBusy(true)
    try {
      const r = await api.suggestTargetingProfile({ query: targetingQuery.trim(), language_mode: targetingLangMode })
      setTargetingProfiles((prev) => [r.profile, ...(prev ?? [])])
      setTargetingProfileId(String(r.profile.id))
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function previewProfile() {
    setErr(null)
    setTargetingProfilePreview(null)
    const pid = targetingProfileId.trim() ? Number(targetingProfileId) : null
    if (!pid || Number.isNaN(pid)) return
    setBusy(true)
    try {
      const r = await api.previewTargetingProfile({ profile_id: pid, segment: 'any', limit: 50 })
      setTargetingProfilePreview(r)
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

  async function saveRunMessage(runId: number) {
    setErr(null)
    setSavingMessageRunId(runId)
    try {
      await api.patchBroadcastRun(runId, { message_body: editMessageBody })
      await load()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setSavingMessageRunId(null)
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
          <div className="label" style={{ marginTop: 10 }}>
            Текст сообщения
          </div>
          <div className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
            {focusedRun.message_body}
          </div>
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
          <fieldset className="field" disabled={busy} style={{ border: 'none', padding: 0, margin: 0 }}>
            <div className="label">Кому отправлять</div>
            <div className="row" style={{ gap: 16, flexWrap: 'wrap' }}>
              <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="dmRecipient"
                  checked={dmRecipient === 'tg_user_id'}
                  onChange={() => setDmRecipient('tg_user_id')}
                />
                по Telegram ID
              </label>
              <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="dmRecipient"
                  checked={dmRecipient === 'username'}
                  onChange={() => setDmRecipient('username')}
                />
                по @username
              </label>
            </div>
            <div className="small muted" style={{ marginTop: 6 }}>
              В режиме username кандидаты без username не попадают в отправку.
            </div>
          </fieldset>
          <fieldset className="field" disabled={busy} style={{ border: 'none', padding: 0, margin: 0, minWidth: 320 }}>
            <div className="label">AI таргетинг (профиль)</div>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
              <input
                placeholder="Напр. селлеры маркетплейсов"
                value={targetingQuery}
                onChange={(e) => setTargetingQuery(e.target.value)}
                disabled={busy}
                style={{ width: 260 }}
              />
              <select value={targetingLangMode} onChange={(e) => setTargetingLangMode(e.target.value as 'ru' | 'mixed')} disabled={busy}>
                <option value="mixed">mixed</option>
                <option value="ru">ru</option>
              </select>
              <button type="button" className="btn" disabled={busy || !targetingQuery.trim()} onClick={() => void suggestProfile()}>
                Suggest
              </button>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
              <select value={targetingProfileId} onChange={(e) => setTargetingProfileId(e.target.value)} disabled={busy} style={{ width: 260 }}>
                <option value="">без профиля</option>
                {(targetingProfiles ?? []).map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    #{p.id} {p.name || p.query}
                  </option>
                ))}
              </select>
              <button type="button" className="btn" disabled={busy || !targetingProfileId.trim()} onClick={() => void previewProfile()}>
                Preview
              </button>
            </div>
            {targetingProfilePreview ? (
              <div className="small muted" style={{ marginTop: 6 }}>
                A={targetingProfilePreview.counts_by_segment.A ?? 0}, B={targetingProfilePreview.counts_by_segment.B ?? 0}, C=
                {targetingProfilePreview.counts_by_segment.C ?? 0}. Чтобы пересчитать профиль (worker):{' '}
                <code>python -m app.targeting_recompute --workspace-id 1 --targeting-profile-id {targetingProfileId || 0}</code>
              </div>
            ) : null}
          </fieldset>
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
          <button type="button" className="btn" disabled={busy} onClick={() => void doTargetingPreview()}>
            Оценить таргетинг
          </button>
          <button type="button" className="btn primary" disabled={busy || !messageKey.trim() || !messageBody.trim()} onClick={() => void start()}>
            {busy ? 'Запуск…' : 'Запустить'}
          </button>
        </div>
        {preview ? (
          <div className="muted" style={{ marginTop: 10 }}>
            <div>
              <strong>Охват (оценка):</strong> в выборке {preview.scan_total}, готовы к отправке сейчас {preview.eligible}
            </div>
            <div className="small" style={{ marginTop: 6 }}>
              Подавлены: {preview.suppressed}
              {dmRecipient === 'tg_user_id' ? (
                <>
                  , без Telegram ID: {preview.missing_tg_user_id}
                </>
              ) : (
                <>
                  , без username: {preview.missing_username}
                </>
              )}
              , уже по этому ключу: {preview.already_sent}.
              {dmRecipient === 'tg_user_id'
                ? ' Нужен числовой tg_user_id у кандидата.'
                : ' Нужен заполненный username; числовой ID подставится из ответа Telegram после отправки.'}
            </div>
          </div>
        ) : null}
        {targetingPreview ? (
          <div className="muted" style={{ marginTop: 10 }}>
            <div>
              <strong>Таргетинг (по сохранённым фичам):</strong>{' '}
              A={targetingPreview.counts_by_segment.A ?? 0}, B={targetingPreview.counts_by_segment.B ?? 0}, C=
              {targetingPreview.counts_by_segment.C ?? 0}
            </div>
            {targetingPreview.top.length > 0 ? (
              <div style={{ marginTop: 8, overflowX: 'auto' }}>
                <table className="table small">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Segment</th>
                      <th>Score</th>
                      <th>Seen</th>
                      <th>Sources</th>
                      <th>Username</th>
                      <th>Keywords</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targetingPreview.top.map((c) => (
                      <tr key={c.candidate_id}>
                        <td>{c.candidate_id}</td>
                        <td>{c.segment}</td>
                        <td>{c.send_score}</td>
                        <td>{c.seen_as}</td>
                        <td>{c.source_count}</td>
                        <td>{c.username ? `@${c.username}` : '—'}</td>
                        <td>{(c.topic_keywords ?? []).slice(0, 6).join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="small" style={{ marginTop: 6 }}>
                Нет данных. Сначала пересчитайте фичи: <code>python -m app.targeting_recompute --workspace-id 1</code>
              </div>
            )}
          </div>
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
                const expanded = expandedRunId === r.id
                const canEditMessage = r.status === 'queued' || r.status === 'paused'
                return (
                  <Fragment key={r.id}>
                    <tr>
                      <td>
                        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                          <button
                            type="button"
                            className="btn"
                            style={{ minWidth: 36, padding: '4px 8px' }}
                            aria-expanded={expanded}
                            title={expanded ? 'Свернуть' : 'Подробнее'}
                            onClick={() => toggleRunExpanded(r)}
                          >
                            {expanded ? '▼' : '▶'}
                          </button>
                          <Link to={`/broadcast/${r.id}`}>{r.id}</Link>
                        </div>
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
                    {expanded ? (
                      <tr className="broadcast-run-detail">
                        <td colSpan={5} style={{ verticalAlign: 'top', background: 'var(--card-inner-bg, rgba(0,0,0,0.04))' }}>
                          <div style={{ padding: '12px 0' }}>
                            <div className="label">Аккаунт отправки</div>
                            <p className="small muted" style={{ marginTop: 4 }}>
                              {accountLabel(r.telegram_account_id)}
                            </p>
                            <div className="label" style={{ marginTop: 12 }}>
                              Текст сообщения
                            </div>
                            {canEditMessage ? (
                              <>
                                <textarea
                                  rows={5}
                                  value={editMessageBody}
                                  maxLength={4096}
                                  onChange={(e) => setEditMessageBody(e.target.value)}
                                  disabled={savingMessageRunId === r.id}
                                  style={{ width: '100%', marginTop: 6 }}
                                />
                                <div className="row" style={{ marginTop: 8, gap: 8, alignItems: 'center' }}>
                                  <button
                                    type="button"
                                    className="btn primary"
                                    disabled={
                                      savingMessageRunId === r.id ||
                                      !editMessageBody.trim() ||
                                      editMessageBody === r.message_body
                                    }
                                    onClick={() => void saveRunMessage(r.id)}
                                  >
                                    {savingMessageRunId === r.id ? 'Сохранение…' : 'Сохранить текст'}
                                  </button>
                                  <span className="hint small">
                                    Меняет только будущие отправки этого запуска; уже ушедшие в Telegram не правятся.
                                  </span>
                                </div>
                              </>
                            ) : (
                              <pre className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                                {r.message_body}
                              </pre>
                            )}
                            <div className="label" style={{ marginTop: 14 }}>
                              Исходы по получателям
                            </div>
                            <p className="hint small" style={{ marginTop: 4 }}>
                              «success» = Telegram принял отправку с нашей стороны, не статус «прочитано».
                            </p>
                            {deliveriesLoading && deliveries.length === 0 ? (
                              <p className="muted small">Загрузка…</p>
                            ) : deliveries.length === 0 ? (
                              <p className="muted small">Пока нет записей (ещё не было попыток или охват пуст).</p>
                            ) : (
                              <>
                                <table className="table" style={{ marginTop: 8 }}>
                                  <thead>
                                    <tr>
                                      <th>Кандидат</th>
                                      <th>tg_user_id</th>
                                      <th>Ник / имя</th>
                                      <th>Статус</th>
                                      <th>Ошибка</th>
                                      <th>Время</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {deliveries.map((d) => (
                                      <tr key={d.id}>
                                        <td className="mono">{d.candidate_id}</td>
                                        <td className="mono">{d.tg_user_id}</td>
                                        <td className="small">
                                          {d.username ? `@${d.username}` : '—'}
                                          {d.display_name ? ` · ${d.display_name}` : ''}
                                        </td>
                                        <td>{d.status}</td>
                                        <td className="mono small">{d.error_code ?? '—'}</td>
                                        <td className="mono small">{d.attempted_at}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                                {deliveries.length < deliveriesTotal ? (
                                  <button
                                    type="button"
                                    className="btn"
                                    style={{ marginTop: 8 }}
                                    disabled={deliveriesLoading}
                                    onClick={() => void fetchDeliveriesPage(r.id, deliveriesOffset, true)}
                                  >
                                    {deliveriesLoading ? 'Загрузка…' : `Ещё (${deliveries.length} / ${deliveriesTotal})`}
                                  </button>
                                ) : null}
                              </>
                            )}
                            <details style={{ marginTop: 12 }}>
                              <summary className="small muted">Статистика (stats)</summary>
                              <pre className="mono small" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
                                {JSON.stringify(r.stats, null, 2)}
                              </pre>
                            </details>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </PageLayout>
  )
}
