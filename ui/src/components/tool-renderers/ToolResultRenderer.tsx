import CellChangeRenderer from './CellChangeRenderer'
import CellDiffRenderer from './CellDiffRenderer'
import CellOutputRenderer from './CellOutputRenderer'
import ImageDisplay from './ImageDisplay'
import PlanDisplay from './PlanDisplay'
import NotebookLink from './NotebookLink'
import { FileWriteDisplay, FileReadDisplay } from './FileDisplay'
import ReportDisplay from './ReportDisplay'

const AUTO_EXPAND_TOOLS = new Set([
  'execute_cell', 'display_cell_output', 'execute_code',
  'display_image',
  'propose_plan', 'update_plan',
  'open_notebook',
  'ws_write_file', 'ws_read_file',
  'build_report',
  'insert_cell', 'edit_cell', 'edit_cell_source',
])

export function shouldAutoExpand(toolName: string): boolean {
  return AUTO_EXPAND_TOOLS.has(toolName)
}

export default function ToolResultRenderer({ toolName, result, args, onFileClick, onDecision }: {
  toolName: string; result: string; args?: string
  onFileClick?: (path: string) => void
  onDecision?: (proposalId: string, status: string, feedback?: string) => void
}) {
  let parsed: any
  try { parsed = JSON.parse(result) } catch { return <GenericResult result={result} /> }

  // Best-effort parse of the call's args — used as a fallback source for cell
  // renderers when older persisted results pre-date the source-echo backend
  // change. Safe to ignore parse failures; renderers degrade gracefully.
  let parsedArgs: any = undefined
  if (args) {
    try { parsedArgs = JSON.parse(args) } catch { /* ignore */ }
  }

  switch (toolName) {
    case 'execute_cell':
    case 'display_cell_output':
    case 'execute_code':
      return <CellOutputRenderer data={parsed} args={parsedArgs} />
    case 'insert_cell':
      return <CellChangeRenderer data={parsed} args={parsedArgs} />
    case 'edit_cell':
    case 'edit_cell_source':
      return <CellDiffRenderer data={parsed} args={parsedArgs} />
    case 'display_image':
      return <ImageDisplay data={parsed} />
    case 'propose_plan':
    case 'update_plan':
      return <PlanDisplay data={parsed} onFileClick={onFileClick} onDecision={onDecision} />
    case 'open_notebook':
    case 'close_notebook':
      return <NotebookLink data={parsed} />
    case 'ws_write_file':
    case 'ws_update_file':
      return <FileWriteDisplay data={parsed} onFileClick={onFileClick} />
    case 'ws_read_file':
      return <FileReadDisplay data={parsed} onFileClick={onFileClick} />
    case 'build_report':
      return <ReportDisplay data={parsed} onFileClick={onFileClick} />
    default:
      return <GenericResult result={result} />
  }
}

function GenericResult({ result }: { result: string }) {
  let formatted = result
  try { formatted = JSON.stringify(JSON.parse(result), null, 2) } catch {}
  return (
    <pre style={{
      fontSize: 11, background: '#f8f9fa', padding: 8, borderRadius: 4,
      overflow: 'auto', maxHeight: 300, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
    }}>
      {formatted}
    </pre>
  )
}
