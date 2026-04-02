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

function getBaseUrl(): string {
  const v = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (!v) return 'http://127.0.0.1:8000'
  return v.replace(/\/+$/, '')
}

function getAdminToken(): string | undefined {
  const v = import.meta.env.VITE_ADMIN_TOKEN as string | undefined
  return v || undefined
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${getBaseUrl()}${path}`
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')

  const token = getAdminToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(url, { ...init, headers })
  const text = await res.text()
  const json = text ? (JSON.parse(text) as unknown) : null

  if (!res.ok) {
    const err = json as ApiError
    const msg = err?.error?.message || `HTTP ${res.status}`
    throw new Error(msg)
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
  startCollectRun: (payload: { source_ids: number[] }) =>
    request<CollectRun>('/collect-runs', { method: 'POST', body: JSON.stringify(payload) }),

  listInviteRuns: () => request<{ items: InviteRun[] }>('/invite-runs'),
  startInviteRun: (payload: { target_id: number; policy?: Record<string, unknown> }) =>
    request<InviteRun>('/invite-runs', { method: 'POST', body: JSON.stringify(payload) }),
}

