import { useEffect, useRef, useState } from 'react'

export interface PlotlyFigure {
  data: any[]
  layout?: Record<string, any>
  config?: Record<string, any>
}

type PlotlyModule = typeof import('plotly.js-dist-min')

let plotlyPromise: Promise<PlotlyModule> | null = null

function loadPlotly(): Promise<PlotlyModule> {
  plotlyPromise ||= import('plotly.js-dist-min')
  return plotlyPromise
}

export default function PlotlyRenderer({ figure, caption }: { figure: PlotlyFigure; caption?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let observer: ResizeObserver | null = null
    let renderedEl: HTMLDivElement | null = null
    let plotly: PlotlyModule | null = null

    setLoadError(null)
    loadPlotly()
      .then((loadedPlotly) => {
        const el = ref.current
        if (cancelled || !el) return
        plotly = loadedPlotly
        renderedEl = el
        loadedPlotly.react(
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
        observer = new ResizeObserver(() => loadedPlotly.Plots.resize(el))
        observer.observe(el)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : 'Could not load Plotly')
      })

    return () => {
      cancelled = true
      observer?.disconnect()
      if (plotly && renderedEl) plotly.purge(renderedEl)
    }
  }, [figure])

  return (
    <div>
      <div ref={ref} style={{ width: '100%', minHeight: 360 }} />
      {loadError && <div style={{ fontSize: 12, color: '#b42318', padding: '0 8px 8px' }}>Chart failed to load: {loadError}</div>}
      {caption && <div style={{ fontSize: 11, color: '#666', fontStyle: 'italic', margin: '4px 0 0', padding: '0 8px 8px' }}>{caption}</div>}
    </div>
  )
}
