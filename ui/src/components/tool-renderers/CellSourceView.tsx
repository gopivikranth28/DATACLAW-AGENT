import { IpynbRenderer as IpynbView } from 'react-ipynb-renderer'
import 'react-ipynb-renderer/dist/styles/default.css'
import MarkdownContent from '../MarkdownContent'

/**
 * Renders a single cell's source. Code cells go through react-ipynb-renderer
 * for Python syntax highlighting; markdown cells go through MarkdownContent
 * (react-markdown + remark-gfm) so they display the way they would in the
 * notebook itself rather than as raw markdown text.
 */
export default function CellSourceView({
  source,
  cellType = 'code',
  executionCount = null,
}: {
  source: string
  cellType?: 'code' | 'markdown'
  executionCount?: number | null
}) {
  if (cellType === 'markdown') {
    return (
      <div style={{
        fontSize: 13, background: '#fafafa', padding: '10px 14px',
        borderRadius: 6, border: '1px solid #e8e8e8',
      }}>
        <MarkdownContent content={source} />
      </div>
    )
  }

  const notebook = {
    nbformat: 4,
    nbformat_minor: 5,
    metadata: { kernelspec: { display_name: 'Python 3', language: 'python', name: 'python3' }, language_info: { name: 'python' } },
    cells: [{
      cell_type: 'code',
      source,
      metadata: {},
      execution_count: executionCount,
      outputs: [],
    }],
  }

  return (
    <div className="cell-output-only" style={{ borderRadius: 6, overflow: 'hidden', border: '1px solid #e8e8e8' }}>
      <IpynbView ipynb={notebook as any} syntaxTheme="vscDarkPlus" language="python" />
    </div>
  )
}
