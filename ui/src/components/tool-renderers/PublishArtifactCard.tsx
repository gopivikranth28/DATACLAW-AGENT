import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Modal, Spin, Tag } from 'antd'
import { DownloadOutlined, ExpandAltOutlined, FileDoneOutlined, ExportOutlined } from '@ant-design/icons'
import { API } from '../../api'

interface PublishArtifactResult {
  success?: boolean
  artifact_id?: string
  version?: number
  url?: string
  session_id?: string
  source_path?: string
  deduped?: boolean
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
  }
}

export default function PublishArtifactCard({ data, sessionId }: {
  data: PublishArtifactResult
  sessionId?: string | null
}) {
  const [shouldMount, setShouldMount] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const mountRef = useRef<HTMLDivElement | null>(null)
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const modalFrameRef = useRef<HTMLIFrameElement | null>(null)
  const artifactSessionId = data.session_id || sessionIdFromUrl(data.url || '') || sessionId || ''
  const artifactUrl = useMemo(
    () => artifactOpenUrl(data, artifactSessionId),
    [data.artifact_id, data.url, data.version, artifactSessionId],
  )
  const exportUrl = data.artifact_id && data.version
    ? artifactExportUrl(data.artifact_id, data.version, artifactSessionId)
    : ''
  const postTheme = useCallback(() => {
    const theme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    frameRef.current?.contentWindow?.postMessage({ theme }, '*')
    modalFrameRef.current?.contentWindow?.postMessage({ theme }, '*')
  }, [])

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return
    const onChange = () => postTheme()
    if (media.addEventListener) media.addEventListener('change', onChange)
    else media.addListener?.(onChange)
    return () => {
      if (media.removeEventListener) media.removeEventListener('change', onChange)
      else media.removeListener?.(onChange)
    }
  }, [artifactUrl, postTheme])

  useEffect(() => {
    if (!artifactUrl || shouldMount) return
    const node = mountRef.current
    if (!node || typeof IntersectionObserver === 'undefined') {
      setShouldMount(true)
      return
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some(entry => entry.isIntersecting || entry.intersectionRatio > 0)) {
        setShouldMount(true)
        observer.disconnect()
      }
    }, { rootMargin: '320px 0px' })
    observer.observe(node)
    return () => observer.disconnect()
  }, [artifactUrl, shouldMount])

  if (data.success === false) {
    return (
      <Alert
        type="error"
        showIcon
        message={data.error?.code || 'Artifact publish failed'}
        description={data.error?.message || 'The artifact did not pass validation.'}
        style={{ borderRadius: 8 }}
      />
    )
  }

  if (!data.artifact_id || !data.version || !artifactUrl) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Artifact result was incomplete"
        description="No artifact id, version, or URL was returned."
        style={{ borderRadius: 8 }}
      />
    )
  }

  return (
    <div ref={mountRef} style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fff' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px',
        borderBottom: '1px solid #edf0f4', flexWrap: 'wrap',
      }}>
        <FileDoneOutlined style={{ color: '#1677ff', fontSize: 15 }} />
        <span style={{ fontSize: 12, fontWeight: 650, color: '#1f2937' }}>Artifact published</span>
        <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>{data.artifact_id}</Tag>
        <Tag style={{ margin: 0, fontSize: 10 }}>v{data.version}</Tag>
        {data.deduped && <Tag color="gold" style={{ margin: 0, fontSize: 10 }}>deduped</Tag>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <Button size="small" icon={<ExpandAltOutlined />} onClick={() => setModalOpen(true)}>Expand</Button>
          <Button size="small" icon={<ExportOutlined />} href={artifactUrl} target="_blank">Open</Button>
          <Button size="small" icon={<DownloadOutlined />} href={exportUrl}>Export</Button>
        </div>
      </div>
      {shouldMount ? (
        <iframe
          data-testid="published-artifact-preview-frame"
          ref={frameRef}
          title={`${data.artifact_id} v${data.version}`}
          src={artifactUrl}
          sandbox="allow-scripts"
          loading="lazy"
          onLoad={postTheme}
          style={{ display: 'block', width: '100%', height: 560, border: 0, background: '#fff' }}
        />
      ) : (
        <div style={{ height: 220, display: 'grid', placeItems: 'center', background: '#fff' }}>
          <Spin size="small" />
        </div>
      )}
      {data.source_path && (
        <div style={{ padding: '6px 10px', borderTop: '1px solid #edf0f4', fontSize: 11, color: '#98a2b3' }}>
          Source: <code>{data.source_path}</code>
        </div>
      )}
      <Modal
        open={modalOpen}
        title={`${data.artifact_id} v${data.version}`}
        footer={null}
        width="min(1200px, 96vw)"
        onCancel={() => setModalOpen(false)}
        styles={{ body: { padding: 0 } }}
      >
        {modalOpen && (
          <iframe
            data-testid="published-artifact-expanded-frame"
            ref={modalFrameRef}
            title={`${data.artifact_id} v${data.version} expanded`}
            src={artifactUrl}
            sandbox="allow-scripts"
            onLoad={postTheme}
            style={{ display: 'block', width: '100%', height: 'min(78vh, 860px)', border: 0, background: '#fff' }}
          />
        )}
      </Modal>
    </div>
  )
}

function toApiUrl(url: string): string {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  if (url.startsWith('/api/')) return url
  if (url.startsWith('/')) return `${API}${url}`
  return `${API}/${url}`
}

function artifactOpenUrl(data: PublishArtifactResult, sessionId: string): string {
  if (!data.artifact_id || !data.version) return ''
  const raw = data.url || `/api/artifacts/${data.artifact_id}?version=${data.version}`
  return withSessionId(toApiUrl(raw), sessionId)
}

function withSessionId(url: string, sessionId: string): string {
  if (!url || !sessionId) return url
  try {
    const parsed = new URL(url, window.location.origin)
    if (!parsed.searchParams.get('session_id')) {
      parsed.searchParams.set('session_id', sessionId)
    }
    if (parsed.origin === window.location.origin) {
      return `${parsed.pathname}${parsed.search}${parsed.hash}`
    }
    return parsed.toString()
  } catch {
    return url
  }
}

function artifactExportUrl(artifactId: string, version: number, sessionId: string): string {
  const params = new URLSearchParams({ version: String(version), session_id: sessionId || 'default' })
  return `${API}/artifacts/${artifactId}/export?${params.toString()}`
}

function sessionIdFromUrl(url: string): string {
  if (!url) return ''
  try {
    const parsed = new URL(url, window.location.origin)
    return parsed.searchParams.get('session_id') || ''
  } catch {
    return ''
  }
}
