type Props = { lines?: number; className?: string }

export function SkeletonBlock({ lines = 3, className }: Props) {
  return (
    <div className={className} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeletonLine" style={{ marginBottom: 10, width: i === lines - 1 ? '60%' : '100%' }} />
      ))}
    </div>
  )
}
