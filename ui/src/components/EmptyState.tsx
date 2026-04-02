import type { ReactNode } from 'react'

type Props = {
  title: string
  hint?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, hint, action }: Props) {
  return (
    <div className="emptyState">
      <div className="emptyStateTitle">{title}</div>
      {hint ? <div className="muted">{hint}</div> : null}
      {action ? <div style={{ marginTop: 14 }}>{action}</div> : null}
    </div>
  )
}
