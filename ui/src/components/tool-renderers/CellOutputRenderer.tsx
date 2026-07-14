import { useState } from 'react'
import PlotlyRenderer, { type PlotlyFigure } from './PlotlyRenderer'

interface CellOutput {
  type: string
  text?: string
  data?: string
  mimetype?: string
  figure?: PlotlyFigure
}

interface CellData {
  cell_index?: number
  outputs?: CellOutput[]
  caption?: string
  error?: string | null
  code?: string
  source?: string
}

interface CellArgs {
  code?: string
  cell_index?: number
}

/** Lightweight chat output renderer.
 *
 * The previous renderer mounted an entire, dark Jupyter document for every cell.
 * Here each output is a normal part of the transcript; dedicated notebook/file
 * views can still use a full notebook renderer where that is useful.
 */
export default function CellOutputRenderer({ data, args }: { data: CellData; args?: CellArgs }) {
  const outputs = data.outputs || []
  const [showSource, setShowSource] = useState(false)
  const source = data.source ?? data.code ?? args?.code ?? ''

  return (
    <div className="chat-cell-output">
      {source.trim() && (
        <button type="button" className="chat-cell-output__source" onClick={() => setShowSource(value => !value)} aria-expanded={showSource}>
          {showSource ? '▾ source' : '▸ source'}
        </button>
      )}
      {showSource && <LightCode value={source} />}
      {outputs.map((output, index) => <Output key={index} output={output} />)}
      {data.error && <pre className="chat-cell-output__error">{data.error}</pre>}
      {!outputs.length && !data.error && <span className="chat-cell-output__empty">No visible output.</span>}
    </div>
  )
}

function Output({ output }: { output: CellOutput }) {
  if (output.type === 'plotly' && output.figure) {
    return <div className="chat-cell-output__plot"><PlotlyRenderer figure={output.figure} /></div>
  }
  if (output.type === 'image' && output.data) {
    return <img className="chat-cell-output__image" src={`data:${output.mimetype || 'image/png'};base64,${output.data}`} alt="Notebook output" />
  }
  if (output.type === 'html' && output.text) return <TableOutput html={output.text} />
  if (output.type === 'error') return <pre className="chat-cell-output__error">{output.text || 'Cell execution failed'}</pre>
  return <pre className="chat-cell-output__text">{output.text || output.data || ''}</pre>
}

function TableOutput({ html }: { html: string }) {
  const [expanded, setExpanded] = useState(false)
  const parsed = parseTable(html)
  if (!parsed) return <pre className="chat-cell-output__text">{stripHtml(html)}</pre>
  const rows = expanded ? parsed.rows : parsed.rows.slice(0, 10)
  return (
    <div className="chat-cell-output__table-wrap">
      <table className="chat-cell-output__table">
        {parsed.headers.length > 0 && <thead><tr>{parsed.headers.map((header, index) => <th key={index}>{header}</th>)}</tr></thead>}
        <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody>
      </table>
      {parsed.rows.length > 10 && (
        <button type="button" className="chat-cell-output__more" onClick={() => setExpanded(value => !value)}>
          {expanded ? 'Show fewer rows' : `${parsed.rows.length - 10} more rows · show table`}
        </button>
      )}
    </div>
  )
}

function LightCode({ value }: { value: string }) {
  const lines = value.split('\n')
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? lines : lines.slice(0, 12)
  return (
    <div className="chat-cell-output__code">
      <pre>{visible.join('\n')}</pre>
      {lines.length > 12 && <button type="button" onClick={() => setExpanded(value => !value)}>{expanded ? 'Show less' : `Show all ${lines.length} lines`}</button>}
    </div>
  )
}

function parseTable(html: string): { headers: string[]; rows: string[][] } | null {
  if (typeof DOMParser === 'undefined' || !/<table[\s>]/i.test(html)) return null
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const table = doc.querySelector('table')
  if (!table) return null
  const headerRow = table.querySelector('thead tr')
  const headers = headerRow ? Array.from(headerRow.querySelectorAll('th, td')).map(cell => cell.textContent?.trim() || '') : []
  const rows = Array.from(table.querySelectorAll('tbody tr, table > tr')).map(row => Array.from(row.querySelectorAll('th, td')).map(cell => cell.textContent?.trim() || ''))
  return { headers, rows }
}

function stripHtml(value: string) {
  if (typeof DOMParser === 'undefined') return value.replace(/<[^>]*>/g, '')
  return new DOMParser().parseFromString(value, 'text/html').body.textContent || ''
}
