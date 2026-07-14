import { API } from '../api'

export function reportPreviewUrl(path: string, options?: { print?: boolean }): string {
  const params = new URLSearchParams({ path })
  if (options?.print) params.set('print', '1')
  return `${API}/workspace/preview?${params.toString()}`
}

export function reportDocumentUrl(path: string, cacheKey?: string, options?: { print?: boolean }): string {
  const params = new URLSearchParams({ path })
  if (cacheKey) params.set('v', cacheKey)
  if (options?.print) params.set('print', '1')
  return `${API}/workspace/preview/document?${params.toString()}`
}
