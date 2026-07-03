import { useEffect, useRef } from 'react'
import * as Plotly from 'plotly.js-dist-min'

export interface PlotlyFigure {
  data: any[]
  layout?: Record<string, any>
  config?: Record<string, any>
}

export default function PlotlyRenderer({ figure, caption }: { figure: PlotlyFigure; caption?: string }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    Plotly.react(
      el,
      figure.data || [],
      {
        ...figure.layout,
        autosize: true,
        margin: figure.layout?.margin ?? { l: 40, r: 20, t: 40, b: 40 },
      },
      { responsive: true, displayModeBar: true, displaylogo: false, ...figure.config },
    )
    // `responsive: true` only tracks window resize; observe the container so
    // charts also reflow when the sidebar is dragged or a panel toggles.
    const observer = new ResizeObserver(() => Plotly.Plots.resize(el))
    observer.observe(el)
    return () => {
      observer.disconnect()
      Plotly.purge(el)
    }
  }, [figure])

  return (
    <div>
      <div ref={ref} style={{ width: '100%', minHeight: 360 }} />
      {caption && <div style={{ fontSize: 11, color: '#666', fontStyle: 'italic', margin: '4px 0 0', padding: '0 8px 8px' }}>{caption}</div>}
    </div>
  )
}
