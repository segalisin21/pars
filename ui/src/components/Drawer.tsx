import { ReactNode, useEffect } from 'react'

export function Drawer(props: { open: boolean; title: ReactNode; onClose: () => void; children: ReactNode }) {
  const { open, title, onClose, children } = props

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="drawerOverlay" onMouseDown={onClose}>
      <div className="drawer" onMouseDown={(e) => e.stopPropagation()}>
        <div className="drawerHeader">
          <div className="drawerTitle">{title}</div>
          <button className="btn" onClick={onClose}>
            Закрыть
          </button>
        </div>
        <div className="drawerBody">{children}</div>
      </div>
    </div>
  )
}

