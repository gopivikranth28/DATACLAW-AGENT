import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { Tag } from 'antd'
import { API } from '../api'
import AppView, {
  collectAppItems,
  itemsFromVisualArtifacts,
  type AppCall,
  type AppLayout,
  type VisualArtifact,
} from '../components/AppView'

interface PublishedSession {
  id: string
  title?: string
  createdAt?: string
  appLayout?: AppLayout | null
  visualArtifacts?: VisualArtifact[]
  messages?: Array<{ role?: string; toolName?: string; result?: string }>
}

// Read-only compatibility surface: /app/<session-id> renders loose visual
// outputs for older sessions. Published artifacts are the durable surface.
export default function AppPage() {
  const { sessionId } = useParams()
  const [session, setSession] = useState<PublishedSession | null>(null)
  const [status, setStatus] = useState<'loading' | 'error' | 'ready'>('loading')

  useEffect(() => {
    if (!sessionId) { setStatus('error'); return }
    fetch(`${API}/chat/sessions/${sessionId}`)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
      .then(s => { setSession(s); setStatus('ready') })
      .catch(() => setStatus('error'))
  }, [sessionId])

  const items = useMemo(() => {
    const artifacts = itemsFromVisualArtifacts(session?.visualArtifacts)
    if (artifacts.length > 0) return artifacts
    const calls: AppCall[] = (session?.messages ?? [])
      .filter(m => m.role === 'tool_call')
      .map(m => ({ name: m.toolName ?? '', result: m.result ?? null }))
    return collectAppItems(calls)
  }, [session])

  if (status === 'loading') {
    return <CenteredNote>Loading…</CenteredNote>
  }
  if (status === 'error') {
    return (
      <CenteredNote>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>App not found</div>
        This session doesn't exist or is no longer available.
      </CenteredNote>
    )
  }

  const date = session?.createdAt ? new Date(session.createdAt).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : ''

  return (
    <div style={{ minHeight: '100vh', background: '#f5f6f8', padding: '32px 16px' }}>
      <div style={{ maxWidth: 900, margin: '0 auto' }}>
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#1a1a1a' }}>{session?.title || 'Analysis'}</div>
            <Tag style={{ margin: 0, fontSize: 10 }}>Scratch view</Tag>
          </div>
          {date && <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 2 }}>{date}</div>}
        </div>
        <AppView items={items} layout={session?.appLayout} />
        <div style={{ textAlign: 'center', fontSize: 11, color: '#b0b0b0', marginTop: 32, paddingBottom: 16 }}>
          Built with Dataclaw
        </div>
      </div>
    </div>
  )
}

function CenteredNote({ children }: { children: ReactNode }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      color: '#8c8c8c', fontSize: 13, background: '#f5f6f8', textAlign: 'center',
    }}>
      <div>{children}</div>
    </div>
  )
}
