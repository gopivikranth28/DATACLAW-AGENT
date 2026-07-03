import type { CSSProperties } from 'react'
import { EyeOutlined, EyeInvisibleOutlined, UpOutlined, DownOutlined } from '@ant-design/icons'
import MetricDisplay, { type MetricData } from './tool-renderers/MetricDisplay'
import PlotlyRenderer, { type PlotlyFigure } from './tool-renderers/PlotlyRenderer'

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
export type AppItem = MetricItem | ChartItem

const CELL_OUTPUT_TOOLS = new Set(['execute_cell', 'display_cell_output', 'execute_code'])

// Item ids are sequence-based (metric-0, chart-1, ...). Session history is
// append-only, so ids stay stable as the session grows — which is what lets
// the saved layout survive reloads and apply on the published route.
export function collectAppItems(calls: AppCall[]): AppItem[] {
  const items: AppItem[] = []
  const chartByFigure = new Map<string, ChartItem>()
  let metricSeq = 0
  let chartSeq = 0

  for (const call of calls) {
    if (!call.result) continue
    let data: any
    try { data = JSON.parse(call.result) } catch { continue }

    if (call.name === 'display_metric' && data?.type === 'metric') {
      items.push({ id: `metric-${metricSeq++}`, kind: 'metric', metric: data })
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

  // Published (non-editable) view drops hidden items; editable view dims them
  // so the author can unhide.
  const visibleMetrics = editable ? metrics : metrics.filter(m => !hidden.has(m.id))
  const visibleCharts = editable ? charts : charts.filter(c => !hidden.has(c.id))

  if (visibleMetrics.length === 0 && visibleCharts.length === 0) {
    return (
      <div style={{ padding: 24, color: '#8c8c8c', fontSize: 13, textAlign: 'center' }}>
        No insights yet. Run an analysis to see metrics and charts here.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
