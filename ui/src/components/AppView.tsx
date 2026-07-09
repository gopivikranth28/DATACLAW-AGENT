import type { CSSProperties } from 'react'
import { EyeOutlined, EyeInvisibleOutlined, UpOutlined, DownOutlined } from '@ant-design/icons'
import MetricDisplay, { type MetricData } from './tool-renderers/MetricDisplay'
import PlotlyRenderer, { type PlotlyFigure } from './tool-renderers/PlotlyRenderer'
import { reportDocumentUrl, reportPreviewUrl } from './reportPreview'

export interface AppCall {
  name: string
  result: string | null
}

export interface AppLayout {
  hidden: string[]
  order: string[]
}

interface MetricItem { id: string; kind: 'metric'; metric: MetricData }
interface ChartItem { id: string; kind: 'chart'; figure: PlotlyFigure; caption?: string }
interface ReportItem { id: string; kind: 'report'; htmlPath: string; title?: string; updatedAt?: string }
export type AppItem = MetricItem | ChartItem | ReportItem

export interface VisualArtifact {
  id: string
  kind: 'metric' | 'chart' | 'report'
  metric?: MetricData
  figure?: PlotlyFigure
  caption?: string
  html_path?: string
  title?: string
  updated_at?: string
}

const CELL_OUTPUT_TOOLS = new Set(['execute_cell', 'display_cell_output', 'execute_code'])
const REPORT_TOOLS = new Set(['build_report', 'report_add_section'])

// Item ids are sequence-based (metric-0, chart-1, ...). Session history is
// append-only, so ids stay stable as the session grows — which lets saved
// compatibility-view layout survive reloads.
export function collectAppItems(calls: AppCall[]): AppItem[] {
  const items: AppItem[] = []
  const chartByFigure = new Map<string, ChartItem>()
  const reportByPath = new Map<string, ReportItem>()
  let metricSeq = 0
  let chartSeq = 0

  for (const call of calls) {
    if (!call.result) continue
    let data: any
    try { data = JSON.parse(call.result) } catch { continue }

    if (call.name === 'display_metric' && data?.type === 'metric') {
      items.push({ id: `metric-${metricSeq++}`, kind: 'metric', metric: data })
    } else if (REPORT_TOOLS.has(call.name) && data?.html_path) {
      const item: ReportItem = {
        id: `report-${data.html_path}`,
        kind: 'report',
        htmlPath: data.html_path,
        title: data.title || data.html_path.split('/').pop(),
        updatedAt: String(data.size ?? Date.now()),
      }
      const existing = reportByPath.get(data.html_path)
      if (existing) {
        existing.title = item.title || existing.title
        existing.updatedAt = item.updatedAt
      } else {
        reportByPath.set(data.html_path, item)
        items.push(item)
      }
    } else if (CELL_OUTPUT_TOOLS.has(call.name) && Array.isArray(data?.outputs)) {
      const caption = typeof data.caption === 'string' && data.caption ? data.caption : undefined
      for (const out of data.outputs) {
        if (out?.type !== 'plotly' || !out.figure) continue
        // Re-executions and display_cell_output re-show the same figure —
        // dedupe by trace data, but let a captioned re-display enrich the
        // original (display_cell_output is how the agent attaches captions).
        const key = JSON.stringify(out.figure.data)
        const existing = chartByFigure.get(key)
        if (existing) {
          if (caption && !existing.caption) existing.caption = caption
          continue
        }
        const item: ChartItem = { id: `chart-${chartSeq++}`, kind: 'chart', figure: out.figure, caption }
        chartByFigure.set(key, item)
        items.push(item)
      }
    }
  }
  return items
}

export function itemsFromVisualArtifacts(artifacts?: VisualArtifact[] | null): AppItem[] {
  if (!artifacts?.length) return []
  const items: AppItem[] = []
  for (const artifact of artifacts) {
    if (artifact.kind === 'metric' && artifact.metric) {
      items.push({ id: artifact.id, kind: 'metric', metric: artifact.metric })
    } else if (artifact.kind === 'chart' && artifact.figure) {
      items.push({
        id: artifact.id,
        kind: 'chart',
        figure: artifact.figure,
        caption: artifact.caption,
      })
    } else if (artifact.kind === 'report' && artifact.html_path) {
      items.push({
        id: artifact.id,
        kind: 'report',
        htmlPath: artifact.html_path,
        title: artifact.title,
        updatedAt: artifact.updated_at,
      })
    }
  }
  return items
}

function appItemPayloadKey(item: AppItem): string {
  if (item.kind === 'metric') return `metric:${JSON.stringify(item.metric)}`
  if (item.kind === 'report') return `report:${item.htmlPath}`
  return `chart:${JSON.stringify(item.figure.data)}`
}

export function mergeAppItems(primary: AppItem[], fallback: AppItem[]): AppItem[] {
  if (primary.length === 0) return dedupeAppItems(fallback)
  const seen = new Set(primary.map(appItemPayloadKey))
  const merged = [...primary]
  for (const item of fallback) {
    const key = appItemPayloadKey(item)
    if (seen.has(key)) {
      const idx = merged.findIndex(existing => appItemPayloadKey(existing) === key)
      if (idx >= 0 && merged[idx].kind === 'report' && item.kind === 'report') merged[idx] = item
      continue
    }
    seen.add(key)
    merged.push(item)
  }
  return merged
}

function dedupeAppItems(items: AppItem[]): AppItem[] {
  const seen = new Set<string>()
  const deduped: AppItem[] = []
  for (const item of items) {
    const key = appItemPayloadKey(item)
    if (seen.has(key)) {
      const idx = deduped.findIndex(existing => appItemPayloadKey(existing) === key)
      if (idx >= 0 && deduped[idx].kind === 'report' && item.kind === 'report') deduped[idx] = item
      continue
    }
    seen.add(key)
    deduped.push(item)
  }
  return deduped
}

function orderCharts(charts: ChartItem[], order?: string[]): ChartItem[] {
  if (!order || order.length === 0) return charts
  const pos = new Map(order.map((id, i) => [id, i]))
  return charts
    .map((c, i) => ({ c, rank: pos.has(c.id) ? pos.get(c.id)! : order.length + i }))
    .sort((a, b) => a.rank - b.rank)
    .map(({ c }) => c)
}

const CONTROL_STYLE: CSSProperties = {
  cursor: 'pointer', color: '#999', fontSize: 12, padding: 2,
}

export default function AppView({ items, layout, editable = false, onLayoutChange }: {
  items: AppItem[]
  layout?: AppLayout | null
  editable?: boolean
  onLayoutChange?: (layout: AppLayout) => void
}) {
  const hidden = new Set(layout?.hidden ?? [])
  const reports = items.filter((i): i is ReportItem => i.kind === 'report')
  const metrics = items.filter((i): i is MetricItem => i.kind === 'metric')
  const charts = orderCharts(items.filter((i): i is ChartItem => i.kind === 'chart'), layout?.order)

  const emit = (nextHidden: Set<string>, nextCharts: ChartItem[]) => {
    onLayoutChange?.({ hidden: [...nextHidden], order: nextCharts.map(c => c.id) })
  }

  const toggleHide = (id: string) => {
    const next = new Set(hidden)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    emit(next, charts)
  }

  const moveChart = (id: string, dir: -1 | 1) => {
    const idx = charts.findIndex(c => c.id === id)
    const target = idx + dir
    if (idx < 0 || target < 0 || target >= charts.length) return
    const next = [...charts]
    ;[next[idx], next[target]] = [next[target], next[idx]]
    emit(hidden, next)
  }

  // Read-only compatibility view drops hidden items; editable view dims them
  // so the author can unhide.
  const visibleReports = editable ? reports : reports.filter(r => !hidden.has(r.id))
  const visibleMetrics = editable ? metrics : metrics.filter(m => !hidden.has(m.id))
  const visibleCharts = editable ? charts : charts.filter(c => !hidden.has(c.id))

  if (visibleReports.length === 0 && visibleMetrics.length === 0 && visibleCharts.length === 0) {
    return (
      <div style={{ padding: 24, color: '#8c8c8c', fontSize: 13, textAlign: 'center' }}>
        No insights yet. Run an analysis to see metrics and charts here.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {visibleReports.map(r => (
        <div key={r.id} style={{
          position: 'relative', border: '1px solid #e5e7eb', borderRadius: 10,
          overflow: 'hidden', background: '#f5f6f8', opacity: hidden.has(r.id) ? 0.35 : 1,
        }}>
          {editable && (
            <span onClick={() => toggleHide(r.id)} title={hidden.has(r.id) ? 'Show' : 'Hide'}
              style={{ ...CONTROL_STYLE, position: 'absolute', top: 8, right: 8, zIndex: 2, background: '#fff', borderRadius: 4 }}>
              {hidden.has(r.id) ? <EyeOutlined /> : <EyeInvisibleOutlined />}
            </span>
          )}
          <ReportFrame htmlPath={r.htmlPath} title={r.title} updatedAt={r.updatedAt} />
        </div>
      ))}
      {visibleMetrics.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {visibleMetrics.map(m => (
            <div key={m.id} style={{ position: 'relative', opacity: hidden.has(m.id) ? 0.35 : 1 }}>
              <MetricDisplay data={m.metric} />
              {editable && (
                <span onClick={() => toggleHide(m.id)} title={hidden.has(m.id) ? 'Show' : 'Hide'}
                  style={{ ...CONTROL_STYLE, position: 'absolute', top: 4, right: 4 }}>
                  {hidden.has(m.id) ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {visibleCharts.map((c, i) => (
        <div key={c.id} style={{
          border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden',
          background: '#fff', opacity: hidden.has(c.id) ? 0.35 : 1,
        }}>
          {editable && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, padding: '4px 8px 0' }}>
              <span onClick={() => moveChart(c.id, -1)} title="Move up"
                style={{ ...CONTROL_STYLE, visibility: i > 0 ? 'visible' : 'hidden' }}><UpOutlined /></span>
              <span onClick={() => moveChart(c.id, 1)} title="Move down"
                style={{ ...CONTROL_STYLE, visibility: i < visibleCharts.length - 1 ? 'visible' : 'hidden' }}><DownOutlined /></span>
              <span onClick={() => toggleHide(c.id)} title={hidden.has(c.id) ? 'Show' : 'Hide'} style={CONTROL_STYLE}>
                {hidden.has(c.id) ? <EyeOutlined /> : <EyeInvisibleOutlined />}
              </span>
            </div>
          )}
          <PlotlyRenderer figure={c.figure} caption={c.caption} />
        </div>
      ))}
    </div>
  )
}

function ReportFrame({ htmlPath, title, updatedAt }: { htmlPath: string; title?: string; updatedAt?: string }) {
  const openUrl = reportPreviewUrl(htmlPath)
  const documentUrl = reportDocumentUrl(htmlPath, updatedAt)

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', background: '#fff', borderBottom: '1px solid #e5e7eb',
      }}>
        <div style={{ fontSize: 13, fontWeight: 650, color: '#1f2937' }}>{title || 'Report'}</div>
        <a href={openUrl} target="_blank" rel="noreferrer"
          style={{ fontSize: 12, color: '#2563eb' }}>Open</a>
      </div>
      <iframe
        data-testid="report-preview-frame"
        src={documentUrl}
        title={title || 'Report'}
        sandbox="allow-scripts allow-forms allow-popups allow-modals"
        style={{ width: '100%', minHeight: 760, border: 0, display: 'block', background: '#f5f6f8' }}
      />
    </div>
  )
}
