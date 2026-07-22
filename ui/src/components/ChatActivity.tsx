import { useEffect, useState } from 'react'
import {
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
  RightOutlined,
} from '@ant-design/icons'
import type { GuardrailState, TimelineItem, ToolCallState } from '../hooks/useAGUI'
import ToolResultRenderer from './tool-renderers/ToolResultRenderer'
import {
  hasToolError,
  publishedReportPath as successfulReportPath,
  reportPublishState,
  reportTargetPath,
  toolBaseName,
  toolErrorMessage,
} from './reportPublishState'

interface TurnGroup {
  id: string
  calls: ToolCallState[]
  guardrails: GuardrailState[]
  evidence: ToolCallState[]
}

interface ActivityCall {
  call: ToolCallState
  duplicateCount: number
}

export type TranscriptBlock =
  | { kind: 'timeline'; entry: TimelineItem }
  | { kind: 'activity'; group: TurnGroup }

/**
 * Keep agent plumbing as one compact unit. Narrative messages deliberately break
 * a group, so persisted sessions that lack an explicit run id still degrade to a
 * readable activity block rather than a stack of tool cards.
 */
export function groupTranscript(entries: TimelineItem[]): TranscriptBlock[] {
  const blocks: TranscriptBlock[] = []
  let calls: ToolCallState[] = []
  let guardrails: GuardrailState[] = []
  let evidence: ToolCallState[] = []

  const flush = () => {
    if (calls.length || guardrails.length || evidence.length) {
      const first = calls[0] || evidence[0]
      blocks.push({
        kind: 'activity',
        group: { id: `turn-${first?.id || guardrails[0]?.id || blocks.length}`, calls, guardrails, evidence },
      })
    }
    calls = []
    guardrails = []
    evidence = []
  }

  for (const entry of entries) {
    if (entry.type === 'toolCall') {
      if (isEvidenceCall(entry.item)) evidence.push(entry.item)
      else calls.push(entry.item)
      continue
    }
    if (entry.type === 'guardrail') {
      guardrails.push(entry.item)
      continue
    }
    flush()
    blocks.push({ kind: 'timeline', entry })
  }
  flush()
  return keepLatestEvidence(blocks)
}

/**
 * Publishing the same report or re-displaying a notebook chart is common
 * during an agentic run. Keep the latest evidence surface so a captioned
 * display can replace the raw execution output without rendering the same
 * chart twice.
 */
function keepLatestEvidence(blocks: TranscriptBlock[]) {
  const seenReportPaths = new Set<string>()
  const seenChartOutputs = new Set<string>()
  const keptBlocks: TranscriptBlock[] = []

  for (let blockIndex = blocks.length - 1; blockIndex >= 0; blockIndex -= 1) {
    const block = blocks[blockIndex]
    if (block.kind !== 'activity') {
      keptBlocks.push(block)
      continue
    }

    const evidence: ToolCallState[] = []
    for (let callIndex = block.group.evidence.length - 1; callIndex >= 0; callIndex -= 1) {
      const call = block.group.evidence[callIndex]
      const reportPath = successfulReportPath(call)
      if (reportPath && seenReportPaths.has(reportPath)) continue
      if (reportPath) seenReportPaths.add(reportPath)
      const chartOutput = chartEvidenceKey(call)
      if (chartOutput && seenChartOutputs.has(chartOutput)) continue
      if (chartOutput) seenChartOutputs.add(chartOutput)
      evidence.push(call)
    }
    block.group.evidence = evidence.reverse()
    if (block.group.calls.length || block.group.guardrails.length || block.group.evidence.length) keptBlocks.push(block)
  }

  return keptBlocks.reverse()
}

function chartEvidenceKey(call: ToolCallState) {
  const toolName = toolBaseName(call.name)
  if (!['execute_cell', 'execute_code', 'display_cell_output'].includes(toolName)) return ''
  const data = parse(call.result)
  if (!Array.isArray(data?.outputs)) return ''
  const figures = data.outputs
    .filter((output: any) => output?.type === 'plotly' && output?.figure)
    .map((output: any) => output.figure.data)
  if (figures.length === 0) return ''
  const args = parse(call.args) || {}
  const cell = data.cell_index ?? args.cell_index ?? ''
  return `${cell}|${JSON.stringify(figures)}`
}

export function TurnActivity({ group, sessionId, onFileClick }: {
  group: TurnGroup
  sessionId?: string | null
  onFileClick?: (path: string) => void
}) {
  // Evidence is rendered separately, so the two arrays are partitioned rather
  // than chronological. Restore the original call order before deciding whether
  // a later retry recovered an error.
  const allCalls = [...group.calls, ...group.evidence].sort((left, right) => left.order - right.order)
  const activityCalls = collapseDuplicateReportUpdates(group.calls)
  const isRunning = allCalls.some(call => call.status === 'calling')
  const errors = allCalls.filter(hasError)
  const fixedErrors = recoveredErrorCount(allCalls)
  const remainingErrors = errors.length - fixedErrors
  const verb = isRunning
    ? 'Working'
    : group.calls.length > 0 && group.calls.every(call => call.name === 'propose_plan' || call.name === 'update_plan')
    ? 'Planned'
    : 'Worked'
  // A finished run stays compact like a notebook cell. Running or failed work
  // opens automatically because its detail is immediately actionable.
  const [expanded, setExpanded] = useState(() => isRunning || errors.length > 0)

  useEffect(() => {
    if (isRunning) setExpanded(true)
  }, [isRunning])

  const duration = relativeDuration(allCalls)
  const turnStartedAt = firstTimestamp(allCalls)
  const metricEvidence = group.evidence.filter(call => toolBaseName(call.name) === 'display_metric')
  const documentEvidence = group.evidence.filter(call => toolBaseName(call.name) !== 'display_metric')
  const stepCount = activityCalls.length + group.guardrails.length + group.evidence.length
  const meta = `${stepCount} steps${duration ? ` · ${duration}` : ''}`
  const label = `${verb} · ${meta}`

  return (
    <section className={`chat-turn${isRunning ? ' is-running' : ''}${remainingErrors ? ' has-error' : ''}${turnStartedAt !== null ? ' has-timing' : ''}`} aria-label={label}>
      <button
        type="button"
        className="chat-turn__header"
        aria-expanded={expanded}
        aria-controls={`${group.id}-details`}
        onClick={() => setExpanded(value => !value)}
      >
        <RightOutlined className="chat-turn__chevron" />
        {isRunning ? <LoadingOutlined spin aria-hidden="true" /> : remainingErrors ? <ExclamationCircleOutlined aria-hidden="true" /> : <CheckCircleOutlined aria-hidden="true" />}
        <span className="chat-turn__summary">{verb}</span>
        <span className="chat-turn__meta">{meta}</span>
        {remainingErrors > 0 && <span className="chat-turn__error-count">· {remainingErrors} error{remainingErrors === 1 ? '' : 's'}</span>}
        {fixedErrors > 0 && <span className="chat-turn__recovered-count">· {fixedErrors} error{fixedErrors === 1 ? '' : 's'} fixed</span>}
      </button>
      {expanded && (
        <div id={`${group.id}-details`} className="chat-turn__details">
          {activityCalls.map(({ call, duplicateCount }) => <ActivityStep key={call.id} call={call} turnStartedAt={turnStartedAt} duplicateCount={duplicateCount} />)}
          {group.guardrails.map(guardrail => <GuardrailStep key={guardrail.id} guardrail={guardrail} />)}
        </div>
      )}
      {metricEvidence.length > 0 && <div className="chat-metric-grid">{metricEvidence.map(call => <EvidenceCell key={call.id} call={call} sessionId={sessionId} onFileClick={onFileClick} />)}</div>}
      {documentEvidence.map(call => <EvidenceCell key={call.id} call={call} sessionId={sessionId} onFileClick={onFileClick} />)}
    </section>
  )
}

function ActivityStep({ call, turnStartedAt, duplicateCount = 1 }: { call: ToolCallState; turnStartedAt: number | null; duplicateCount?: number }) {
  const [open, setOpen] = useState(false)
  const failed = hasError(call)
  const timestamp = relativeTimestamp(call, turnStartedAt)
  const label = `${stepLabel(call)}${duplicateCount > 1 ? ` — consolidated ${duplicateCount} identical updates` : ''}`
  const disclosure = failed
    ? 'traceback'
    : sourceFor(call)
      ? 'source'
      : reportActivityDetail(call)
        ? 'details'
        : executableOutput(call)
          ? 'output'
          : null
  const detail = disclosure ? toolDetail(call) : ''
  const summary = <>
    {timestamp && <span className="chat-step__time">{timestamp}</span>}
    <span className="chat-step__mark" aria-hidden="true">{call.status === 'calling' ? '•' : failed ? '!' : '·'}</span>
    <span className="chat-step__label">{label}</span>
    {disclosure && <span className="chat-step__more">{open ? '▾' : '▸'} {disclosure}</span>}
  </>

  return (
    <div className={`chat-step${failed ? ' is-error' : ''}${call.status === 'calling' ? ' is-current' : ''}${timestamp ? ' has-timestamp' : ''}`}>
      {disclosure ? <button
        type="button"
        className="chat-step__summary"
        onClick={() => setOpen(value => !value)}
        aria-expanded={open}
        aria-controls={`${call.id}-detail`}
      >{summary}</button> : <div className="chat-step__summary">{summary}</div>}
      {open && detail && (
        <div id={`${call.id}-detail`} className="chat-step__detail">
          <CappedCode value={detail} />
        </div>
      )}
    </div>
  )
}

function GuardrailStep({ guardrail }: { guardrail: GuardrailState }) {
  const isProblem = guardrail.status === 'denied' || guardrail.status === 'pending'
  return (
    <div className={`chat-step${isProblem ? ' is-error' : ''}`}>
      <div className="chat-step__summary" role="status">
        <span className="chat-step__time">system</span>
        <span className="chat-step__mark" aria-hidden="true">{isProblem ? '!' : '·'}</span>
        <span className="chat-step__label">Guardrail {guardrail.status.replace(/_/g, ' ')}{guardrail.message ? ` — ${guardrail.message}` : ''}</span>
      </div>
    </div>
  )
}

function EvidenceCell({ call, sessionId, onFileClick }: {
  call: ToolCallState
  sessionId?: string | null
  onFileClick?: (path: string) => void
}) {
  const [sourceOpen, setSourceOpen] = useState(false)
  const data = parse(call.result)
  const args = parse(call.args)
  const cell = typeof data?.cell_index === 'number' ? data.cell_index : typeof args?.cell_index === 'number' ? args.cell_index : null
  const caption = typeof data?.caption === 'string' ? data.caption : ''
  const isMetric = toolBaseName(call.name) === 'display_metric'
  const publishState = reportPublishState(call)

  return (
    <article id={`output-${call.id}`} className={`chat-evidence${isMetric ? ' is-metric' : ''}`}>
      <div className="chat-evidence__body">
        {publishState === 'published' && <div style={{ marginBottom: 8, color: 'var(--ink)', fontSize: 12, fontWeight: 650 }}>Report published to workspace</div>}
        <ToolResultRenderer toolName={call.name} result={call.result} args={call.args} status={call.status} onFileClick={onFileClick} sessionId={sessionId} />
        {caption && <p className="chat-evidence__caption">{caption}</p>}
        <footer className="chat-evidence__footer">
          <span>{cell === null ? 'reported output' : `cell [${cell}]`} · ran in this turn</span>
          {sourceFor(call) && (
            <button type="button" onClick={() => setSourceOpen(value => !value)} aria-expanded={sourceOpen}>
              {sourceOpen ? '▾ source' : '▸ source'}
            </button>
          )}
        </footer>
        {sourceOpen && sourceFor(call) && <CappedCode value={sourceFor(call)!} />}
      </div>
    </article>
  )
}

function CappedCode({ value }: { value: string }) {
  const lines = value.split('\n')
  const [showAll, setShowAll] = useState(false)
  const shown = showAll ? lines : lines.slice(0, 12)
  return (
    <div className="chat-code">
      <pre>{shown.join('\n')}</pre>
      {lines.length > 12 && (
        <button type="button" onClick={() => setShowAll(value => !value)}>
          {showAll ? 'Show less' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  )
}

function isEvidenceCall(call: ToolCallState) {
  // A report section is a mutation, not reader-facing evidence. Keep it in
  // Worked as a narrated step; only the finished/published report earns its
  // own durable output surface.
  const toolName = toolBaseName(call.name)
  if (toolName === 'report_publish') return reportPublishState(call) === 'published'
  if (toolName === 'display_metric' || toolName === 'display_image') return true
  if (!['execute_cell', 'execute_code', 'display_cell_output'].includes(toolName)) return false
  const data = parse(call.result)
  return Array.isArray(data?.outputs) && data.outputs.some((output: any) => ['plotly', 'image', 'html'].includes(output?.type))
}

function stepLabel(call: ToolCallState): string {
  const args = parse(call.args) || {}
  const result = parse(call.result) || {}
  const cell = result.cell_index ?? result.index ?? args.cell_index ?? args.index
  const path = result.html_path ?? result.path ?? args.html_path ?? args.path ?? args.file_path ?? args.output_path ?? args.report_path
  const failed = hasError(call)
  const failure = failed ? errorSummary(call, result) : ''
  const suffix = failure ? ` — ${failure}` : ''
  const duration = callDuration(call, result)
  const durationSuffix = duration ? ` · ${duration}` : ''
  const toolName = toolBaseName(call.name)

  switch (toolName) {
    case 'insert_cell': {
      const source = String(args.source || args.content || '')
      const lines = source ? source.split('\n').length : null
      return `Added ${args.cell_type || 'code'} cell${cell === undefined || cell === -1 ? '' : ` [${cell}]`}${lines ? ` · ${lines} lines` : ''}${codePurpose(source)}${suffix}`
    }
    case 'edit_cell':
      return `Edited cell${cell === undefined ? '' : ` [${cell}]`}${args.new_source ? ` · ${args.new_source.split('\n').length} lines` : ''}${codePurpose(args.new_source)}${suffix}`
    case 'edit_cell_source':
      return `Edited cell${cell === undefined ? '' : ` [${cell}]`}${args.old_string ? ` — replaced ${compactInline(args.old_string, 64)}` : ''}${suffix}`
    case 'execute_cell':
      return `${call.status === 'calling' ? 'Running' : 'Ran'} cell${cell === undefined ? '' : ` [${cell}]`}${durationSuffix}${suffix}`
    case 'execute_code':
      return `${call.status === 'calling' ? 'Running' : 'Ran'} notebook code${codePurpose(String(args.code || ''))}${durationSuffix}${suffix}`
    case 'open_notebook': return `Opened notebook ${displayName(args.name || args.path || result.name || 'notebook')}${suffix}`
    case 'close_notebook': return `Closed notebook ${displayName(args.name || result.name || 'notebook')}${suffix}`
    case 'list_notebooks': return `Listed open notebooks${suffix}`
    case 'read_notebook': return `Read notebook cells${rangeLabel(args.start, args.limit)}${suffix}`
    case 'read_cell': return `Read cell${cell === undefined ? '' : ` [${cell}]`}${suffix}`
    case 'move_cell': return `Moved cell [${args.source_index}] to [${args.target_index}]${suffix}`
    case 'delete_cells': return `Deleted ${Array.isArray(args.cell_indices) ? `${args.cell_indices.length} cells` : 'cells'}${suffix}`
    case 'ws_list_files': return `Listed files${args.path && args.path !== '.' ? ` in ${displayName(args.path)}` : ''}${suffix}`
    case 'ws_read_file': return `Read ${displayName(path || 'a file')}${result.lines_returned ? ` · ${result.lines_returned} lines` : ''}${suffix}`
    case 'ws_write_file': return `Wrote ${displayName(path || 'a file')}${result.size ? ` · ${formatBytes(result.size)}` : ''}${suffix}`
    case 'ws_update_file': return `Updated ${displayName(path || 'a file')}${args.old_string ? ` — replaced ${compactInline(args.old_string, 64)}` : ''}${suffix}`
    case 'ws_exec': return `${call.status === 'calling' ? 'Running' : 'Ran'} workspace command${args.command ? ` — ${compactInline(args.command, 92)}` : ''}${result.exit_code ? ` · exit ${result.exit_code}` : ''}${durationSuffix}${suffix}`
    case 'data_list_datasets': return `Listed available datasets${suffix}`
    case 'data_preview_data': return `Previewed ${dataTarget(args)}${args.n_rows ? ` · ${args.n_rows} rows` : ''}${suffix}`
    case 'data_profile_dataset': return `Profiled ${dataTarget(args)}${suffix}`
    case 'data_describe_column': return `Described ${args.column_name || 'a column'} in ${dataTarget(args)}${suffix}`
    case 'data_query_data': return `Queried ${dataTarget(args)}${args.sql ? ` — ${compactInline(args.sql, 92)}` : ''}${durationSuffix}${suffix}`
    case 'data_get_docs': return `Loaded data package documentation${suffix}`
    case 'fetch_skill': return `Loaded skill ${displayName(args.skill_id || args.name || result.name || 'skill')}${suffix}`
    case 'propose_plan': return `Submitted plan ${args.name || result.plan?.name || 'for review'}${suffix}`
    case 'update_plan': return `Updated plan${planChange(args, result)}${suffix}`
    case 'delegate_to_subagent': return `Delegated to ${args.subagent_name || call.subagent?.name || 'subagent'}${call.subagent ? ` · ${call.subagent.currentTurn || 0} turns` : ''}${suffix}`
    case 'build_report': return `Built report ${displayName(args.title || path || 'report')}${args.report_goal ? ` — ${compactInline(args.report_goal, 110)}` : ''}${suffix}`
    case 'report_design_report': return reportDesignLabel(args, result, path, suffix)
    case 'report_review_visuals': return `Reviewed report visuals for ${displayName(path || 'report')}${suffix}`
    case 'report_publish': return reportPublishLabel(call, suffix)
    case 'report_add_section': return reportSectionLabel(args, result, suffix)
    case 'report_note': return `Added note to the ${args.page || 'report'} report${suffix}`
    default: return genericStepLabel(call, args, result, suffix, durationSuffix)
  }
}

function reportDesignLabel(args: any, result: any, path: unknown, suffix: string) {
  const title = displayName(args.title || result.title || path || 'report')
  const insightCount = Array.isArray(args.insights) ? args.insights.length : 0
  const purpose = args.report_goal || result.report_goal || ''
  return `Designed report ${title}${insightCount ? ` from ${insightCount} completed finding${insightCount === 1 ? '' : 's'}` : ''}${purpose ? ` — ${compactInline(purpose, 110)}` : ''}${suffix}`
}

function reportPublishLabel(call: ToolCallState, suffix: string) {
  const state = reportPublishState(call)
  const target = displayName(reportTargetPath(call) || 'report')
  switch (state) {
    case 'publishing': return `Publishing report ${target}`
    case 'published': return `Report published to workspace: ${target}`
    case 'draft': return `Report remains a draft: ${target}${suffix}`
    case 'blocked': return `Report publication blocked: ${target}${suffix}`
    case 'failed': return `Could not publish report: ${target}${suffix}`
    default: return `Completed report publication check: ${target}${suffix}`
  }
}

function reportSectionLabel(args: any, result: any, suffix: string) {
  const section = result.section || {}
  const data = args.data && typeof args.data === 'object' ? args.data : {}
  const kind = String(result.section_type || section.kind || args.section_type || 'content').replace(/_/g, ' ')
  const action = reportSectionAction(kind)
  const title = firstText(section, data, ['title', 'heading']) || firstText(args, result, ['title'])
  const context = reportSectionContext(kind, data, section)
  return `${action}${title ? `: ${compactInline(title, 104)}` : ''}${context ? ` — ${context}` : ''}${suffix}`
}

function reportSectionAction(kind: string) {
  const actions: Record<string, string> = {
    header: 'Set the report opening',
    'metric row': 'Added the headline metrics',
    chart: 'Added a chart',
    'chart interpretation': 'Added an interpreted chart',
    'interactive table': 'Added an explorable table',
    findings: 'Added the key findings',
    'narrative band': 'Added the report narrative',
    explanation: 'Added an explanation',
    callout: 'Added a decision callout',
    'methodology block': 'Documented the method',
    comparison: 'Added a comparison',
    checklist: 'Added a decision checklist',
  }
  return actions[kind] || `Added a ${kind} section`
}

function reportSectionContext(kind: string, data: any, section: any) {
  if (kind === 'metric row' && Array.isArray(data.metrics)) {
    const labels = data.metrics.slice(0, 3).map((metric: any) => {
      const label = metric?.label || metric?.name
      const value = metric?.value
      return label ? `${label}${value === undefined || value === '' ? '' : ` (${value})`}` : ''
    }).filter(Boolean)
    const remaining = data.metrics.length - labels.length
    return labels.length ? `${labels.join(', ')}${remaining > 0 ? `, and ${remaining} more` : ''}` : ''
  }
  if (kind === 'findings' && Array.isArray(data.findings)) {
    return `${data.findings.length} evidence-backed finding${data.findings.length === 1 ? '' : 's'}`
  }
  const text = firstText(section, data, ['caption', 'subtitle', 'summary', 'takeaway', 'description'])
  return text ? compactInline(text, 150) : ''
}

function genericStepLabel(call: ToolCallState, args: any, result: any, suffix: string, durationSuffix: string) {
  const name = toolBaseName(call.name)
  const words = name
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/^(?:kaggle|eda|analysis review|artifact|mlflow)\s+/, '')
    .trim()
    .toLowerCase()
  const target = genericTarget(args, result)
  const action = genericAction(words)
  const subject = action.object || words || 'task'
  const prefix = call.status === 'calling' ? 'Running' : hasError(call) ? 'Failed to' : action.verb
  return `${prefix} ${subject}${target ? ` — ${target}` : ''}${durationSuffix}${suffix}`
}

function genericAction(words: string) {
  const actions: Array<[RegExp, string]> = [
    [/^(?:get|fetch|read)\b/, 'Read'],
    [/^list\b/, 'Listed'],
    [/^query\b/, 'Queried'],
    [/^(?:search|find)\b/, 'Searched'],
    [/^(?:create|add|write|save|generate)\b/, 'Created'],
    [/^propose\b/, 'Recorded'],
    [/^request\b/, 'Requested'],
    [/^accept\b/, 'Accepted'],
    [/^(?:update|edit|modify)\b/, 'Updated'],
    [/^(?:delete|remove)\b/, 'Removed'],
    [/^(?:run|execute)\b/, 'Ran'],
    [/^(?:analyze|profile)\b/, 'Analyzed'],
    [/^(?:load|import)\b/, 'Loaded'],
    [/^(?:export|download)\b/, 'Exported'],
    [/^publish\b/, 'Published'],
    [/^(?:inspect|describe)\b/, 'Inspected'],
  ]
  for (const [pattern, verb] of actions) {
    if (pattern.test(words)) return { verb, object: words.replace(pattern, '').trim() || 'data' }
  }
  return { verb: 'Completed', object: words }
}

function genericTarget(args: any, result: any) {
  const target = firstText(args, result, ['path', 'file_path', 'output_path', 'report_path', 'dataset_name', 'dataset_id', 'table_name', 'competition', 'dataset', 'proposal_id', 'plan_step_id', 'target_id', 'experiment_id', 'name', 'title', 'query', 'search', 'url'])
  if (target) return displayName(target)
  const command = firstText(args, result, ['command'])
  return command ? compactInline(command, 92) : ''
}

function dataTarget(args: any) {
  const dataset = displayName(args.dataset_name || args.dataset_id || 'dataset')
  return args.table_name ? `${args.table_name} in ${dataset}` : dataset
}

function planChange(args: any, result: any) {
  const patches = Array.isArray(args.step_patches) ? args.step_patches : []
  if (patches.length) {
    const patch = patches[0] || {}
    const status = typeof patch.status === 'string' ? patch.status.replace(/_/g, ' ') : ''
    const detail = patch.summary || patch.name || patch.plan_step_id || ''
    if (detail || status) return ` — ${compactInline([detail, status].filter(Boolean).join(' · '), 96)}`
  }
  const step = firstText(args, result, ['step_name', 'step', 'current_step', 'summary', 'message'])
  const indexes = args.step_indices || args.step_ids
  if (step) return ` — ${compactInline(step, 96)}`
  if (Array.isArray(indexes) && indexes.length) return ` — ${indexes.length === 1 ? `step ${indexes[0]}` : `${indexes.length} steps`}`
  return ''
}

function errorSummary(call: ToolCallState, result: any) {
  const raw = toolErrorMessage(result) || (call.status === 'error' ? toolErrorMessage(call.result) || call.result || 'Tool failed' : 'Tool failed')
  return compactInline(raw.replace(/^error:\s*/i, ''), 150)
}

function callDuration(call: ToolCallState, result: any) {
  const started = call.startedAt
  const finished = call.finishedAt
  const milliseconds = typeof started === 'number' && typeof finished === 'number'
    ? Math.max(0, finished - started)
    : Number(result?.duration_ms ?? result?.elapsed_ms ?? result?.durationMs ?? 0)
  if (!milliseconds) return ''
  return milliseconds < 10_000 ? `${(milliseconds / 1000).toFixed(milliseconds < 1000 ? 1 : 0)}s` : `${Math.round(milliseconds / 1000)}s`
}

function codePurpose(source: string) {
  const lines = source.split('\n').map(line => line.trim()).filter(Boolean)
  const comment = lines.find(line => /^#\s+\S/.test(line))
  if (comment) return ` — ${compactInline(comment.replace(/^#\s*/, ''), 80)}`
  const assignment = lines.find(line => /^[A-Za-z][\w]*\s*=/.test(line))
  return assignment ? ` — ${compactInline(assignment.split('=')[0].trim().replace(/_/g, ' '), 64)}` : ''
}

function rangeLabel(start: unknown, limit: unknown) {
  return typeof start === 'number' ? ` from ${start}${typeof limit === 'number' ? ` · up to ${limit}` : ''}` : ''
}

function firstText(first: any, second: any, keys: string[]) {
  for (const source of [first, second]) {
    if (!source || typeof source !== 'object') continue
    for (const key of keys) {
      if (typeof source[key] === 'string' && source[key].trim()) return source[key].trim()
    }
  }
  return ''
}

function displayName(value: unknown) {
  return compactInline(String(value).replace(/^\.\//, ''), 110)
}

function compactInline(value: string, max: number) {
  return compact(value.replace(/\s+/g, ' ').trim(), max)
}

function hasError(call: ToolCallState) {
  if (call.status === 'error') return true
  return hasToolError(call.result)
}

function executableOutput(call: ToolCallState) {
  if (!call.result || !['execute_cell', 'execute_code', 'data_query_data', 'ws_exec'].includes(call.name)) return false
  const result = parse(call.result)
  return Boolean(result?.outputs?.length || result?.output || result?.stdout || result?.text)
}

function firstTimestamp(calls: ToolCallState[]) {
  const timestamps = calls.flatMap(call => [call.startedAt, call.finishedAt]).filter((value): value is number => typeof value === 'number')
  return timestamps.length ? Math.min(...timestamps) : null
}

function relativeTimestamp(call: ToolCallState, turnStartedAt: number | null) {
  const timestamp = call.startedAt ?? call.finishedAt
  if (typeof timestamp !== 'number' || turnStartedAt === null) return null
  const seconds = Math.max(0, Math.round((timestamp - turnStartedAt) / 1000))
  return `+${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function collapseDuplicateReportUpdates(calls: ToolCallState[]): ActivityCall[] {
  const visible: ActivityCall[] = []
  for (const call of calls) {
    const key = reportUpdateKey(call)
    const previous = visible[visible.length - 1]
    if (key && previous && key === reportUpdateKey(previous.call)) {
      previous.duplicateCount += 1
      continue
    }
    visible.push({ call, duplicateCount: 1 })
  }
  return visible
}

function reportUpdateKey(call: ToolCallState) {
  if (call.name !== 'report_add_section') return ''
  const args = parse(call.args) || {}
  const result = parse(call.result) || {}
  const section = result.section || {}
  const data = args.data && typeof args.data === 'object' ? args.data : {}
  const kind = result.section_type || section.kind || args.section_type
  const identity = section.section_id
    || section.title
    || data.title
    || (Array.isArray(data.metrics) ? data.metrics.map((metric: any) => metric?.label).filter(Boolean).join('|') : '')
  const report = result.html_path || args.report_path || args.path || ''
  return kind && identity ? `${report}|${kind}|${identity}` : ''
}

function recoveredErrorCount(calls: ToolCallState[]) {
  return calls.reduce((count, call, index) => {
    if (!hasError(call)) return count
    return calls.slice(index + 1).some(next => !hasError(next) && retriesCall(call, next)) ? count + 1 : count
  }, 0)
}

function retriesCall(failed: ToolCallState, next: ToolCallState) {
  if (failed.name !== next.name) return false
  const failedArgs = parse(failed.args) || {}
  const nextArgs = parse(next.args) || {}
  const failedResult = parse(failed.result) || {}
  const nextResult = parse(next.result) || {}
  const failedCell = failedResult.cell_index ?? failedArgs.cell_index ?? failedArgs.index
  const nextCell = nextResult.cell_index ?? nextArgs.cell_index ?? nextArgs.index
  if (failedCell !== undefined || nextCell !== undefined) return failedCell === nextCell
  const failedPath = failedResult.path ?? failedArgs.path ?? failedArgs.file_path ?? failedArgs.report_path
  const nextPath = nextResult.path ?? nextArgs.path ?? nextArgs.file_path ?? nextArgs.report_path
  if (failedPath || nextPath) return failedPath === nextPath
  const failedDataset = failedArgs.dataset_id ?? failedArgs.dataset_name
  const nextDataset = nextArgs.dataset_id ?? nextArgs.dataset_name
  if (failedDataset || nextDataset) {
    if (failedDataset !== nextDataset || failedArgs.table_name !== nextArgs.table_name) return false
    const failedQuery = failedArgs.sql ?? failedArgs.query ?? failedArgs.command
    const nextQuery = nextArgs.sql ?? nextArgs.query ?? nextArgs.command
    return !failedQuery || failedQuery === nextQuery
  }
  return false
}

function sourceFor(call: ToolCallState) {
  const result = parse(call.result)
  const args = parse(call.args)
  const source = result?.source || result?.code || args?.code || args?.source
  return typeof source === 'string' && source.trim() ? source : null
}

function toolDetail(call: ToolCallState) {
  const reportDetail = reportActivityDetail(call)
  if (reportDetail) return reportDetail
  const source = sourceFor(call)
  if (source) return source
  if (call.result) {
    try { return JSON.stringify(JSON.parse(call.result), null, 2) } catch { return call.result }
  }
  if (call.args) {
    try { return JSON.stringify(JSON.parse(call.args), null, 2) } catch { return call.args }
  }
  return ''
}

function reportActivityDetail(call: ToolCallState) {
  if (call.name !== 'report_add_section') return ''
  const args = parse(call.args) || {}
  const result = parse(call.result) || {}
  const section = result.section || {}
  const data = args.data && typeof args.data === 'object' ? args.data : {}
  const kind = String(result.section_type || section.kind || args.section_type || 'content').replace(/_/g, ' ')
  const context = reportSectionContext(kind, data, section)
  const report = displayName(result.html_path || args.report_path || 'the report')
  return [
    `What changed: ${reportSectionLabel(args, result, '')}`,
    context ? `Why it matters: ${context}` : '',
    `Saved in: ${report}`,
  ].filter(Boolean).join('\n')
}

function parse(value: string | null | undefined): any {
  if (!value) return null
  try { return JSON.parse(value) } catch { return null }
}

function compact(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function formatBytes(size: number) {
  return size < 1024 ? `${size} B` : `${(size / 1024).toFixed(1)} KB`
}

function relativeDuration(calls: ToolCallState[]) {
  const times = calls.flatMap(call => [call.startedAt, call.finishedAt]).filter((value): value is number => typeof value === 'number')
  if (times.length < 2) return null
  const seconds = Math.max(0, Math.round((Math.max(...times) - Math.min(...times)) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}
