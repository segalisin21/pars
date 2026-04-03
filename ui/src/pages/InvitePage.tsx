import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, apiBaseUrl } from '../lib/api'
import type { InviteRun, Target } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

const POLICY_PRESET_KEY = 'pars.invite.policyPreset'

export const INVITE_POLICY_PRESETS = {
  cautious: { label: 'Осторожный', max_per_minute: 1, max_per_hour: 20, cooldown_minutes: 1440 },
  standard: { label: 'Стандартный', max_per_minute: 2, max_per_hour: 30, cooldown_minutes: 0 },
  aggressive: { label: 'Агрессивный', max_per_minute: 5, max_per_hour: 120, cooldown_minutes: 0 },
} as const

export type InvitePolicyPresetId = keyof typeof INVITE_POLICY_PRESETS

function readStoredPreset(): InvitePolicyPresetId {
  try {
    const v = localStorage.getItem(POLICY_PRESET_KEY)
    if (v === 'cautious' || v === 'standard' || v === 'aggressive') return v
  } catch {
    /* ignore */
  }
  return 'standard'
}

function runIsActive(r: InviteRun): boolean {
  return r.status === 'queued' || r.status === 'running'
}

function formatNextEligible(iso: string | undefined): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const diff = t - Date.now()
  if (diff <= 0) return 'можно продолжать'
  const mins = Math.max(1, Math.ceil(diff / 60000))
  return `~${mins} мин`
}

function pauseReasonHint(code: string | null): string | null {
  if (!code) return null
  switch (code) {
    case 'pacing_limit':
      return 'Достигнут лимит отправки. Дождитесь next_eligible_at или нажмите «Возобновить» позже.'
    case 'flood_wait':
      return 'Telegram вернул FloodWait. Подождите указанное время и возобновите запуск.'
    case 'cancelled':
      return 'Запуск отменён оператором.'
    default:
      return null
  }
}

function errCodeBannerHint(code: string | null): string | null {
  if (!code) return null
  if (code === 'db_pool_timeout' || code === 'db_unavailable') {
    return 'Проблема с пулом БД: уменьшите нагрузку или увеличьте пул на стороне сервера.'
  }
  if (code === 'invite_run_not_resumable') {
    return 'Возобновить можно только запуск в статусе paused.'
  }
  if (code === 'invite_run_not_cancellable') {
    return 'Отменить можно только queued или paused.'
  }
  return null
}

export function InvitePage() {
  const { runId: runIdParam } = useParams()
  const runId = runIdParam ? Number(runIdParam) : null

  const [targets, setTargets] = useState<Target[] | null>(null)
  const [runs, setRuns] = useState<InviteRun[] | null>(null)
  const [targetId, setTargetId] = useState<number | null>(null)
  const [preset, setPreset] = useState<InvitePolicyPresetId>(() => readStoredPreset())
  const [focusedRun, setFocusedRun] = useState<InviteRun | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionBusyId, setActionBusyId] = useState<number | null>(null)
  const didInitTarget = useRef(false)

  const enabledTargets = useMemo(() => (targets ?? []).filter((t) => t.enabled), [targets])
  const canStart = targetId !== null

  const onPresetChange = (id: InvitePolicyPresetId) => {
    setPreset(id)
    try {
      localStorage.setItem(POLICY_PRESET_KEY, id)
    } catch {
      /* ignore */
    }
  }

  const load = useCallback(async () => {
    setErr(null)
    setErrCode(null)
    try {
      const [t, r] = await Promise.all([api.listTargets(), api.listInviteRuns()])
      setTargets(t.items)
      setRuns(r.items)
      if (!didInitTarget.current && t.items.length > 0) {
        didInitTarget.current = true
        const first = t.items.find((x) => x.enabled)
        setTargetId(first ? first.id : null)
      }
      if (runId !== null && !Number.isNaN(runId)) {
        try {
          const one = await api.getInviteRun(runId)
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
      setErrCode(f.code ?? null)
      setTargets(null)
      setRuns(null)
    }
  }, [runId])

  useEffect(() => {
    void load()
  }, [load])

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

  async function start() {
    if (targetId === null) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    const p = INVITE_POLICY_PRESETS[preset]
    try {
      await api.startInviteRun({
        target_id: targetId,
        policy: { max_per_minute: p.max_per_minute, max_per_hour: p.max_per_hour, cooldown_minutes: p.cooldown_minutes },
      })
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function resumeRun(id: number) {
    setActionBusyId(id)
    setErr(null)
    setErrCode(null)
    try {
      await api.resumeInviteRun(id)
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setActionBusyId(null)
    }
  }

  async function cancelRun(id: number) {
    setActionBusyId(id)
    setErr(null)
    setErrCode(null)
    try {
      await api.cancelInviteRun(id)
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setActionBusyId(null)
    }
  }

  const netHint = err && err.toLowerCase().includes('failed to fetch')
  const bannerExtra = errCodeBannerHint(errCode)

  return (
    <PageLayout title="Инвайт" subtitle="Запуск приглашений и история с паузами (FloodWait, лимиты).">
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load()}>
          {err}
          {bannerExtra ? <div className="hint" style={{ marginTop: 8 }}>{bannerExtra}</div> : null}
          {netHint ? (
            <div className="hint" style={{ marginTop: 8 }}>
              Проверьте <code>VITE_API_BASE_URL</code> (сейчас: <code>{apiBaseUrl()}</code>) и CORS.
            </div>
          ) : null}
        </UiBanner>
      ) : null}

      {runId !== null && !Number.isNaN(runId) ? (
        <section className="card">
          <div className="cardTitle">Запуск #{runId}</div>
          {focusedRun ? (
            <>
              <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <span
                  className={
                    focusedRun.status === 'succeeded'
                      ? 'badge ok'
                      : focusedRun.status === 'failed'
                        ? 'badge err'
                        : focusedRun.status === 'paused'
                          ? 'badge warn'
                          : focusedRun.status === 'cancelled'
                            ? 'badge'
                            : 'badge'
                  }
                >
                  {focusedRun.status}
                </span>
                {runIsActive(focusedRun) ? <span className="badge warn">обновление…</span> : null}
              </div>
              <div className="mono small" style={{ marginTop: 8 }}>
                Цель id: {focusedRun.target_id}
              </div>
              {(() => {
                const st = focusedRun.stats ?? {}
                const pr = st.pause_reason ? String(st.pause_reason) : null
                const fw = st.flood_wait_seconds != null ? String(st.flood_wait_seconds) : null
                const nextIso = st.next_eligible_at != null ? String(st.next_eligible_at) : undefined
                const nextHuman = formatNextEligible(nextIso)
                const fbc = st.failed_by_code as Record<string, unknown> | undefined
                const fbcEntries = fbc ? Object.entries(fbc).filter(([, v]) => Number(v) > 0) : []
                return (
                  <>
                    {pr ? (
                      <div className="badge warn" style={{ marginTop: 8 }}>
                        {pr}
                        {fw ? ` · ${fw}s` : ''}
                      </div>
                    ) : null}
                    {pauseReasonHint(pr) ? <div className="hint" style={{ marginTop: 8 }}>{pauseReasonHint(pr)}</div> : null}
                    {nextIso ? (
                      <div className="mono small" style={{ marginTop: 8 }}>
                        next_eligible_at: {nextIso}
                        {nextHuman ? ` (${nextHuman})` : ''}
                      </div>
                    ) : null}
                    {st.remaining_candidates != null ? (
                      <div className="mono small" style={{ marginTop: 4 }}>
                        remaining_candidates: {String(st.remaining_candidates)}
                      </div>
                    ) : null}
                    {fbcEntries.length > 0 ? (
                      <div style={{ marginTop: 8 }}>
                        <div className="label">failed_by_code</div>
                        <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                          {fbcEntries.map(([k, v]) => (
                            <span key={k} className="badge">
                              {k}: {String(v)}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="row" style={{ marginTop: 12, gap: 8, flexWrap: 'wrap' }}>
                      {focusedRun.status === 'paused' ? (
                        <>
                          <button
                            type="button"
                            className="btn primary"
                            disabled={actionBusyId === focusedRun.id}
                            onClick={() => void resumeRun(focusedRun.id)}
                          >
                            {actionBusyId === focusedRun.id ? 'Возобновление…' : 'Возобновить'}
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={actionBusyId === focusedRun.id}
                            onClick={() => void cancelRun(focusedRun.id)}
                          >
                            Отменить
                          </button>
                        </>
                      ) : null}
                      <Link to={`/attempts?invite_run_id=${focusedRun.id}`} className="btn">
                        Попытки этого запуска
                      </Link>
                    </div>
                  </>
                )
              })()}
            </>
          ) : (
            <div className="muted">Запуск не найден.</div>
          )}
          <div style={{ marginTop: 10 }}>
            <Link to="/invite" className="btn">
              Ко всем запускам
            </Link>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="cardTitle">Запуск инвайта</div>
        {targets === null ? (
          <SkeletonBlock lines={2} />
        ) : enabledTargets.length === 0 ? (
          <EmptyState title="Нет активных целей" hint="Создайте и включите цель на странице «Цели»." />
        ) : (
          <div className="row" style={{ flexWrap: 'wrap', gap: 12 }}>
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
            <label className="field">
              <div className="label">Политика</div>
              <select value={preset} onChange={(e) => onPresetChange(e.target.value as InvitePolicyPresetId)} disabled={busy}>
                {(Object.keys(INVITE_POLICY_PRESETS) as InvitePolicyPresetId[]).map((k) => (
                  <option key={k} value={k}>
                    {INVITE_POLICY_PRESETS[k].label} ({INVITE_POLICY_PRESETS[k].max_per_minute}/мин, {INVITE_POLICY_PRESETS[k].max_per_hour}/ч)
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn primary" onClick={() => void start()} disabled={busy || !canStart}>
              {busy ? 'Запуск…' : 'Запустить инвайт'}
            </button>
          </div>
        )}
        <div className="hint" style={{ marginTop: 10 }}>
          Если статус <code>paused</code> — смотрите <code>pause_reason</code> и <code>next_eligible_at</code>; при{' '}
          <code>flood_wait</code> дождитесь таймера и нажмите «Возобновить».
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">История запусков</div>
        {runs === null ? (
          <SkeletonBlock lines={4} />
        ) : runs.length === 0 ? (
          <EmptyState title="Запусков пока нет" />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Статус</th>
                <th>Пауза / дальше</th>
                <th>Цель</th>
                <th>Старт</th>
                <th>Итоги</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const s = r.stats ?? {}
                const pauseReason = s.pause_reason ? String(s.pause_reason) : null
                const active = runIsActive(r)
                const nextIso = s.next_eligible_at != null ? String(s.next_eligible_at) : null
                const nextHuman = formatNextEligible(nextIso ?? undefined)
                return (
                  <tr key={r.id} className={r.status === 'paused' ? 'warn' : ''}>
                    <td className="mono">
                      <Link to={`/invite/${r.id}`}>{r.id}</Link>
                    </td>
                    <td>
                      <span
                        className={
                          r.status === 'succeeded'
                            ? 'badge ok'
                            : r.status === 'paused'
                              ? 'badge warn'
                              : r.status === 'failed'
                                ? 'badge err'
                                : r.status === 'cancelled'
                                  ? 'badge'
                                  : 'badge'
                        }
                      >
                        {r.status}
                      </span>
                      {active ? <span className="badge warn">обновление</span> : null}
                      {pauseReason ? (
                        <span className="badge" style={{ marginLeft: 8 }}>
                          {pauseReason}
                        </span>
                      ) : null}
                    </td>
                    <td className="mono small">
                      {nextIso ? (
                        <>
                          {nextIso}
                          {nextHuman ? <div className="muted">{nextHuman}</div> : null}
                        </>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="mono small">{r.target_id}</td>
                    <td className="mono small">{r.started_at}</td>
                    <td>
                      <div className="row" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
                        <span className="badge">attempted {String(s.attempted ?? 0)}</span>
                        <span className="badge ok">success {String(s.success ?? 0)}</span>
                        <span className="badge">skipped {String(s.skipped ?? 0)}</span>
                        <span className="badge err">failed {String(s.failed ?? 0)}</span>
                        {s.remaining_candidates != null ? (
                          <span className="badge">осталось ~{String(s.remaining_candidates)}</span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      {r.status === 'paused' ? (
                        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="btn primary"
                            disabled={actionBusyId === r.id}
                            onClick={() => void resumeRun(r.id)}
                          >
                            {actionBusyId === r.id ? '…' : 'Возобновить'}
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={actionBusyId === r.id}
                            onClick={() => void cancelRun(r.id)}
                          >
                            Отменить
                          </button>
                        </div>
                      ) : r.status === 'queued' ? (
                        <button
                          type="button"
                          className="btn"
                          disabled={actionBusyId === r.id}
                          onClick={() => void cancelRun(r.id)}
                        >
                          {actionBusyId === r.id ? '…' : 'Отменить'}
                        </button>
                      ) : null}
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
