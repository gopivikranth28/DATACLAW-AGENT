import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Empty, Select, Spin, Tag, Tooltip } from 'antd'
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
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)

  const load = useCallback(() => {
    if (!sessionId) {
      setArtifacts([])
      setSelectedId(null)
      setSelectedVersion(null)
      return
    }
    setLoading(true)
    fetch(`${API}/artifacts?session_id=${encodeURIComponent(sessionId)}`)
      .then(r => r.ok ? r.json() : { artifacts: [] })
      .then(data => {
        const next = Array.isArray(data.artifacts) ? data.artifacts : []
        setArtifacts(next)
        setSelectedId(current => current && next.some((a: ArtifactRecord) => a.artifact_id === current)
          ? current
          : next[0]?.artifact_id || null)
        setSelectedVersion(current => {
          const selected = next.find((a: ArtifactRecord) => a.artifact_id === selectedId) || next[0]
          if (selected?.kind === 'living_report') return null
          return current && selected?.versions?.some((v: ArtifactVersion) => v.version === current)
            ? current
            : selected?.latest_version || null
        })
      })
      .catch(() => setArtifacts([]))
      .finally(() => setLoading(false))
  }, [sessionId, selectedId])

  useEffect(() => { load() }, [load, refreshKey])

  const selected = useMemo(
    () => artifacts.find(a => a.artifact_id === selectedId) || null,
    [artifacts, selectedId],
  )
  const version = selectedVersion || selected?.latest_version || null
  const isLivingReport = selected?.kind === 'living_report'
  const artifactUrl = selected
    ? isLivingReport
      ? (selected.url || `${API}/artifacts/${selected.artifact_id}/living`)
      : version ? `${API}/artifacts/${selected.artifact_id}?version=${version}` : ''
    : ''
  const exportUrl = selected && !isLivingReport && version ? `${API}/artifacts/${selected.artifact_id}/export?version=${version}` : ''

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
          <Button size="small" type="text" icon={<ReloadOutlined />} onClick={load} style={{ marginLeft: 'auto' }} />
        </Tooltip>
      </div>

      {loading && artifacts.length === 0 ? (
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

              <iframe
                title={`${selected.artifact_id} v${version}`}
                src={artifactUrl}
                sandbox="allow-scripts"
                loading="lazy"
                style={{
                  width: '100%',
                  height: 620,
                  border: '1px solid #edf0f4',
                  borderRadius: 8,
                  background: '#fff',
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}
