import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Select, Spin, Tag } from 'antd'
import { DownloadOutlined, ExportOutlined } from '@ant-design/icons'
import { API } from '../api'
import { reportDocumentUrl, reportPreviewUrl } from './reportPreview'

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

type ReportEntry =
  | { key: string; kind: 'artifact'; artifact: ArtifactRecord }
  | { key: string; kind: 'scratch'; report: ScratchReport }

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
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const lastAppliedFocusKeyRef = useRef<number | null>(null)

  useEffect(() => { selectedIdRef.current = selectedId }, [selectedId])

  const load = useCallback(() => {
    if (!sessionId) {
      setArtifacts([])
      setSelectedId(null)
      setSelectedVersion(null)
      setError(null)
      onCountsChange?.({ published: 0, scratch: 0 })
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
        const focusedId = shouldApplyFocus && focusArtifactId && next.some((a: ArtifactRecord) => a.artifact_id === focusArtifactId)
          ? artifactKey(focusArtifactId)
          : null
        const currentId = selectedIdRef.current && (
          next.some((a: ArtifactRecord) => artifactKey(a.artifact_id) === selectedIdRef.current) ||
          selectedIdRef.current.startsWith('scratch:')
        )
          ? selectedIdRef.current
          : null
        const nextSelectedId = focusedId || currentId || (next[0] ? artifactKey(next[0].artifact_id) : null)
        const nextSelected = next.find((a: ArtifactRecord) => artifactKey(a.artifact_id) === nextSelectedId) || null
        if (focusedId) lastAppliedFocusKeyRef.current = focusKey
        setArtifacts(next)
        setSelectedId(nextSelectedId)
        setSelectedVersion(current => {
          if (nextSelected?.kind === 'living_report') return null
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
        setSelectedId(null)
        setSelectedVersion(null)
        setError(formatArtifactLoadError(err))
        onCountsChange?.({ published: 0, scratch: 0 })
      })
      .finally(() => setLoading(false))
  }, [sessionId, focusArtifactId, focusVersion, focusKey, onCountsChange])

  useEffect(() => { load() }, [load, refreshKey])

  const visibleScratchReports = useMemo(
    () => uniqueScratchReports(scratchReports).filter(report => !artifacts.some(artifact => pathsMatch(artifact.source_path, report.htmlPath))),
    [artifacts, scratchReports],
  )
  const reportEntries = useMemo<ReportEntry[]>(() => [
    ...artifacts.map(artifact => ({ key: artifactKey(artifact.artifact_id), kind: 'artifact' as const, artifact })),
    ...visibleScratchReports.map(report => ({ key: scratchKey(report.id), kind: 'scratch' as const, report })),
  ], [artifacts, visibleScratchReports])
  const selectedEntry = useMemo(
    () => reportEntries.find(entry => entry.key === selectedId) || null,
    [reportEntries, selectedId],
  )
  const selected = selectedEntry?.kind === 'artifact' ? selectedEntry.artifact : null
  const selectedScratchReport = selectedEntry?.kind === 'scratch' ? selectedEntry.report : null

  useEffect(() => {
    if (reportEntries.length === 0) {
      setSelectedId(null)
      setSelectedVersion(null)
      return
    }
    if (!selectedEntry) {
      const next = reportEntries[0]
      selectedIdRef.current = next.key
      setSelectedId(next.key)
      setSelectedVersion(next.kind === 'artifact' && next.artifact.kind !== 'living_report' ? next.artifact.latest_version : null)
    }
  }, [reportEntries, selectedEntry])

  useEffect(() => {
    const livingCount = artifacts.filter(artifact => artifact.kind === 'living_report').length
    onCountsChange?.({ published: artifacts.length - livingCount, scratch: livingCount + visibleScratchReports.length })
  }, [artifacts, visibleScratchReports, onCountsChange])

  const version = selectedVersion || selected?.latest_version || null
  const isLivingReport = selected?.kind === 'living_report'
  const selectedSessionId = selected?.session_id || sessionId || 'default'
  const versionExists = Boolean(
    selectedScratchReport ||
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
  const exportUrl = selected && !isLivingReport && version ? artifactExportUrl(selected.artifact_id, version, selectedSessionId) : ''
  const scratchDocumentUrl = selectedScratchReport
    ? reportDocumentUrl(selectedScratchReport.htmlPath, selectedScratchReport.updatedAt, { sessionId })
    : ''
  const scratchOpenUrl = selectedScratchReport
    ? reportPreviewUrl(selectedScratchReport.htmlPath, { sessionId })
    : ''
  const previewUrl = scratchDocumentUrl || artifactUrl
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

  const onSelectReport = (key: string) => {
    const entry = reportEntries.find(item => item.key === key)
    selectedIdRef.current = key
    setSelectedId(key)
    setSelectedVersion(entry?.kind === 'artifact' && entry.artifact.kind !== 'living_report' ? entry.artifact.latest_version : null)
  }

  if (!sessionId) return <Empty description="Select a session" image={Empty.PRESENTED_IMAGE_SIMPLE} />

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {error ? (
        <Alert type="error" showIcon message="Artifact library unavailable" description={error} />
      ) : loading && artifacts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
      ) : reportEntries.length === 0 ? (
        <Empty description="No reports yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <>
          <div style={{ padding: '6px 8px', border: '1px solid #e7ecf3', borderRadius: 7, background: '#fafcff', fontSize: 10.5, color: '#667085', lineHeight: 1.35 }}>
            Published reports are versioned. Scratch reports are session drafts.
          </div>

          {reportEntries.length > 0 && <Select
            className="dataclaw-report-picker"
            data-testid="report-picker"
            size="small"
            value={selectedEntry?.key}
            onChange={onSelectReport}
            style={{ width: '100%', minWidth: 0 }}
            options={reportEntries.map(entry => ({
              value: entry.key,
              label: entry.kind === 'scratch'
                ? `${entry.report.title || entry.report.htmlPath.split('/').pop()} · draft`
                : entry.artifact.kind === 'living_report'
                  ? `${entry.artifact.title || entry.artifact.artifact_id} · scratch`
                  : `${entry.artifact.title || entry.artifact.artifact_id} · v${entry.artifact.latest_version}`,
            }))}
          />}

          {selectedEntry && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
                {selectedScratchReport ? (
                  <Tag color="blue" style={{ margin: 0, fontSize: 10 }}>draft</Tag>
                ) : isLivingReport ? (
                  <Tag color="green" style={{ margin: 0, fontSize: 10 }}>live</Tag>
                ) : (
                  <Select
                    className="dataclaw-report-version"
                    size="small"
                    value={version || undefined}
                    onChange={setSelectedVersion}
                    style={{ width: 105 }}
                    options={[...(selected?.versions || [])].reverse().map(v => ({
                      value: v.version,
                      label: v.label ? `v${v.version} · ${v.label}` : `v${v.version}`,
                    }))}
                  />
                )}
                <Button size="small" icon={<ExportOutlined />} href={scratchOpenUrl || artifactUrl} target="_blank" style={{ height: 28, paddingInline: 9, fontSize: 11 }}>Open</Button>
                {selected && !isLivingReport && <Button size="small" icon={<DownloadOutlined />} href={exportUrl} style={{ height: 28, paddingInline: 9, fontSize: 11 }}>Export</Button>}
              </div>

              {selected?.description && (
                <div data-testid="report-description" title={selected.description} style={{ fontSize: 10.5, color: '#667085', lineHeight: 1.4 }}>{selected.description}</div>
              )}
              {selected?.source_path && (
                <div title={selected.source_path} style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 9.5, color: '#98a2b3' }}>
                  <code style={{ fontSize: 'inherit' }}>{selected.source_path}</code>
                </div>
              )}
              {selectedScratchReport && (
                <div title={selectedScratchReport.htmlPath} style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 9.5, color: '#98a2b3' }}>
                  <code style={{ fontSize: 'inherit' }}>{selectedScratchReport.htmlPath}</code>
                </div>
              )}

              {!versionExists ? (
                <Alert
                  type="warning"
                  showIcon
                  message="Artifact version unavailable"
                  description={`Version ${version || 'unknown'} is not present in this artifact's history.`}
                />
              ) : previewUrl ? (
                <iframe
                  data-testid={selectedScratchReport ? 'scratch-report-preview-frame' : isLivingReport ? 'living-report-preview-frame' : 'artifact-preview-frame'}
                  ref={frameRef}
                  title={selectedScratchReport ? selectedScratchReport.title || selectedScratchReport.htmlPath : isLivingReport ? `${selected?.artifact_id} live` : `${selected?.artifact_id} v${version}`}
                  src={previewUrl}
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
          )}
        </>
      )}
    </div>
  )
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

function artifactKey(artifactId: string): string {
  return `artifact:${artifactId}`
}

function scratchKey(reportId: string): string {
  return `scratch:${reportId}`
}

function normalizePath(path?: string): string {
  return String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')
}

function pathsMatch(left?: string, right?: string): boolean {
  const a = normalizePath(left)
  const b = normalizePath(right)
  if (!a || !b) return false
  if (a === b) return true
  const aIsAbsolute = /^\//.test(a) || /^[A-Za-z]:\//.test(a)
  const bIsAbsolute = /^\//.test(b) || /^[A-Za-z]:\//.test(b)
  return (!aIsAbsolute && b.endsWith(`/${a}`)) || (!bIsAbsolute && a.endsWith(`/${b}`))
}

function uniqueScratchReports(reports: ScratchReport[]): ScratchReport[] {
  const byPath = new Map<string, ScratchReport>()
  for (const report of reports) {
    if (!report?.htmlPath) continue
    const key = normalizePath(report.htmlPath)
    const existing = byPath.get(key)
    if (!existing || String(report.updatedAt || '').localeCompare(String(existing.updatedAt || '')) > 0) {
      byPath.set(key, report)
    }
  }
  return [...byPath.values()].sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))
}
