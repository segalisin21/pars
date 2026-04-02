/** Masks Telegram numeric id for display (last 4 digits). */
export function maskTelegramUserId(id: number): string {
  const s = String(id)
  if (s.length <= 4) return '…'
  return `…${s.slice(-4)}`
}
