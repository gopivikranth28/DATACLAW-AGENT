/**
 * A report is not published merely because a report path was supplied to a
 * tool. This module is the single UI contract for the gated publish lifecycle
 * so transcript, report cards, and compatibility surfaces agree on that fact.
 */
export type PublishState = 'publishing' | 'published' | 'draft' | 'blocked' | 'failed' | 'completed'

export interface PublishCallLike {
  name: string
  status?: string
  result?: unknown
  args?: unknown
}

export function toolBaseName(name: string): string {
  return name.replace(/^(?:dataclaw_|workspace_|notebook_)/, '')
}

export function parseToolPayload(value: unknown): Record<string, any> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, any>
  if (typeof value !== 'string' || !value.trim()) return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

export function toolErrorMessage(value: unknown): string {
  const payload = parseToolPayload(value)
  const error = payload.error

  if (typeof error === 'string' && error.trim()) return error.trim()
  if (error && typeof error === 'object' && !Array.isArray(error)) {
    const code = text(error.code)
    const message = text(error.message) || text(error.detail) || text(error.hint)
    if (code && message) return `${code}: ${message}`
    return message || code
  }

  return text(payload.message) || text(payload.detail) || text(payload.hint)
    || (typeof value === 'string' && value.trim() && !Object.keys(payload).length ? value.trim() : '')
}

export function hasToolError(value: unknown): boolean {
  const payload = parseToolPayload(value)
  return Boolean(
    payload.error
    || payload.success === false
    || payload.ok === false
    || payload.status === 'error'
    || (typeof payload.exit_code === 'number' && payload.exit_code !== 0),
  )
}

export function isPublishedReportPayload(value: unknown): boolean {
  const payload = parseToolPayload(value)
  if (hasToolError(payload)) return false
  return payload.published === true || payload.publication_status === 'published'
}

export function reportPublishState(call: PublishCallLike): PublishState | null {
  if (toolBaseName(call.name) !== 'report_publish') return null
  if (call.status === 'calling') return 'publishing'

  const payload = parseToolPayload(call.result)
  if (call.status === 'error') return isPublishGateBlock(payload, call.result) ? 'blocked' : 'failed'
  if (isPublishedReportPayload(payload)) return 'published'
  if (payload.blocked === true || payload.publication_status === 'blocked') return 'blocked'
  if (hasToolError(payload)) return isPublishGateBlock(payload, call.result) ? 'blocked' : 'failed'
  if (payload.publication_status === 'draft' || payload.publish_required === true) return 'draft'
  return 'completed'
}

/** Return an actual output path only for a successful report publication. */
export function publishedReportPath(call: PublishCallLike): string {
  if (reportPublishState(call) !== 'published') return ''
  const payload = parseToolPayload(call.result)
  return text(payload.html_path) || text(payload.path)
}

/** Return the report target for a status message; this never claims publication. */
export function reportTargetPath(call: PublishCallLike): string {
  const result = parseToolPayload(call.result)
  const args = parseToolPayload(call.args)
  return text(result.html_path) || text(result.path)
    || text(args.html_path) || text(args.report_path) || text(args.path)
}

function isPublishGateBlock(payload: Record<string, any>, rawResult: unknown): boolean {
  if (payload.blocked === true || payload.publication_status === 'blocked') return true
  const message = toolErrorMessage(rawResult)
  return /(?:\b(?:publish|publication|report)\b.{0,80}\b(?:gate|blocked|requires?|required)\b|\b(?:analysis|design|visual|runtime)\b.{0,40}\bgate\b)/i.test(message)
}

function text(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
