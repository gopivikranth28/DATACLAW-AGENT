import { IpynbRenderer as IpynbView } from 'react-ipynb-renderer'
import 'react-ipynb-renderer/dist/styles/default.css'

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
  code?: string  // present in execute_code results
}

export default function CellOutputRenderer({ data }: { data: CellData }) {
  const outputs = data.outputs || []

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
