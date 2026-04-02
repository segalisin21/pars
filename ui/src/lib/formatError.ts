import { ApiRequestError } from './api'

export function formatApiError(e: unknown): { message: string; code?: string; isNetwork: boolean } {
  if (e instanceof ApiRequestError) {
    return { message: e.message, code: e.code ?? undefined, isNetwork: false }
  }
  if (e instanceof Error) {
    const net = e.message.toLowerCase().includes('failed to fetch') || e.message.toLowerCase().includes('network')
    return { message: e.message, isNetwork: net }
  }
  return { message: 'Неизвестная ошибка', isNetwork: false }
}
