import { API } from '../api'

export interface ReportPreviewOptions {
  print?: boolean
  sessionId?: string | null
}

function reportParams(path: string, options?: ReportPreviewOptions): URLSearchParams {
  const params = new URLSearchParams({ path })
  if (options?.print) params.set('print', '1')
  if (options?.sessionId) params.set('session_id', options.sessionId)
  return params
}

export function reportPreviewUrl(path: string, options?: ReportPreviewOptions): string {
  const params = reportParams(path, options)
  return `${API}/workspace/preview?${params.toString()}`
}

export function reportDocumentUrl(path: string, cacheKey?: string, options?: ReportPreviewOptions): string {
  const params = reportParams(path, options)
  if (cacheKey) params.set('v', cacheKey)
  return `${API}/workspace/preview/document?${params.toString()}`
}
