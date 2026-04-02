import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { CollectMode, Source } from '../lib/api'

const COLLECT_MODE_OPTIONS: { value: CollectMode; label: string }[] = [
  { value: 'participants', label: 'Участники' },
  { value: 'messages', label: 'Чат (авторы)' },
  { value: 'both', label: 'Оба' },
  { value: 'auto', label: 'Авто' },
]
import { PageLayout } from '../components/PageLayout'
import { UiBanner } from '../components/UiBanner'
import { SkeletonBlock } from '../components/SkeletonBlock'
import { EmptyState } from '../components/EmptyState'
import { formatApiError } from '../lib/formatError'

export function SourcesPage() {
  const [items, setItems] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [errCode, setErrCode] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [type, setType] = useState<'group' | 'chat' | 'channel'>('group')
  const [identifier, setIdentifier] = useState('')
  const [newCollectMode, setNewCollectMode] = useState<CollectMode>('participants')
  const [filter, setFilter] = useState('')
  const canSubmit = useMemo(() => identifier.trim().length > 0, [identifier])
  const filtered = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return items ?? []
    return (items ?? []).filter((x) => x.identifier.toLowerCase().includes(f) || String(x.id).includes(f) || x.type.toLowerCase().includes(f))
  }, [items, filter])

  async function load() {
    setErr(null)
    setErrCode(null)
    try {
      const r = await api.listSources()
      setItems(r.items)
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
      setItems(null)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function onCreate() {
    if (!canSubmit) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.createSource({
        type,
        identifier: identifier.trim(),
        enabled: true,
        collect_mode: newCollectMode,
      })
      setIdentifier('')
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function onToggle(src: Source) {
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.patchSource(src.id, { enabled: !src.enabled })
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function onCollectModeChange(src: Source, mode: CollectMode) {
    if (src.collect_mode === mode) return
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.patchSource(src.id, { collect_mode: mode })
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  async function onRefreshMeta(src: Source) {
    setBusy(true)
    setErr(null)
    setErrCode(null)
    try {
      await api.refreshSourceTelegramMeta(src.id)
      await load()
    } catch (e) {
      const f = formatApiError(e)
      setErr(f.message)
      setErrCode(f.code ?? null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <PageLayout
      title="Источники"
      subtitle="Чаты / группы / каналы, откуда собираем кандидатов."
    >
      {err ? (
        <UiBanner variant="error" title={errCode ? `Ошибка (${errCode})` : undefined} onRetry={() => void load()}>
          {err}
        </UiBanner>
      ) : null}

      <section className="card">
        <div className="cardTitle">Добавить источник</div>
        <div className="row">
          <label className="field">
            <div className="label">Тип</div>
            <select value={type} onChange={(e) => setType(e.target.value as 'group' | 'chat' | 'channel')} disabled={busy}>
              <option value="group">group</option>
              <option value="chat">chat</option>
              <option value="channel">channel</option>
            </select>
          </label>

          <label className="field grow">
            <div className="label">Идентификатор</div>
            <input
              placeholder="@публичное_имя или id"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              disabled={busy}
            />
          </label>

          <label className="field">
            <div className="label">Сбор контактов</div>
            <select
              value={newCollectMode}
              onChange={(e) => setNewCollectMode(e.target.value as CollectMode)}
              disabled={busy}
              title="Где воркер ищет людей для этого источника"
            >
              {COLLECT_MODE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>

          <button type="button" className="btn primary" onClick={() => void onCreate()} disabled={busy || !canSubmit}>
            Добавить
          </button>
        </div>
        <div className="hint">
          Запись требует <code>VITE_ADMIN_TOKEN</code>, если на API задан <code>ADMIN_TOKEN</code>. Название и число подписчиков подтягиваются кнопкой «Обновить из Telegram» в списке (нужна сессия воркера с Telethon). «Чат (авторы)» — недавние отправители сообщений; «Авто» — если список участников пуст, тогда из чата.
        </div>
      </section>

      <section className="card">
        <div className="cardTitle">Список</div>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <label className="field grow">
            <div className="label">Поиск</div>
            <input placeholder="id / username / type" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <div className="toolbarRight">
            <span className="badge">всего {items?.length ?? 0}</span>
            <span className="badge">показано {filtered.length}</span>
          </div>
        </div>
        {items === null ? (
          <SkeletonBlock lines={4} />
        ) : items.length === 0 ? (
          <EmptyState title="Источников пока нет" hint="Добавьте первый источник выше." />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Тип</th>
                <th>Идентификатор</th>
                <th>Telegram</th>
                <th>Подписчики</th>
                <th>Мета</th>
                <th>Сбор</th>
                <th>Статус</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr key={s.id} className={s.enabled ? '' : 'disabled'}>
                  <td>{s.id}</td>
                  <td>{s.type}</td>
                  <td className="mono">@{s.identifier}</td>
                  <td>{s.telegram_title ?? '—'}</td>
                  <td>{s.telegram_participants_count != null ? s.telegram_participants_count.toLocaleString() : '—'}</td>
                  <td className="mono small">{s.telegram_meta_updated_at ?? '—'}</td>
                  <td>
                    <select
                      className="selectInTable"
                      value={s.collect_mode ?? 'participants'}
                      onChange={(e) => void onCollectModeChange(s, e.target.value as CollectMode)}
                      disabled={busy}
                      title="Режим сбора для воркера"
                    >
                      {COLLECT_MODE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{s.enabled ? 'Включен' : 'Выключен'}</td>
                  <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <button type="button" className="btn" onClick={() => void onRefreshMeta(s)} disabled={busy} title="Запросить title и participants_count через воркер">
                      Обновить из TG
                    </button>{' '}
                    <button type="button" className="btn" onClick={() => void onToggle(s)} disabled={busy}>
                      {s.enabled ? 'Выключить' : 'Включить'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </PageLayout>
  )
}
