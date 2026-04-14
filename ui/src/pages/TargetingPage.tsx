import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { TargetingProfile, TargetingRun, TargetingPreviewCandidate } from '../lib/api'
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { formatApiError } from '../lib/formatError'

type TargetingParamsV2 = {
  version: 'v2'
  limits: {
    days: number
    max_messages_per_source: number
    max_candidate_text_chars: number
    max_candidates: number | null
  }
  terms: {
    keywords_include: string[]
    keywords_exclude: string[]
    intent_phrases: string[]
  }
  weights: { semantic: number; warmth: number; risk: number }
  thresholds: { min_send_score: number; segment_a_min: number; segment_b_min: number }
  models: { embedding_model: string }
}

function defaultParams(): TargetingParamsV2 {
  return {
    version: 'v2',
    limits: { days: 14, max_messages_per_source: 200, max_candidate_text_chars: 4000, max_candidates: null },
    terms: { keywords_include: [], keywords_exclude: [], intent_phrases: [] },
    weights: { semantic: 1, warmth: 1, risk: 1 },
    thresholds: { min_send_score: 10, segment_a_min: 40, segment_b_min: 10 },
    models: { embedding_model: 'text-embedding-3-small' },
  }
}

function parseCsv(s: string): string[] {
  return s
    .split(/[,\n;]/g)
    .map((x) => x.trim())
    .filter(Boolean)
}

function asParamsV2(obj: unknown): TargetingParamsV2 | null {
  if (!obj || typeof obj !== 'object') return null
  const o = obj as Record<string, unknown>
  if (o.version !== 'v2') return null
  return obj as TargetingParamsV2
}

function candidateLabel(c: TargetingPreviewCandidate): string {
  if (c.username) return `@${c.username}`
  if (c.display_name) return c.display_name
  return `#${c.candidate_id}`
}

export function TargetingPage() {
  const [profiles, setProfiles] = useState<TargetingProfile[] | null>(null)
  const [profileId, setProfileId] = useState('')
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [langMode, setLangMode] = useState<'ru' | 'mixed'>('mixed')
  const [params, setParams] = useState<TargetingParamsV2>(defaultParams())
  const [tab, setTab] = useState<'form' | 'json'>('form')
  const [jsonText, setJsonText] = useState('')
  const [jsonErr, setJsonErr] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draftDiff, setDraftDiff] = useState<{ path: string; before: unknown; after: unknown }[] | null>(null)

  const [run, setRun] = useState<TargetingRun | null>(null)
  const [runBusy, setRunBusy] = useState(false)

  const [topN, setTopN] = useState(50)
  const [segment, setSegment] = useState<'any' | 'A' | 'B' | 'C'>('any')
  const [minScore, setMinScore] = useState('')
  const [topPreview, setTopPreview] = useState<{ counts_by_segment: Record<string, number>; top: TargetingPreviewCandidate[] } | null>(null)

  const [allItems, setAllItems] = useState<TargetingPreviewCandidate[]>([])
  const [allTotal, setAllTotal] = useState(0)
  const [allOffset, setAllOffset] = useState(0)
  const [allLoading, setAllLoading] = useState(false)

  const pid = useMemo(() => (profileId.trim() ? Number(profileId) : null), [profileId])
  const minSendScore = useMemo(() => {
    const s = minScore.trim()
    if (!s) return null
    const n = Number(s)
    return Number.isFinite(n) ? n : null
  }, [minScore])

  const loadProfiles = useCallback(async () => {
    const r = await api.listTargetingProfiles()
    setProfiles(r.items)
  }, [])

  useEffect(() => {
    setErr(null)
    void loadProfiles().catch((e) => setErr(formatApiError(e).message))
  }, [loadProfiles])

  useEffect(() => {
    if (!pid || !profiles) {
      return
    }
    const p = profiles.find((x) => x.id === pid) ?? null
    setQuery(p?.query ?? '')
    setName(p?.name ?? '')
    setLangMode((p?.language_mode as 'ru' | 'mixed') || 'mixed')
    const p2 = asParamsV2(p?.params) ?? defaultParams()
    setParams(p2)
    setJsonText(JSON.stringify(p2, null, 2))
    setJsonErr(null)
    setDraftDiff(null)
    setRun(null)
    setTopPreview(null)
    setAllItems([])
    setAllTotal(0)
    setAllOffset(0)
  }, [pid, profiles])

  useEffect(() => {
    if (!run) return
    if (run.status !== 'queued' && run.status !== 'running') return
    let cancelled = false
    const tick = async () => {
      try {
        const r = await api.getTargetingRun(run.id)
        if (!cancelled) setRun(r)
      } finally {
        if (!cancelled) window.setTimeout(tick, document.hidden ? 15000 : 4000)
      }
    }
    const t = window.setTimeout(tick, 1500)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [run])

  async function createNew() {
    setErr(null)
    setBusy(true)
    try {
      const p = await api.createTargetingProfile({ name: name.trim() || null, query: query.trim(), language_mode: langMode, params })
      await loadProfiles()
      setProfileId(String(p.id))
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (!pid) return
    setErr(null)
    setBusy(true)
    try {
      await api.patchTargetingProfile(pid, { name: name.trim() || null, query: query.trim(), language_mode: langMode, params })
      await loadProfiles()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function clone() {
    if (!pid) return
    setErr(null)
    setBusy(true)
    try {
      const p = await api.cloneTargetingProfile(pid)
      await loadProfiles()
      setProfileId(String(p.id))
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function suggestDraft() {
    if (!pid) return
    setErr(null)
    setBusy(true)
    try {
      const r = await api.suggestTargetingProfileDraft(pid)
      setDraftDiff(r.diff)
      const p2 = asParamsV2(r.draft_params) ?? null
      if (p2) {
        setParams(p2)
        setJsonText(JSON.stringify(p2, null, 2))
        setJsonErr(null)
      }
      await loadProfiles()
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function applyDraft() {
    if (!pid) return
    setErr(null)
    setBusy(true)
    try {
      await api.applyTargetingProfileDraft(pid)
      await loadProfiles()
      setDraftDiff(null)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  async function startRun() {
    if (!pid) return
    setErr(null)
    setRunBusy(true)
    try {
      const r = await api.startTargetingRun(pid)
      const rr = await api.getTargetingRun(r.run_id)
      setRun(rr)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setRunBusy(false)
    }
  }

  async function refreshTop() {
    if (!pid) return
    setErr(null)
    setTopPreview(null)
    setBusy(true)
    try {
      const r = await api.listTargetingCandidatesTop(pid, {
        n: topN,
        segment: segment === 'any' ? undefined : segment,
        min_send_score: minSendScore ?? undefined,
      })
      setTopPreview(r)
    } catch (e) {
      setErr(formatApiError(e).message)
    } finally {
      setBusy(false)
    }
  }

  const fetchAllPage = useCallback(
    async (offset: number, append: boolean) => {
      if (!pid) return
      setAllLoading(true)
      try {
        const r = await api.listTargetingCandidates(pid, {
          limit: 50,
          offset,
          segment: segment === 'any' ? undefined : segment,
          min_send_score: minSendScore ?? undefined,
        })
        setAllTotal(r.page.total)
        if (append) {
          setAllItems((prev) => [...prev, ...r.items])
          setAllOffset(offset + r.items.length)
        } else {
          setAllItems(r.items)
          setAllOffset(r.items.length)
        }
      } catch (e) {
        if (!append) {
          setAllItems([])
          setAllTotal(0)
          setAllOffset(0)
        }
      } finally {
        setAllLoading(false)
      }
    },
    [pid, segment, minSendScore],
  )

  function onJsonChange(next: string) {
    setJsonText(next)
    try {
      const obj = JSON.parse(next) as unknown
      const p2 = asParamsV2(obj)
      if (!p2) {
        setJsonErr('JSON должен быть TargetingParamsV2 (version=v2)')
        return
      }
      setJsonErr(null)
      setParams(p2)
    } catch (e) {
      setJsonErr(e instanceof Error ? e.message : 'invalid json')
    }
  }

  function setPath<K1 extends keyof TargetingParamsV2>(k1: K1, next: TargetingParamsV2[K1]) {
    const p2: TargetingParamsV2 = { ...params, [k1]: next }
    setParams(p2)
    setJsonText(JSON.stringify(p2, null, 2))
    setJsonErr(null)
  }

  if (profiles === null) {
    return (
      <PageLayout title="Таргетинг" subtitle="Оценка и настройка целевой аудитории">
        <SkeletonBlock lines={6} />
      </PageLayout>
    )
  }

  return (
    <PageLayout title="Таргетинг" subtitle="Профили, AI draft, пересчёт (RQ), топ кандидатов и просмотр всех">
      {err ? <UiBanner variant="error">{err}</UiBanner> : null}

      <section className="card">
        <div className="cardTitle">Профиль</div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <select value={profileId} onChange={(e) => setProfileId(e.target.value)} disabled={busy} style={{ width: 320 }}>
            <option value="">— выбрать профиль —</option>
            {profiles.map((p) => (
              <option key={p.id} value={String(p.id)}>
                #{p.id} {p.name || p.query}
              </option>
            ))}
          </select>
          <button type="button" className="btn" disabled={busy || !pid} onClick={() => void clone()}>
            Clone
          </button>
        </div>

        <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginTop: 10 }}>
          <label className="field" style={{ minWidth: 320 }}>
            <div className="label">Name</div>
            <input value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />
          </label>
          <label className="field" style={{ minWidth: 320, flexGrow: 1 }}>
            <div className="label">Query (кого ищу)</div>
            <input value={query} onChange={(e) => setQuery(e.target.value)} disabled={busy} />
          </label>
          <label className="field">
            <div className="label">Language</div>
            <select value={langMode} onChange={(e) => setLangMode(e.target.value as 'ru' | 'mixed')} disabled={busy}>
              <option value="mixed">mixed</option>
              <option value="ru">ru</option>
            </select>
          </label>
        </div>

        <div className="row" style={{ gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
          <button type="button" className="btn primary" disabled={busy || query.trim().length < 2} onClick={() => void (pid ? save() : createNew())}>
            {pid ? 'Save' : 'Create'}
          </button>
          {!pid ? (
            <button type="button" className="btn" disabled={busy || query.trim().length < 2} onClick={() => void createNew()}>
              Create
            </button>
          ) : null}
          <button type="button" className="btn" disabled={busy || !pid} onClick={() => void suggestDraft()}>
            AI Suggest (draft)
          </button>
          <button type="button" className="btn" disabled={busy || !pid} onClick={() => void applyDraft()}>
            Apply draft
          </button>
        </div>

        {draftDiff && draftDiff.length > 0 ? (
          <details style={{ marginTop: 10 }}>
            <summary className="small muted">Что изменил AI (diff)</summary>
            <pre className="mono small" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
              {draftDiff.map((d) => `${d.path}: ${JSON.stringify(d.before)} → ${JSON.stringify(d.after)}`).join('\n')}
            </pre>
          </details>
        ) : null}
      </section>

      <section className="card">
        <div className="cardTitle">Настройки</div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className={tab === 'form' ? 'btn primary' : 'btn'} onClick={() => setTab('form')} disabled={busy}>
            Form
          </button>
          <button type="button" className={tab === 'json' ? 'btn primary' : 'btn'} onClick={() => setTab('json')} disabled={busy}>
            JSON (advanced)
          </button>
        </div>

        {tab === 'form' ? (
          <div style={{ marginTop: 12 }}>
            <div className="label">Limits</div>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginTop: 6 }}>
              <label className="field">
                <div className="label">days</div>
                <input
                  type="number"
                  value={params.limits.days}
                  onChange={(e) => setPath('limits', { ...params.limits, days: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 120 }}
                />
              </label>
              <label className="field">
                <div className="label">max_messages_per_source</div>
                <input
                  type="number"
                  value={params.limits.max_messages_per_source}
                  onChange={(e) => setPath('limits', { ...params.limits, max_messages_per_source: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 180 }}
                />
              </label>
              <label className="field">
                <div className="label">max_candidate_text_chars</div>
                <input
                  type="number"
                  value={params.limits.max_candidate_text_chars}
                  onChange={(e) => setPath('limits', { ...params.limits, max_candidate_text_chars: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 200 }}
                />
              </label>
              <label className="field">
                <div className="label">max_candidates</div>
                <input
                  type="number"
                  placeholder="null = без лимита"
                  value={params.limits.max_candidates ?? ''}
                  onChange={(e) =>
                    setPath('limits', { ...params.limits, max_candidates: e.target.value.trim() ? Number(e.target.value) : null })
                  }
                  disabled={busy}
                  style={{ width: 160 }}
                />
              </label>
            </div>

            <div className="label" style={{ marginTop: 14 }}>
              Terms
            </div>
            <label className="field">
              <div className="label">keywords_include</div>
              <textarea
                rows={2}
                value={params.terms.keywords_include.join(', ')}
                onChange={(e) => setPath('terms', { ...params.terms, keywords_include: parseCsv(e.target.value) })}
                disabled={busy}
              />
            </label>
            <label className="field">
              <div className="label">keywords_exclude</div>
              <textarea
                rows={2}
                value={params.terms.keywords_exclude.join(', ')}
                onChange={(e) => setPath('terms', { ...params.terms, keywords_exclude: parseCsv(e.target.value) })}
                disabled={busy}
              />
            </label>
            <label className="field">
              <div className="label">intent_phrases</div>
              <textarea
                rows={2}
                value={params.terms.intent_phrases.join(', ')}
                onChange={(e) => setPath('terms', { ...params.terms, intent_phrases: parseCsv(e.target.value) })}
                disabled={busy}
              />
            </label>

            <div className="label" style={{ marginTop: 14 }}>
              Weights
            </div>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginTop: 6 }}>
              {(['semantic', 'warmth', 'risk'] as const).map((k) => (
                <label className="field" key={k}>
                  <div className="label">{k}</div>
                  <input
                    type="number"
                    step="0.1"
                    value={params.weights[k]}
                    onChange={(e) => setPath('weights', { ...params.weights, [k]: Number(e.target.value) })}
                    disabled={busy}
                    style={{ width: 120 }}
                  />
                </label>
              ))}
            </div>

            <div className="label" style={{ marginTop: 14 }}>
              Thresholds
            </div>
            <div className="row" style={{ gap: 12, flexWrap: 'wrap', marginTop: 6 }}>
              {(['min_send_score', 'segment_a_min', 'segment_b_min'] as const).map((k) => (
                <label className="field" key={k}>
                  <div className="label">{k}</div>
                  <input
                    type="number"
                    value={params.thresholds[k]}
                    onChange={(e) => setPath('thresholds', { ...params.thresholds, [k]: Number(e.target.value) })}
                    disabled={busy}
                    style={{ width: 140 }}
                  />
                </label>
              ))}
            </div>

            <div className="label" style={{ marginTop: 14 }}>
              Models
            </div>
            <label className="field" style={{ maxWidth: 420 }}>
              <div className="label">embedding_model</div>
              <input
                value={params.models.embedding_model}
                onChange={(e) => setPath('models', { ...params.models, embedding_model: e.target.value })}
                disabled={busy}
              />
            </label>
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <textarea rows={18} value={jsonText} onChange={(e) => onJsonChange(e.target.value)} disabled={busy} style={{ width: '100%' }} />
            {jsonErr ? <div className="small" style={{ marginTop: 6, color: 'var(--danger, #b00)' }}>{jsonErr}</div> : null}
          </div>
        )}
      </section>

      <section className="card">
        <div className="cardTitle">Run (пересчёт)</div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn primary" disabled={!pid || runBusy} onClick={() => void startRun()}>
            {runBusy ? 'Запуск…' : 'Start scoring (RQ)'}
          </button>
          {run ? (
            <div className="small muted">
              status=<strong>{run.status}</strong> · stage=<strong>{run.stage}</strong> · progress={JSON.stringify(run.progress)}
            </div>
          ) : (
            <div className="small muted">Пока нет запуска. Нужен настроенный `REDIS_URL` и воркер.</div>
          )}
        </div>
        {run && run.logs && run.logs.length > 0 ? (
          <details style={{ marginTop: 10 }}>
            <summary className="small muted">Журнал (последние)</summary>
            <pre className="mono small" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
              {run.logs.map((l) => `${l.created_at} · ${l.msg}`).join('\n')}
            </pre>
          </details>
        ) : null}
        {run && run.status === 'failed' ? (
          <pre className="mono small" style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(run.error, null, 2)}
          </pre>
        ) : null}
      </section>

      <section className="card">
        <div className="cardTitle">Кандидаты</div>
        <div className="row" style={{ gap: 12, flexWrap: 'wrap' }}>
          <label className="field">
            <div className="label">Top-N</div>
            <select value={String(topN)} onChange={(e) => setTopN(Number(e.target.value))} disabled={busy}>
              {[20, 50, 100, 200, 500].map((n) => (
                <option key={n} value={String(n)}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <div className="label">Segment</div>
            <select value={segment} onChange={(e) => setSegment(e.target.value as any)} disabled={busy}>
              <option value="any">any</option>
              <option value="A">A</option>
              <option value="B">B</option>
              <option value="C">C</option>
            </select>
          </label>
          <label className="field">
            <div className="label">min_send_score</div>
            <input value={minScore} onChange={(e) => setMinScore(e.target.value)} placeholder="например 10" disabled={busy} style={{ width: 120 }} />
          </label>
          <button type="button" className="btn" disabled={!pid || busy} onClick={() => void refreshTop()}>
            Refresh top
          </button>
          <button type="button" className="btn" disabled={!pid || allLoading} onClick={() => void fetchAllPage(0, false)}>
            {allLoading ? 'Загрузка…' : 'Показать всех (страница 1)'}
          </button>
        </div>

        {topPreview ? (
          <div className="muted" style={{ marginTop: 10 }}>
            <div className="small">
              counts: A={topPreview.counts_by_segment.A ?? 0}, B={topPreview.counts_by_segment.B ?? 0}, C={topPreview.counts_by_segment.C ?? 0}
            </div>
            {topPreview.top.length > 0 ? (
              <div style={{ marginTop: 8, overflowX: 'auto' }}>
                <table className="table small">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Who</th>
                      <th>Seg</th>
                      <th>Score</th>
                      <th>Warm/Risk/Sem</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topPreview.top.map((c) => (
                      <tr key={c.candidate_id}>
                        <td className="mono">{c.candidate_id}</td>
                        <td>{candidateLabel(c)}</td>
                        <td>{c.segment}</td>
                        <td className="mono">{c.send_score}</td>
                        <td className="mono">
                          {c.warmth_score}/{c.risk_score}/{(c.reasons?.semantic_score as any) ?? c.send_score}
                        </td>
                        <td style={{ minWidth: 240 }}>
                          <details>
                            <summary className="small muted">reasons</summary>
                            <pre className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                              {JSON.stringify(c.reasons ?? {}, null, 2)}
                            </pre>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="small" style={{ marginTop: 6 }}>
                Нет данных (нужен run scoring).
              </div>
            )}
          </div>
        ) : null}

        {allItems.length > 0 ? (
          <div className="muted" style={{ marginTop: 12 }}>
            <div className="small">
              Всего: {allTotal} · показано: {allItems.length}
            </div>
            <div style={{ marginTop: 8, overflowX: 'auto' }}>
              <table className="table small">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Who</th>
                    <th>Seg</th>
                    <th>Score</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {allItems.map((c) => (
                    <tr key={c.candidate_id}>
                      <td className="mono">{c.candidate_id}</td>
                      <td>{candidateLabel(c)}</td>
                      <td>{c.segment}</td>
                      <td className="mono">{c.send_score}</td>
                      <td>
                        <details>
                          <summary className="small muted">reasons</summary>
                          <pre className="mono small" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
                            {JSON.stringify(c.reasons ?? {}, null, 2)}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {allItems.length < allTotal ? (
              <button type="button" className="btn" style={{ marginTop: 8 }} disabled={allLoading} onClick={() => void fetchAllPage(allOffset, true)}>
                {allLoading ? 'Загрузка…' : `Ещё (${allItems.length} / ${allTotal})`}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </PageLayout>
  )
}

