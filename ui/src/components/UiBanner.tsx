import type { ReactNode } from 'react'

type Variant = 'error' | 'warning' | 'info'

type Props = {
  variant: Variant
  title?: string
  children: ReactNode
  onRetry?: () => void
}

export function UiBanner({ variant, title, children, onRetry }: Props) {
  return (
    <div className={`banner ${variant === 'error' ? 'error' : variant === 'warning' ? 'warning' : 'info'}`}>
      {title ? <div className="bannerTitle">{title}</div> : null}
      <div>{children}</div>
      {onRetry ? (
        <div style={{ marginTop: 10 }}>
          <button type="button" className="btn" onClick={onRetry}>
            Повторить
          </button>
        </div>
      ) : null}
    </div>
  )
}
