import CellChangeRenderer from './CellChangeRenderer'
import CellDiffRenderer from './CellDiffRenderer'
import CellOutputRenderer from './CellOutputRenderer'
import ImageDisplay from './ImageDisplay'
import NotebookLink from './NotebookLink'
import { FileWriteDisplay, FileReadDisplay } from './FileDisplay'
import ReportDisplay from './ReportDisplay'
import MetricDisplay from './MetricDisplay'
import PublishArtifactCard from './PublishArtifactCard'
import { reportPreviewUrl } from '../reportPreview'

const AUTO_EXPAND_TOOLS = new Set([
  'execute_cell', 'display_cell_output', 'execute_code',
  'display_image', 'display_metric',
  'open_notebook',
  'ws_write_file', 'ws_read_file',
  'build_report',
  'report_design_report',
  'report_publish',
  'publish_artifact',
  'insert_cell', 'edit_cell', 'edit_cell_source',
])

const CUSTOM_RENDER_TOOLS = new Set([
  ...AUTO_EXPAND_TOOLS,
  'ws_update_file',
  'close_notebook',
  'propose_plan',
  'update_plan',
  'report_design_report',
  'report_add_section',
])

export function shouldAutoExpand(toolName: string): boolean {
  return AUTO_EXPAND_TOOLS.has(toolName)
}

export function hasCustomRenderer(toolName: string): boolean {
  return CUSTOM_RENDER_TOOLS.has(toolName)
}

export function shouldRenderWhileCalling(_toolName: string): boolean {
  return false
}

function parseJSON(value: string | null | undefined): any | undefined {
  if (!value) return undefined
  try { return JSON.parse(value) } catch { return undefined }
}

export default function ToolResultRenderer({ toolName, result, args, status, onFileClick, sessionId }: {
  toolName: string; result: string | null; args?: string; status?: string
  onFileClick?: (path: string) => void
  sessionId?: string | null
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
    case 'report_design_report':
    case 'report_publish':
      return <ReportDisplay data={parsed} />
    case 'report_add_section':
      return <ReportUpdateNotice data={parsed} onFileClick={onFileClick} />
    case 'publish_artifact':
      return <PublishArtifactCard data={parsed} sessionId={sessionId} />
    default:
      return <GenericResult result={result} />
  }
}

function ReportUpdateNotice({ data, onFileClick }: {
  data: any
  onFileClick?: (path: string) => void
}) {
  const htmlPath = data?.html_path || data?.path
  const sectionType = data?.section_type || data?.section?.kind || 'section'
  const name = htmlPath?.split('/').pop() || 'report.html'
  const openPreview = () => {
    if (!htmlPath) return
    if (onFileClick) onFileClick(htmlPath)
    else window.open(reportPreviewUrl(htmlPath), '_blank')
  }
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      fontSize: 12, color: '#667085',
    }}>
      <span>Report updated: <b>{sectionType}</b></span>
      {data?.publication_status === 'draft' && (
        <span style={{ color: '#ad6800', fontWeight: 600 }}>Draft · publish required</span>
      )}
      {htmlPath && (
        <>
          <span style={{ color: '#98a2b3' }}>{name}</span>
          <button
            type="button"
            onClick={openPreview}
            style={{
              border: 0, background: 'transparent', color: '#2563eb',
              padding: 0, cursor: 'pointer', fontSize: 12,
            }}
          >
            Preview
          </button>
        </>
      )}
    </div>
  )
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
