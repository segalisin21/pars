import type { ReactNode } from 'react'

export type Column<T> = {
  key: string
  header: ReactNode
  className?: string
  render: (row: T) => ReactNode
}

export type PageMeta = {
  limit: number
  offset: number
  total: number
}

export function DataTable<T>(props: {
  columns: Column<T>[]
  rows: T[]
  page?: PageMeta
  onPageChange?: (next: { limit: number; offset: number }) => void
  empty?: ReactNode
}) {
  const { columns, rows, page, onPageChange, empty } = props
  const canPrev = page ? page.offset > 0 : false
  const canNext = page ? page.offset + page.limit < page.total : false
  const pageLabel = page ? `${page.offset + 1}-${Math.min(page.offset + page.limit, page.total)} из ${page.total}` : null

  return (
    <div className="tableWrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.className}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>{empty ?? <div className="muted">Пусто.</div>}</td>
            </tr>
          ) : (
            rows.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={c.className}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>

      {page ? (
        <div className="pager">
          <div className="muted small">{pageLabel}</div>
          <div className="pagerBtns">
            <button
              className="btn"
              disabled={!canPrev}
              onClick={() => onPageChange?.({ limit: page.limit, offset: Math.max(0, page.offset - page.limit) })}
            >
              Назад
            </button>
            <button
              className="btn"
              disabled={!canNext}
              onClick={() => onPageChange?.({ limit: page.limit, offset: page.offset + page.limit })}
            >
              Вперёд
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

