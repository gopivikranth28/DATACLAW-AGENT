import CellChangeRenderer from './CellChangeRenderer'
import CellDiffRenderer from './CellDiffRenderer'
import CellOutputRenderer from './CellOutputRenderer'
import ImageDisplay from './ImageDisplay'
import NotebookLink from './NotebookLink'
import { FileWriteDisplay, FileReadDisplay } from './FileDisplay'
import ReportDisplay from './ReportDisplay'
import MetricDisplay from './MetricDisplay'

const AUTO_EXPAND_TOOLS = new Set([
  'execute_cell', 'display_cell_output', 'execute_code',
  'display_image', 'display_metric',
  'open_notebook',
  'ws_write_file', 'ws_read_file',
  'build_report',
  'report_add_section',
  'insert_cell', 'edit_cell', 'edit_cell_source',
])

export function shouldAutoExpand(toolName: string): boolean {
  return AUTO_EXPAND_TOOLS.has(toolName)
}

export function shouldRenderWhileCalling(_toolName: string): boolean {
  return false
}

function parseJSON(value: string | null | undefined): any | undefined {
  if (!value) return undefined
  try { return JSON.parse(value) } catch { return undefined }
}

export default function ToolResultRenderer({ toolName, result, args, status, onFileClick }: {
  toolName: string; result: string | null; args?: string; status?: string
  onFileClick?: (path: string) => void
}) {
  // Best-effort parse of the call's args — used as a fallback source for cell
  // renderers when older persisted results pre-date the source-echo backend
  // change. Safe to ignore parse failures; renderers degrade gracefully.
  const parsedArgs = parseJSON(args)

  if (toolName === 'propose_plan' || toolName === 'update_plan') {
    const parsed = parseJSON(result) ?? {}
    return <PlanToolNotice data={parsed} draft={parsedArgs} toolName={toolName} status={status} />
  }

  if (result === null) return null

  const parsed = parseJSON(result)
  if (!parsed) return <GenericResult result={result} />

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
    case 'display_metric':
      return <MetricDisplay data={parsed} />
    case 'open_notebook':
    case 'close_notebook':
      return <NotebookLink data={parsed} />
    case 'ws_write_file':
    case 'ws_update_file':
      return <FileWriteDisplay data={parsed} onFileClick={onFileClick} />
    case 'ws_read_file':
      return <FileReadDisplay data={parsed} onFileClick={onFileClick} />
    case 'build_report':
    case 'report_add_section':
      return <ReportDisplay data={parsed} onFileClick={onFileClick} />
    default:
      return <GenericResult result={result} />
  }
}

function PlanToolNotice({ data, draft, toolName, status }: {
  data: any
  draft?: any
  toolName: string
  status?: string
}) {
  const planName = draft?.name || data?.plan?.name || data?.proposal_id || 'Plan'
  const revision = data?.revision ? `rev ${data.revision}` : ''
  const label = toolName === 'update_plan'
    ? 'Plan progress updated'
    : status === 'calling'
    ? 'Drafting plan'
    : 'Plan submitted'
  return (
    <div style={{ fontSize: 12, color: '#667085', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span>{label}: <b>{planName}</b></span>
      {revision && <span style={{ color: '#98a2b3' }}>{revision}</span>}
      <span style={{ color: '#98a2b3' }}>review from the composer bar</span>
    </div>
  )
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
