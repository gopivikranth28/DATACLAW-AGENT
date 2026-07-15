import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Select, Spin, Tag, Tooltip } from 'antd'
import { DownloadOutlined, ExportOutlined, ReloadOutlined } from '@ant-design/icons'
import { API } from '../api'
import { reportPreviewUrl } from './reportPreview'

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
  session_id?: string
  latest_version: number
  versions: ArtifactVersion[]
  source_path?: string
  updated_at?: string
  url?: string
}

interface ScratchReport {
  id: string
  htmlPath: string
  title?: string
  updatedAt?: string
}

interface ReportCounts {
  published: number
  scratch: number
}

export default function ArtifactPanel({
  sessionId,
  refreshKey = 0,
  focusArtifactId = null,
  focusVersion = null,
  focusKey = 0,
  scratchReports = [],
  onCountsChange,
}: {
  sessionId: string | null
  refreshKey?: number
  focusArtifactId?: string | null
  focusVersion?: number | null
  focusKey?: number
  scratchReports?: ScratchReport[]
  onCountsChange?: (counts: ReportCounts) => void
}) {
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const selectedKeyRef = useRef<string | null>(null)
  const lastAppliedFocusKeyRef = useRef<number | null>(null)

  useEffect(() => { selectedKeyRef.current = selectedKey }, [selectedKey])

  const load = useCallback(() => {
    if (!sessionId) {
      setArtifacts([])
      setSelectedKey(null)
      setSelectedVersion(null)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    const requestUrl = apiUrl('/artifacts', { session_id: sessionId })
    fetch(requestUrl, { headers: { Accept: 'application/json' } })
      .then(async r => {
        const text = await r.text()
        let payload: any = null
        try {
          payload = text ? JSON.parse(text) : {}
        } catch {
          throw new Error(
            r.ok
              ? 'Artifacts API returned non-JSON. Restart Dataclaw so plugin routes register, then refresh.'
              : `Artifact library failed with ${r.status}`,
          )
        }
        if (!r.ok) {
          const detail = typeof payload?.detail === 'string' ? payload.detail : ''
          throw new Error(detail ? `Artifact library failed with ${r.status}: ${detail}` : `Artifact library failed with ${r.status}`)
        }
        return payload
      })
      .then(data => {
        const next = sortArtifacts(Array.isArray(data.artifacts) ? data.artifacts : [])
        const shouldApplyFocus = Boolean(focusArtifactId && lastAppliedFocusKeyRef.current !== focusKey)
        const focusedId = shouldApplyFocus && next.some((a: ArtifactRecord) => a.artifact_id === focusArtifactId)
          ? focusArtifactId
          : null
        const currentKey = selectedKeyRef.current
        const currentArtifactId = currentKey?.startsWith('artifact:') ? currentKey.slice('artifact:'.length) : null
        const currentId = currentArtifactId && next.some((a: ArtifactRecord) => a.artifact_id === currentArtifactId)
          ? currentArtifactId
          : null
        const nextSelectedKey = focusedId
          ? `artifact:${focusedId}`
          : currentKey?.startsWith('scratch:')
            ? currentKey
            : currentId
              ? `artifact:${currentId}`
              : next[0]?.artifact_id
                ? `artifact:${next[0].artifact_id}`
                : null
        const nextSelectedId = nextSelectedKey?.startsWith('artifact:') ? nextSelectedKey.slice('artifact:'.length) : null
        const nextSelected = next.find((a: ArtifactRecord) => a.artifact_id === nextSelectedId) || null
        if (focusedId) lastAppliedFocusKeyRef.current = focusKey
        setArtifacts(next)
        selectedKeyRef.current = nextSelectedKey
        setSelectedKey(nextSelectedKey)
        setSelectedVersion(current => {
          if (!nextSelected || nextSelected.kind === 'living_report') return null
          if (focusedId && focusVersion && nextSelected?.versions?.some((v: ArtifactVersion) => v.version === focusVersion)) {
            return focusVersion
          }
          return current && nextSelected?.versions?.some((v: ArtifactVersion) => v.version === current)
            ? current
            : nextSelected?.latest_version || null
        })
      })
      .catch((err) => {
        setArtifacts([])
        setSelectedKey(current => current?.startsWith('scratch:') ? current : null)
        setSelectedVersion(null)
        setError(formatArtifactLoadError(err))
      })
      .finally(() => setLoading(false))
  }, [sessionId, focusArtifactId, focusVersion, focusKey])

  useEffect(() => { load() }, [load, refreshKey])

  const publishedArtifacts = useMemo(() => artifacts.filter(artifact => artifact.kind !== 'living_report'), [artifacts])
  const livingReports = useMemo(() => artifacts.filter(artifact => artifact.kind === 'living_report'), [artifacts])
  const workspaceScratchReports = useMemo(() => {
    const livingIds = new Set(livingReports.map(report => report.artifact_id))
    const livingPaths = new Set(livingReports.map(report => report.source_path).filter(Boolean))
    return [...scratchReports]
      .filter(report => !livingIds.has(report.id) && !livingPaths.has(report.htmlPath))
      .sort((left, right) => String(right.updatedAt || '').localeCompare(String(left.updatedAt || '')))
  }, [livingReports, scratchReports])
  const reportOptions = useMemo(() => [
    ...artifacts.map(artifact => ({
      value: `artifact:${artifact.artifact_id}`,
      label: artifact.kind === 'living_report'
        ? `${artifact.title || artifact.artifact_id} · scratch`
        : `${artifact.title || artifact.artifact_id} · published · v${artifact.latest_version}`,
    })),
    ...workspaceScratchReports.map(report => ({
      value: `scratch:${report.id}`,
      label: `${report.title || report.htmlPath.split('/').pop() || report.id} · scratch`,
    })),
  ], [artifacts, workspaceScratchReports])
  const selectedArtifactId = selectedKey?.startsWith('artifact:') ? selectedKey.slice('artifact:'.length) : null
  const selectedScratchId = selectedKey?.startsWith('scratch:') ? selectedKey.slice('scratch:'.length) : null
  const selected = useMemo(
    () => artifacts.find(artifact => artifact.artifact_id === selectedArtifactId) || null,
    [artifacts, selectedArtifactId],
  )
  const selectedScratch = useMemo(
    () => workspaceScratchReports.find(report => report.id === selectedScratchId) || null,
    [workspaceScratchReports, selectedScratchId],
  )

  useEffect(() => {
    const available = new Set(reportOptions.map(option => option.value))
    if (selectedKey && available.has(selectedKey)) return
    const nextKey = reportOptions[0]?.value || null
    selectedKeyRef.current = nextKey
    setSelectedKey(nextKey)
    if (nextKey?.startsWith('scratch:')) setSelectedVersion(null)
  }, [reportOptions, selectedKey])

  useEffect(() => {
    onCountsChange?.(sessionId ? {
      published: publishedArtifacts.length,
      scratch: livingReports.length + workspaceScratchReports.length,
    } : { published: 0, scratch: 0 })
  }, [livingReports.length, onCountsChange, publishedArtifacts.length, sessionId, workspaceScratchReports.length])

  const version = selectedVersion || selected?.latest_version || null
  const isLivingReport = selected?.kind === 'living_report'
  const isScratchReport = Boolean(isLivingReport || selectedScratch)
  const selectedSessionId = selected?.session_id || sessionId || 'default'
  const versionExists = Boolean(
    selectedScratch ||
    isLivingReport ||
    !selected ||
    (version && (selected.versions || []).some(v => v.version === version)),
  )
  const artifactUrl = selected
    ? isLivingReport
      ? toApiUrl(selected.url || livingReportUrl(selected.artifact_id, selectedSessionId))
      : version && versionExists ? toApiUrl(
        selected.url && version === selected.latest_version
          ? selected.url
          : artifactVersionUrl(selected.artifact_id, version, selectedSessionId),
      ) : ''
    : ''
  const reportUrl = selectedScratch ? reportPreviewUrl(selectedScratch.htmlPath) : artifactUrl
  const exportUrl = selected && !isLivingReport && version ? artifactExportUrl(selected.artifact_id, version, selectedSessionId) : ''
  const selectedDescription = selected?.description || ''
  const selectedPath = selectedScratch?.htmlPath || selected?.source_path || ''
  const selectedUpdatedAt = selectedScratch?.updatedAt || selected?.updated_at || ''
  const selectedUpdatedLabel = formatReportTime(selectedUpdatedAt)
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

  const onSelectReport = (selectionKey: string) => {
    selectedKeyRef.current = selectionKey
    setSelectedKey(selectionKey)
    if (selectionKey.startsWith('scratch:')) {
      setSelectedVersion(null)
      return
    }
    const artifactId = selectionKey.slice('artifact:'.length)
    const artifact = artifacts.find(item => item.artifact_id === artifactId)
    setSelectedVersion(artifact?.kind === 'living_report' ? null : artifact?.latest_version || null)
  }

  if (!sessionId) return <Empty description="Select a session" image={Empty.PRESENTED_IMAGE_SIMPLE} />

  return (
    <div aria-label="Report library controls" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', minWidth: 0, alignItems: 'center', gap: 5, minHeight: 28 }}>
        {reportOptions.length > 0 && <Select
          aria-label="Select report"
          value={selectedKey || undefined}
          onChange={onSelectReport}
          showSearch
          optionFilterProp="label"
          style={{ flex: '1 1 auto', minWidth: 0 }}
          options={reportOptions}
        />}
        <Tooltip title="Refresh">
          <Button size="small" type="text" icon={<ReloadOutlined />} loading={loading && artifacts.length > 0} onClick={load} aria-label="Refresh reports" style={{ flex: '0 0 auto', marginLeft: 'auto', paddingInline: 3 }} />
        </Tooltip>
      </div>

      {error && <Alert type="error" showIcon message="Published report library unavailable" description={error} />}
      {loading && artifacts.length === 0 && workspaceScratchReports.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : reportOptions.length === 0 ? (
        error ? null : <Empty description="No reports yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (selected || selectedScratch) ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', minWidth: 0, gap: 6, alignItems: 'center' }}>
            {isScratchReport ? (
              <Tag color="blue" style={{ flex: '0 0 auto', margin: 0 }}>scratch</Tag>
            ) : (
              <Select
                size="small"
                aria-label="Select report version"
                value={version || undefined}
                onChange={setSelectedVersion}
                style={{ flex: '0 1 150px', minWidth: 90 }}
                options={[...(selected?.versions || [])].reverse().map(v => ({
                  value: v.version,
                  label: v.label ? `v${v.version} · ${v.label}` : `v${v.version}`,
                }))}
              />
            )}
            {selectedUpdatedLabel && <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#98a2b3', fontSize: 11 }}>{selectedUpdatedLabel}</span>}
            <div style={{ display: 'flex', alignItems: 'center', gap: 2, marginLeft: 'auto' }}>
              <Tooltip title="Open report in a new tab">
                <Button size="small" type="text" icon={<ExportOutlined />} href={reportUrl} target="_blank" aria-label="Open selected report" style={{ paddingInline: 5 }} />
              </Tooltip>
              {exportUrl && <Tooltip title="Export selected report version">
                <Button size="small" type="text" icon={<DownloadOutlined />} href={exportUrl} aria-label="Export selected report" style={{ paddingInline: 5 }} />
              </Tooltip>}
            </div>
          </div>

          {selectedDescription && (
            <Tooltip title={<div style={{ maxWidth: 420, whiteSpace: 'normal' }}>{selectedDescription}</div>} placement="bottomLeft">
              <div tabIndex={0} aria-label={`Update: ${selectedDescription}`} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12.5, color: '#667085', lineHeight: 1.4, cursor: 'help' }}>
                <b style={{ color: '#475467' }}>Update</b> · {selectedDescription}
              </div>
            </Tooltip>
          )}
          {selectedPath && (
            <Tooltip title={<code style={{ wordBreak: 'break-all' }}>{selectedPath}</code>} placement="bottomLeft">
              <div tabIndex={0} aria-label={`File path: ${selectedPath}`} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11.5, color: '#98a2b3', cursor: 'help' }}>
                <code>{compactReportPath(selectedPath)}</code>
              </div>
            </Tooltip>
          )}

          {!versionExists ? (
            <Alert
              type="warning"
              showIcon
              message="Artifact version unavailable"
              description={`Version ${version || 'unknown'} is not present in this artifact's history.`}
            />
          ) : reportUrl ? (
            <iframe
              data-testid={selectedScratch ? 'scratch-report-preview-frame' : isLivingReport ? 'living-report-preview-frame' : 'artifact-preview-frame'}
              ref={frameRef}
              title={selectedScratch ? `${selectedScratch.title || selectedScratch.id} scratch` : isLivingReport ? `${selected?.artifact_id} live` : `${selected?.artifact_id} v${version}`}
              src={reportUrl}
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
            <Alert type="warning" showIcon message="Report URL unavailable" />
          )}
        </div>
      ) : (
        <Empty description="Choose a report" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </div>
  )
}

function compactReportPath(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/').filter(Boolean)
  if (parts.length <= 2) return path
  return `…/${parts.slice(-2).join('/')}`
}

function formatReportTime(value: string): string {
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 1_000_000_000
    ? new Date(numeric < 1_000_000_000_000 ? numeric * 1000 : numeric)
    : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function artifactVersionUrl(artifactId: string, version: number, sessionId: string): string {
  return apiUrl(`/artifacts/${artifactId}`, { version, session_id: sessionId || 'default' })
}

function artifactExportUrl(artifactId: string, version: number, sessionId: string): string {
  return apiUrl(`/artifacts/${artifactId}/export`, { version, session_id: sessionId || 'default' })
}

function livingReportUrl(artifactId: string, sessionId: string): string {
  return apiUrl(`/artifacts/${artifactId}/living`, { session_id: sessionId || 'default' })
}

function toApiUrl(url: string): string {
  if (!url) return ''
  if (/^https?:\/\//i.test(url)) return url
  if (url.startsWith('/api/')) return apiUrl(url.slice('/api'.length))
  if (url.startsWith('/')) return apiUrl(url)
  return apiUrl(`/${url}`)
}

function apiUrl(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): string {
  const base = (API || '/api').replace(/\/+$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return
    query.set(key, String(value))
  })
  const raw = `${base}${normalizedPath}${query.toString() ? `?${query.toString()}` : ''}`
  try {
    return new URL(raw, window.location.href).toString()
  } catch {
    return raw
  }
}

function formatArtifactLoadError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err || '')
  if (message === 'The string did not match the expected pattern.') {
    return 'Artifacts API request could not be built by the browser. Refresh the Dataclaw UI; if this persists, restart Dataclaw so the current frontend and backend are served together.'
  }
  return message || 'Could not load artifact library'
}

function sortArtifacts(items: ArtifactRecord[]): ArtifactRecord[] {
  return [...items].sort((a, b) => {
    if (a.kind === 'living_report' && b.kind !== 'living_report') return 1
    if (a.kind !== 'living_report' && b.kind === 'living_report') return -1
    return String(b.updated_at || '').localeCompare(String(a.updated_at || ''))
  })
}
