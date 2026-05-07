import { useState } from 'react'
import { IpynbRenderer as IpynbView } from 'react-ipynb-renderer'
import 'react-ipynb-renderer/dist/styles/default.css'
import CellSourceView from './CellSourceView'

interface CellOutput {
  type: string
  text?: string
  data?: string
  mimetype?: string
}

interface CellData {
  cell_index?: number
  outputs?: CellOutput[]
  caption?: string
  error?: string | null
  code?: string    // present in execute_code results (inline code)
  source?: string  // present in execute_cell results (cell source)
}

interface CellArgs {
  // execute_code passes the inline source as `code`; execute_cell passes
  // only `cell_index` (so source is unavailable from args alone).
  code?: string
  cell_index?: number
}

export default function CellOutputRenderer({ data, args }: { data: CellData; args?: CellArgs }) {
  const outputs = data.outputs || []
  const [showSource, setShowSource] = useState(false)
  // Prefer source from result; fall back to args.code for legacy execute_code
  // results that didn't echo source on the result side.
  const sourceForToggle = data.source ?? args?.code ?? ''
  const hasToggleableSource = !!(sourceForToggle && sourceForToggle.trim())

  if (data.error && outputs.length === 0) {
    return (
      <div>
        {data.cell_index !== undefined && <CellLabel index={data.cell_index} />}
        <pre style={{ background: '#fff2f0', color: '#cf1322', padding: 8, borderRadius: 4, fontSize: 11, margin: 0, whiteSpace: 'pre-wrap' }}>
          {data.error}
        </pre>
      </div>
    )
  }

  // Convert outputs to nbformat-compatible cell for IpynbView
  const nbOutputs = outputs.map(out => {
    if (out.type === 'image' && out.data) {
      return { output_type: 'display_data', data: { [out.mimetype || 'image/png']: out.data }, metadata: {} }
    }
    if (out.type === 'html' && out.text) {
      return { output_type: 'execute_result', data: { 'text/html': out.text }, metadata: {}, execution_count: null }
    }
    if (out.type === 'error' && out.text) {
      return { output_type: 'error', ename: 'Error', evalue: '', traceback: [out.text] }
    }
    return { output_type: 'stream', name: 'stdout', text: out.text || '' }
  })

  // Build a minimal notebook with one cell for IpynbView
  const notebook = {
    nbformat: 4,
    nbformat_minor: 5,
    metadata: { kernelspec: { display_name: 'Python 3', language: 'python', name: 'python3' }, language_info: { name: 'python' } },
    cells: [{
      cell_type: 'code',
      source: data.code || '',
      metadata: {},
      execution_count: data.cell_index !== undefined ? data.cell_index + 1 : null,
      outputs: nbOutputs,
    }],
  }

  return (
    <div>
      {data.cell_index !== undefined && <CellLabel index={data.cell_index} />}
      {hasToggleableSource && (
        <div style={{ marginBottom: 4 }}>
          <button
            onClick={() => setShowSource(s => !s)}
            style={{
              fontSize: 11, padding: '2px 8px', cursor: 'pointer',
              border: '1px solid #d9d9d9', borderRadius: 4,
              background: '#fafafa', color: '#444',
              display: 'inline-flex', alignItems: 'center', gap: 4,
            }}
          >
            <span style={{
              display: 'inline-block', transition: 'transform 0.15s',
              transform: showSource ? 'rotate(90deg)' : 'rotate(0deg)',
            }}>▸</span>
            Source
          </button>
          {showSource && (
            <div style={{ marginTop: 4 }}>
              <CellSourceView source={sourceForToggle} />
            </div>
          )}
        </div>
      )}
      <div className="cell-output-only" style={{ borderRadius: 6, overflow: 'hidden', border: '1px solid #e8e8e8' }}>
        <IpynbView ipynb={notebook as any} syntaxTheme="vscDarkPlus" language="python" />
      </div>
      {data.caption && <div style={{ fontSize: 11, color: '#666', fontStyle: 'italic', marginTop: 4 }}>{data.caption}</div>}
      {data.error && (
        <pre style={{ background: '#fff2f0', color: '#cf1322', padding: 6, borderRadius: 4, fontSize: 10, marginTop: 4, whiteSpace: 'pre-wrap' }}>
          {data.error}
        </pre>
      )}
    </div>
  )
}

function CellLabel({ index }: { index: number }) {
  return <div style={{ fontSize: 10, color: '#888', marginBottom: 4, fontFamily: 'monospace' }}>Cell [{index}]</div>
}
