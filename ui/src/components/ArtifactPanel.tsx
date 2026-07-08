import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Select, Spin, Tag, Tooltip } from 'antd'
import { DownloadOutlined, ExportOutlined, FileDoneOutlined, ReloadOutlined } from '@ant-design/icons'
import { API } from '../api'

interface ArtifactVersion {
  version: number
  label?: string
  bytes?: number
  created_at?: string
}

interface ArtifactRecord {
  artifact_id: string
  kind?: string
  title: string
  description?: string
  latest_version: number
  versions: ArtifactVersion[]
  source_path?: string
  updated_at?: string
  url?: string
}

export default function ArtifactPanel({ sessionId, refreshKey = 0 }: {
  sessionId: string | null
  refreshKey?: number
}) {
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const frameRef = useRef<HTMLIFrameElement | null>(null)

  const load = useCallback(() => {
    if (!sessionId) {
      setArtifacts([])
      setSelectedId(null)
      setSelectedVersion(null)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    fetch(`${API}/artifacts?session_id=${encodeURIComponent(sessionId)}`)
      .then(r => {
        if (!r.ok) throw new Error(`Artifact library failed with ${r.status}`)
        return r.json()
      })
      .then(data => {
        const next = sortArtifacts(Array.isArray(data.artifacts) ? data.artifacts : [])
        const nextSelectedId = selectedId && next.some((a: ArtifactRecord) => a.artifact_id === selectedId)
          ? selectedId
          : next[0]?.artifact_id || null
        const nextSelected = next.find((a: ArtifactRecord) => a.artifact_id === nextSelectedId) || null
        setArtifacts(next)
        setSelectedId(nextSelectedId)
        setSelectedVersion(current => {
          if (nextSelected?.kind === 'living_report') return null
          return current && nextSelected?.versions?.some((v: ArtifactVersion) => v.version === current)
            ? current
            : nextSelected?.latest_version || null
        })
      })
      .catch((err) => {
        setArtifacts([])
        setSelectedId(null)
        setSelectedVersion(null)
        setError(err instanceof Error ? err.message : 'Could not load artifact library')
      })
      .finally(() => setLoading(false))
  }, [sessionId, selectedId])

  useEffect(() => { load() }, [load, refreshKey])

  const selected = useMemo(
    () => artifacts.find(a => a.artifact_id === selectedId) || null,
    [artifacts, selectedId],
  )
  const version = selectedVersion || selected?.latest_version || null
  const isLivingReport = selected?.kind === 'living_report'
  const versionExists = Boolean(
    isLivingReport ||
    !selected ||
    (version && (selected.versions || []).some(v => v.version === version)),
  )
  const artifactUrl = selected
    ? isLivingReport
      ? (selected.url || `${API}/artifacts/${selected.artifact_id}/living`)
      : version && versionExists ? `${API}/artifacts/${selected.artifact_id}?version=${version}` : ''
    : ''
  const exportUrl = selected && !isLivingReport && version ? `${API}/artifacts/${selected.artifact_id}/export?version=${version}` : ''
  const postTheme = useCallback(() => {
    const theme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    frameRef.current?.contentWindow?.postMessage({ theme }, '*')
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
  }, [postTheme])

  const onSelectArtifact = (artifactId: string) => {
    const artifact = artifacts.find(a => a.artifact_id === artifactId)
    setSelectedId(artifactId)
    setSelectedVersion(artifact?.kind === 'living_report' ? null : artifact?.latest_version || null)
  }

  if (!sessionId) return <Empty description="Select a session" image={Empty.PRESENTED_IMAGE_SIMPLE} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <FileDoneOutlined style={{ color: '#1677ff' }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#1f2937' }}>Artifact Library</span>
        <Tag style={{ marginLeft: 2, fontSize: 10 }}>{artifacts.length}</Tag>
        <Tooltip title="Refresh">
          <Button size="small" type="text" icon={<ReloadOutlined />} loading={loading && artifacts.length > 0} onClick={load} style={{ marginLeft: 'auto' }} />
        </Tooltip>
      </div>

      {error ? (
        <Alert type="error" showIcon message="Artifact library unavailable" description={error} />
      ) : loading && artifacts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : artifacts.length === 0 ? (
        <Empty description="No published artifacts yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <Select
            value={selected?.artifact_id}
            onChange={onSelectArtifact}
            style={{ width: '100%' }}
            options={artifacts.map(a => ({
              value: a.artifact_id,
              label: a.kind === 'living_report'
                ? `${a.title || a.artifact_id} · live`
                : `${a.title || a.artifact_id} · v${a.latest_version}`,
            }))}
          />

          {selected && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                {isLivingReport ? (
                  <Tag color="green" style={{ margin: 0 }}>live</Tag>
                ) : (
                  <Select
                    size="small"
                    value={version || undefined}
                    onChange={setSelectedVersion}
                    style={{ width: 120 }}
                    options={[...(selected.versions || [])].reverse().map(v => ({
                      value: v.version,
                      label: v.label ? `v${v.version} · ${v.label}` : `v${v.version}`,
                    }))}
                  />
                )}
                <Button size="small" icon={<ExportOutlined />} href={artifactUrl} target="_blank">Open</Button>
                {!isLivingReport && <Button size="small" icon={<DownloadOutlined />} href={exportUrl}>Export</Button>}
              </div>

              {selected.description && (
                <div style={{ fontSize: 12, color: '#667085', lineHeight: 1.5 }}>{selected.description}</div>
              )}
              {selected.source_path && (
                <div style={{ fontSize: 11, color: '#98a2b3', wordBreak: 'break-all' }}>
                  <code>{selected.source_path}</code>
                </div>
              )}

              {!versionExists ? (
                <Alert
                  type="warning"
                  showIcon
                  message="Artifact version unavailable"
                  description={`Version ${version || 'unknown'} is not present in this artifact's history.`}
                />
              ) : artifactUrl ? (
                <iframe
                  ref={frameRef}
                  title={isLivingReport ? `${selected.artifact_id} live` : `${selected.artifact_id} v${version}`}
                  src={artifactUrl}
                  sandbox="allow-scripts"
                  loading="lazy"
                  onLoad={postTheme}
                  style={{
                    width: '100%',
                    height: 620,
                    border: '1px solid #edf0f4',
                    borderRadius: 8,
                    background: '#fff',
                  }}
                />
              ) : (
                <Alert type="warning" showIcon message="Artifact URL unavailable" />
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function sortArtifacts(items: ArtifactRecord[]): ArtifactRecord[] {
  return [...items].sort((a, b) => {
    if (a.kind === 'living_report' && b.kind !== 'living_report') return -1
    if (a.kind !== 'living_report' && b.kind === 'living_report') return 1
    return String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
  })
}
