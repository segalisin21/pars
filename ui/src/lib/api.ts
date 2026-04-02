export type ApiError = {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
  }
}

export type Source = {
  id: number
  type: 'group' | 'chat' | 'channel' | string
  identifier: string
  enabled: boolean
  notes: string | null
}

export type Target = {
  id: number
  identifier: string
  enabled: boolean
  notes: string | null
}

export type CollectRun = {
  id: number
  status: string
  source_ids: number[]
  started_at: string
  finished_at: string | null
  stats: Record<string, unknown>
}

export type InviteRun = {
  id: number
  status: string
  target_id: number
  policy: Record<string, unknown>
  started_at: string
  finished_at: string | null
  stats: Record<string, unknown>
}

export type TelegramRequestCodeOut = {
  token: string | null
  error: string | null
}

export type TelegramVerifyCodeOut = {
  success: boolean
  session_string: string | null
  error: string | null
}

export type PageMeta = {
  limit: number
  offset: number
  total: number
}

export type SourceRef = {
  id: number
  type: string
  identifier: string
}

export type Candidate = {
  id: number
  tg_user_id: number | null
  username: string | null
  display_name: string | null
  first_seen_at: string
  last_seen_at: string
  sources: SourceRef[]
}

export type CandidatesList = {
  items: Candidate[]
  page: PageMeta
}

export type InviteAttempt = {
  id: number
  invite_run_id: number
  target_id: number
  candidate_id: number
  status: string
  error_code: string | null
  attempted_at: string
}

export type InviteAttemptsList = {
  items: InviteAttempt[]
  page: PageMeta
}

export type SuppressionRow = {
  id: number
  tg_user_id: number | null
  username: string | null
  reason: string
  until: string | null
  created_at: string
}

export type SuppressionList = {
  items: SuppressionRow[]
  page: PageMeta
}

export type AuditEvent = {
  id: number
  action: string
  entity_type: string
  entity_id: number | null
  meta: Record<string, unknown>
  created_at: string
}

export type AuditEventsList = {
  items: AuditEvent[]
  page: PageMeta
}

function getBaseUrl(): string {
  const v = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!v) return 'http://127.0.0.1:8000'
  return v.replace(/\/+$/, '')
}

export function apiBaseUrl(): string {
  return getBaseUrl()
}

function getAdminToken(): string | undefined {
  const v = import.meta.env.VITE_ADMIN_TOKEN as string | undefined
  return v || undefined
}

/** Thrown on non-2xx; includes API `error.code` when present. */
export class ApiRequestError extends Error {
  readonly status: number
  readonly code?: string
  readonly details: Record<string, unknown>

  constructor(message: string, status: number, code?: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
    this.details = details
  }
}

function parseJson(text: string): unknown {
  try {
    return text ? JSON.parse(text) : null
  } catch {
    return null
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${getBaseUrl()}${path}`
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')

  const token = getAdminToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { ...init, headers })
  const text = await res.text()
  const json = parseJson(text)

  if (!res.ok) {
    const err = json as Partial<ApiError> | null
    const msg = err?.error?.message || text || `HTTP ${res.status}`
    const code = err?.error?.code
    const details = err?.error?.details && typeof err.error.details === 'object' ? err.error.details : {}
    throw new ApiRequestError(msg, res.status, code, details as Record<string, unknown>)
  }
  return json as T
}

export const api = {
  health: () => request<{ status: string }>('/health'),

  listSources: () => request<{ items: Source[] }>('/sources'),
  createSource: (payload: { type: string; identifier: string; enabled?: boolean; notes?: string | null }) =>
    request<Source>('/sources', { method: 'POST', body: JSON.stringify(payload) }),
  patchSource: (id: number, payload: { enabled?: boolean; notes?: string | null }) =>
    request<Source>(`/sources/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  listTargets: () => request<{ items: Target[] }>('/targets'),
  createTarget: (payload: { identifier: string; enabled?: boolean; notes?: string | null }) =>
    request<Target>('/targets', { method: 'POST', body: JSON.stringify(payload) }),
  patchTarget: (id: number, payload: { enabled?: boolean; notes?: string | null }) =>
    request<Target>(`/targets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  listCollectRuns: () => request<{ items: CollectRun[] }>('/collect-runs'),
  getCollectRun: (id: number) => request<CollectRun>(`/collect-runs/${id}`),
  startCollectRun: (payload: { source_ids: number[] }) =>
    request<CollectRun>('/collect-runs', { method: 'POST', body: JSON.stringify(payload) }),

  listInviteRuns: () => request<{ items: InviteRun[] }>('/invite-runs'),
  getInviteRun: (id: number) => request<InviteRun>(`/invite-runs/${id}`),
  startInviteRun: (payload: { target_id: number; policy?: Record<string, unknown> }) =>
    request<InviteRun>('/invite-runs', { method: 'POST', body: JSON.stringify(payload) }),

  telegramRequestCode: (payload: { phone: string }) =>
    request<TelegramRequestCodeOut>('/telegram/auth/request_code', { method: 'POST', body: JSON.stringify(payload) }),
  telegramVerifyCode: (payload: { token: string; code: string; password?: string }) =>
    request<TelegramVerifyCodeOut>('/telegram/auth/verify_code', { method: 'POST', body: JSON.stringify(payload) }),

  listCandidates: (params?: { q?: string; source_id?: number; has_tg_user_id?: boolean; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams()
    if (params?.q) sp.set('q', params.q)
    if (params?.source_id !== undefined) sp.set('source_id', String(params.source_id))
    if (params?.has_tg_user_id !== undefined) sp.set('has_tg_user_id', String(params.has_tg_user_id))
    if (params?.limit !== undefined) sp.set('limit', String(params.limit))
    if (params?.offset !== undefined) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return request<CandidatesList>(`/candidates${qs ? `?${qs}` : ''}`)
  },
  getCandidate: (id: number) => request<Candidate>(`/candidates/${id}`),

  listInviteAttempts: (params?: {
    invite_run_id?: number
    candidate_id?: number
    target_id?: number
    status?: string
    error_code?: string
    limit?: number
    offset?: number
  }) => {
    const sp = new URLSearchParams()
    if (params?.invite_run_id !== undefined) sp.set('invite_run_id', String(params.invite_run_id))
    if (params?.candidate_id !== undefined) sp.set('candidate_id', String(params.candidate_id))
    if (params?.target_id !== undefined) sp.set('target_id', String(params.target_id))
    if (params?.status) sp.set('status', params.status)
    if (params?.error_code) sp.set('error_code', params.error_code)
    if (params?.limit !== undefined) sp.set('limit', String(params.limit))
    if (params?.offset !== undefined) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return request<InviteAttemptsList>(`/invite-attempts${qs ? `?${qs}` : ''}`)
  },

  listSuppression: (params?: { q?: string; reason?: string; active_only?: boolean; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams()
    if (params?.q) sp.set('q', params.q)
    if (params?.reason) sp.set('reason', params.reason)
    if (params?.active_only !== undefined) sp.set('active_only', String(params.active_only))
    if (params?.limit !== undefined) sp.set('limit', String(params.limit))
    if (params?.offset !== undefined) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return request<SuppressionList>(`/suppression${qs ? `?${qs}` : ''}`)
  },

  listAudit: (params?: { action?: string; entity_type?: string; limit?: number; offset?: number }) => {
    const sp = new URLSearchParams()
    if (params?.action) sp.set('action', params.action)
    if (params?.entity_type) sp.set('entity_type', params.entity_type)
    if (params?.limit !== undefined) sp.set('limit', String(params.limit))
    if (params?.offset !== undefined) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return request<AuditEventsList>(`/audit${qs ? `?${qs}` : ''}`)
  },
}

