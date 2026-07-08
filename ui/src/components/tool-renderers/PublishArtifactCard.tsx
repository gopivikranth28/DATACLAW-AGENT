import { useMemo, useState } from 'react'
import { Alert, Button, Tag } from 'antd'
import { DownloadOutlined, ExpandAltOutlined, FileDoneOutlined, ExportOutlined } from '@ant-design/icons'
import { API } from '../../api'

interface PublishArtifactResult {
  success?: boolean
  artifact_id?: string
  version?: number
  url?: string
  source_path?: string
  deduped?: boolean
  error?: {
    code?: string
    message?: string
    details?: Record<string, unknown>
  }
}

export default function PublishArtifactCard({ data }: { data: PublishArtifactResult }) {
  const [expanded, setExpanded] = useState(true)
  const artifactUrl = useMemo(() => toApiUrl(data.url || ''), [data.url])
  const exportUrl = data.artifact_id && data.version
    ? `${API}/artifacts/${data.artifact_id}/export?version=${data.version}`
    : ''

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
    <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fff' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '9px 10px',
        borderBottom: expanded ? '1px solid #edf0f4' : 0, flexWrap: 'wrap',
      }}>
        <FileDoneOutlined style={{ color: '#1677ff', fontSize: 15 }} />
        <span style={{ fontSize: 12, fontWeight: 650, color: '#1f2937' }}>Artifact published</span>
        <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>{data.artifact_id}</Tag>
        <Tag style={{ margin: 0, fontSize: 10 }}>v{data.version}</Tag>
        {data.deduped && <Tag color="gold" style={{ margin: 0, fontSize: 10 }}>deduped</Tag>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <Button size="small" icon={<ExpandAltOutlined />} onClick={() => setExpanded(v => !v)}>
            {expanded ? 'Collapse' : 'Expand'}
          </Button>
          <Button size="small" icon={<ExportOutlined />} href={artifactUrl} target="_blank">Open</Button>
          <Button size="small" icon={<DownloadOutlined />} href={exportUrl}>Export</Button>
        </div>
      </div>
      {expanded && (
        <iframe
          title={`${data.artifact_id} v${data.version}`}
          src={artifactUrl}
          sandbox="allow-scripts"
          loading="lazy"
          style={{ display: 'block', width: '100%', height: 560, border: 0, background: '#fff' }}
        />
      )}
      {data.source_path && (
        <div style={{ padding: '6px 10px', borderTop: '1px solid #edf0f4', fontSize: 11, color: '#98a2b3' }}>
          Source: <code>{data.source_path}</code>
        </div>
      )}
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
