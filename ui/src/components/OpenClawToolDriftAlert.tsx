import { useEffect, useState } from 'react'
import { Alert, Button, Space, Tag } from 'antd'
import { Link } from 'react-router-dom'
import { API } from '../api'

type SyncStatus = {
  has_snapshot: boolean
  in_sync: boolean
  live_count: number
  installed_count?: number
  added: string[]
  removed: string[]
  installed_at?: string | null
}

const POLL_INTERVAL_MS = 5_000
const PLUGIN_ID = 'dataclaw'

/**
 * Self-contained drift banner. Mount anywhere a tool change might happen
 * (Tools page, custom-tool editor, MCP servers tab) and it will:
 *
 *   - Skip rendering when the configured agent backend isn't openclaw —
 *     drift is only relevant when openclaw owns the agent loop.
 *   - Poll `/api/openclaw/plugins/dataclaw/sync-status` every 5s while
 *     mounted so the banner appears within a heartbeat of the user
 *     creating/deleting a custom tool, MCP server, etc.
 *   - Render a yellow `Alert` listing the added/removed tool names with
 *     a deep link to the config page where the user can click Update on
 *     the dataclaw plugin row.
 */
export function OpenClawToolDriftAlert({ style }: { style?: React.CSSProperties }) {
  const [backend, setBackend] = useState<string | null>(null)
  const [sync, setSync] = useState<SyncStatus | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/config`)
      .then(r => (r.ok ? r.json() : null))
      .then(cfg => {
        if (cancelled || !cfg) return
        const llm = cfg.llm ?? {}
        const resolved = (llm.backend as string | undefined) || 'openclaw'
        setBackend(resolved)
      })
      .catch(() => {
        if (!cancelled) setBackend(null)
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (backend !== 'openclaw') return
    let cancelled = false
    const tick = async () => {
      try {
        const res = await fetch(`${API}/openclaw/plugins/${PLUGIN_ID}/sync-status`)
        if (!res.ok) return
        const data = (await res.json()) as SyncStatus
        if (!cancelled) setSync(data)
      } catch {
        // Network blip — keep last known state.
      }
    }
    tick()
    const id = window.setInterval(tick, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [backend])

  if (backend !== 'openclaw') return null
  if (!sync || !sync.has_snapshot || sync.in_sync) return null

  const total = sync.added.length + sync.removed.length

  return (
    <Alert
      type="warning"
      showIcon
      style={style}
      message={
        <Space size={6} wrap>
          <span>
            {total} tool change{total === 1 ? '' : 's'} since last OpenClaw install —
            reinstall the dataclaw plugin so the openclaw agent picks them up.
          </span>
          {sync.installed_at && (
            <Tag color="default" style={{ fontWeight: 'normal' }}>
              last installed {new Date(sync.installed_at).toLocaleString()}
            </Tag>
          )}
        </Space>
      }
      description={
        <div style={{ fontSize: 12 }}>
          {sync.added.length > 0 && (
            <div>
              <strong>Added ({sync.added.length}):</strong>{' '}
              <span style={{ fontFamily: 'monospace' }}>{sync.added.join(', ')}</span>
            </div>
          )}
          {sync.removed.length > 0 && (
            <div>
              <strong>Removed ({sync.removed.length}):</strong>{' '}
              <span style={{ fontFamily: 'monospace' }}>{sync.removed.join(', ')}</span>
            </div>
          )}
        </div>
      }
      action={
        <Link to="/config">
          <Button size="small" type="primary">Open Config</Button>
        </Link>
      }
    />
  )
}
