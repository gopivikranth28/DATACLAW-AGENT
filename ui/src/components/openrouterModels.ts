// Model selector helpers for OpenRouter's catalog (hundreds of models).

export interface CatalogModel {
  id: string
  label: string
  context_window?: number | null
  prompt_price_per_mtok?: number | null
  completion_price_per_mtok?: number | null
}

export function formatContext(tokens: number | null | undefined): string | null {
  if (!tokens) return null
  if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(2))}M`
  return `${Math.round(tokens / 1000)}K`
}

function formatPrice(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null
  if (value === 0) return '$0'
  return `$${value < 0.1 ? value.toFixed(3) : Number(value.toFixed(2))}`
}

export function modelDetails(model: CatalogModel): string {
  const parts: string[] = []
  const context = formatContext(model.context_window)
  if (context) parts.push(`${context} context`)
  const input = formatPrice(model.prompt_price_per_mtok)
  const output = formatPrice(model.completion_price_per_mtok)
  if (input !== null && output !== null) parts.push(`${input} / ${output} per M tokens`)
  return parts.join(' · ')
}

export function vendorOf(modelId: string): string {
  const slash = modelId.indexOf('/')
  return slash > 0 ? modelId.slice(0, slash).replace(/^~/, '') : 'other'
}

// Options grouped by vendor prefix (anthropic/, openai/, google/, ...), the
// most common vendors first, with a search string over id, name and vendor.
export function groupedModelOptions(models: CatalogModel[]) {
  const groups = new Map<string, CatalogModel[]>()
  for (const model of models) {
    const vendor = vendorOf(model.id)
    groups.set(vendor, [...(groups.get(vendor) || []), model])
  }
  const featured = ['anthropic', 'openai', 'google', 'x-ai', 'deepseek', 'typesafe']
  const vendors = [...groups.keys()].sort((a, b) => {
    const ia = featured.indexOf(a)
    const ib = featured.indexOf(b)
    if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
    return a.localeCompare(b)
  })
  return vendors.map(vendor => ({
    label: `${vendor} (${groups.get(vendor)!.length})`,
    title: vendor,
    options: groups.get(vendor)!.map(model => ({
      value: model.id,
      label: model.label,
      details: modelDetails(model),
      searchText: `${model.id} ${model.label} ${vendor}`.toLowerCase(),
    })),
  }))
}
