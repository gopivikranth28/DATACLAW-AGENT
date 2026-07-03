import type { ToolCallState } from '../hooks/useAGUI'
import MetricDisplay, { type MetricData } from './tool-renderers/MetricDisplay'
import PlotlyRenderer, { type PlotlyFigure } from './tool-renderers/PlotlyRenderer'

const CELL_OUTPUT_TOOLS = new Set(['execute_cell', 'display_cell_output', 'execute_code'])

interface ChartEntry {
  figure: PlotlyFigure
}

function collectInsights(toolCalls: ToolCallState[]): { metrics: MetricData[]; charts: ChartEntry[] } {
  const metrics: MetricData[] = []
  const charts: ChartEntry[] = []
  for (const tc of toolCalls) {
    if (!tc.result) continue
    let data: any
    try { data = JSON.parse(tc.result) } catch { continue }
    if (tc.name === 'display_metric' && data?.type === 'metric') {
      metrics.push(data)
    } else if (CELL_OUTPUT_TOOLS.has(tc.name) && Array.isArray(data?.outputs)) {
      for (const out of data.outputs) {
        if (out?.type === 'plotly' && out.figure) charts.push({ figure: out.figure })
      }
    }
  }
  return { metrics, charts }
}

export default function InsightsPanel({ toolCalls }: { toolCalls: ToolCallState[] }) {
  const { metrics, charts } = collectInsights(toolCalls)

  if (metrics.length === 0 && charts.length === 0) {
    return (
      <div style={{ padding: 24, color: '#8c8c8c', fontSize: 13, textAlign: 'center' }}>
        No insights yet. Run an analysis to see metrics and charts here.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {metrics.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {metrics.map((m, i) => <MetricDisplay key={i} data={m} />)}
        </div>
      )}
      {charts.map((c, i) => (
        <div key={i} style={{ border: '1px solid #f0f0f0', borderRadius: 8, overflow: 'hidden', background: '#fff' }}>
          <PlotlyRenderer figure={c.figure} />
        </div>
      ))}
    </div>
  )
}
