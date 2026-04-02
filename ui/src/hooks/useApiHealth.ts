import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export type HealthState = 'ok' | 'error' | 'checking'

export function useApiHealth(pollMs = 30000): HealthState {
  const [state, setState] = useState<HealthState>('checking')

  useEffect(() => {
    let cancelled = false

    async function ping() {
      try {
        const r = await api.health()
        if (!cancelled) setState(r?.status === 'ok' ? 'ok' : 'error')
      } catch {
        if (!cancelled) setState('error')
      }
    }

    void ping()
    const id = setInterval(() => void ping(), pollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollMs])

  return state
}
