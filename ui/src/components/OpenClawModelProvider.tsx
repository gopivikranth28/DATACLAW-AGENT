import { useCallback, useEffect, useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Alert, Button, Input, Select, Space, Switch, Tag, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, LoginOutlined, ReloadOutlined, SaveOutlined } from '@ant-design/icons'
import { API } from '../api'

/**
 * "Model provider" block for the OpenClaw runtime. Configures OpenClaw's
 * bundled OpenRouter provider through `/api/openclaw/model`; the OpenRouter
 * model list comes from the backend's cached proxy, never from the browser.
 * Other providers keep the terminal sign-in path.
 */

interface RoutingState {
  data_collection?: 'allow' | 'deny'
  zdr?: boolean
  sort?: 'price' | 'throughput' | 'latency'
  order?: string[]
  only?: string[]
  ignore?: string[]
  allow_fallbacks?: boolean
}

interface ModelState {
  provider: string | null
  model: string | null
  openrouter_model: string | null
  configured: boolean
  env_key_available: boolean
  routing: RoutingState & Record<string, unknown>
  response_cache: { enabled: boolean; ttl_seconds: number | null }
}

interface CatalogModel {
  id: string
  ref: string
  name: string
  vendor: string
  context_length: number | null
  prompt_price: string | null
  tools: boolean
}

type ProviderChoice = 'openrouter' | 'terminal'
type SortChoice = '' | 'price' | 'throughput' | 'latency'

const HELP_STYLE: CSSProperties = { fontSize: 12, color: '#737373', lineHeight: 1.5 }
// Routing keys the backend accepts; anything else authored by hand is left out
// of the replacement object rather than rejected.
const CARRIED_ROUTING_KEYS = ['order', 'only', 'ignore', 'allow_fallbacks'] as const

function Row({ label, description, children }: { label: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 13, color: '#555', fontWeight: 520, marginBottom: 4 }}>{label}</div>
      {children}
      {description && <div style={{ ...HELP_STYLE, marginTop: 4 }}>{description}</div>}
    </div>
  )
}

function formatPrice(perToken: string | null): string | null {
  const value = Number(perToken)
  if (!perToken || !Number.isFinite(value) || value < 0) return null
  return `$${(value * 1_000_000).toFixed(value * 1_000_000 < 1 ? 2 : 1)}/M in`
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}))
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) return body.detail.map((d: { loc?: string[]; msg?: string }) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ')
  return fallback
}

export default function OpenClawModelProvider({ onOpenTerminal }: { onOpenTerminal: () => void }) {
  const [state, setState] = useState<ModelState | null>(null)
  const [loadingState, setLoadingState] = useState(false)
  const [catalog, setCatalog] = useState<CatalogModel[]>([])
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [loadingCatalog, setLoadingCatalog] = useState(false)
  const [choice, setChoice] = useState<ProviderChoice>('openrouter')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState<string | undefined>(undefined)
  const [denyDataCollection, setDenyDataCollection] = useState(false)
  const [requireZdr, setRequireZdr] = useState(false)
  const [sort, setSort] = useState<SortChoice>('')
  const [saving, setSaving] = useState(false)

  const loadState = useCallback(async () => {
    setLoadingState(true)
    try {
      const res = await fetch(`${API}/openclaw/model`)
      if (!res.ok) throw new Error(await errorDetail(res, 'Could not read the OpenClaw model'))
      const data = (await res.json()) as ModelState
      setState(data)
      if (data.model && data.provider !== 'openrouter') setChoice('terminal')
      if (data.provider === 'openrouter' && data.model) setModel(data.model)
      setDenyDataCollection(data.routing?.data_collection === 'deny')
      setRequireZdr(data.routing?.zdr === true)
      setSort((data.routing?.sort as SortChoice) || '')
    } catch (error) {
      setState(null)
      message.error(error instanceof Error ? error.message : 'Could not read the OpenClaw model')
    } finally {
      setLoadingState(false)
    }
  }, [])

  const loadCatalog = useCallback(async (refresh = false) => {
    setLoadingCatalog(true)
    setCatalogError(null)
    try {
      const res = await fetch(`${API}/openclaw/openrouter/models${refresh ? '?refresh=true' : ''}`)
      if (!res.ok) throw new Error(await errorDetail(res, 'OpenRouter model list unavailable'))
      const data = await res.json()
      setCatalog(data.models || [])
      if (data.stale) setCatalogError('Showing a cached model list; OpenRouter could not be reached.')
    } catch (error) {
      setCatalogError(error instanceof Error ? error.message : 'OpenRouter model list unavailable')
    } finally {
      setLoadingCatalog(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void loadState(), 0)
    return () => window.clearTimeout(timer)
  }, [loadState])

  useEffect(() => {
    if (choice !== 'openrouter' || catalog.length || loadingCatalog || catalogError) return
    const timer = window.setTimeout(() => void loadCatalog(), 0)
    return () => window.clearTimeout(timer)
  }, [choice, catalog.length, loadingCatalog, catalogError, loadCatalog])

  const modelOptions = useMemo(() => {
    const groups = new Map<string, { label: string; value: string; search: string }[]>()
    for (const row of catalog) {
      const price = formatPrice(row.prompt_price)
      const detail = [row.id, price, row.tools ? null : 'no tools'].filter(Boolean).join(' · ')
      const list = groups.get(row.vendor) || []
      list.push({ value: row.ref, label: `${row.name} — ${detail}`, search: `${row.name} ${row.id}`.toLowerCase() })
      groups.set(row.vendor, list)
    }
    return [...groups.entries()].map(([vendor, options]) => ({ label: vendor, title: vendor, options }))
  }, [catalog])

  const modelMissing = !!model && catalog.length > 0 && !catalog.some(row => row.ref === model)

  const save = async () => {
    if (!model) {
      message.error('Choose a model')
      return
    }
    const carried = Object.fromEntries(
      CARRIED_ROUTING_KEYS.filter(key => state?.routing?.[key] !== undefined).map(key => [key, state!.routing[key]]),
    )
    const routing: RoutingState = { ...carried }
    if (denyDataCollection) routing.data_collection = 'deny'
    if (requireZdr) routing.zdr = true
    if (sort) routing.sort = sort
    setSaving(true)
    try {
      const res = await fetch(`${API}/openclaw/model`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: 'openrouter', model, routing, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) }),
      })
      if (!res.ok) throw new Error(await errorDetail(res, 'OpenClaw model configuration failed'))
      const data = await res.json()
      setApiKey('')
      for (const warning of data.warnings || []) message.warning(warning)
      message.success(`OpenClaw now uses ${data.model}`)
      await loadState()
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'OpenClaw model configuration failed')
    } finally {
      setSaving(false)
    }
  }

  const credentialTag = state === null
    ? <Tag>{loadingState ? 'Checking' : 'Status unknown'}</Tag>
    : state.configured
      ? <Tag icon={<CheckCircleOutlined />} color="success">OpenRouter key configured</Tag>
      : <Tag icon={<CloseCircleOutlined />}>No OpenRouter key</Tag>

  return (
    <div data-testid="openclaw-model-provider">
      <Row label="Provider" description={state?.model ? <>Current primary model: <code>{state.model}</code></> : 'OpenClaw has no primary model yet.'}>
        <Space wrap>
          <Select<ProviderChoice>
            value={choice}
            onChange={setChoice}
            style={{ minWidth: 240 }}
            options={[
              { value: 'openrouter', label: 'OpenRouter' },
              { value: 'terminal', label: 'Other provider (sign in from a terminal)' },
            ]}
          />
          {choice === 'openrouter' && credentialTag}
          <Button icon={<ReloadOutlined />} onClick={() => void loadState()} loading={loadingState} aria-label="Refresh OpenClaw model status" />
        </Space>
      </Row>

      {choice === 'terminal' ? (
        <Row label="Sign in" description="Runs OpenClaw's interactive login, which stores the credential and default model in OpenClaw.">
          <Button icon={<LoginOutlined />} onClick={onOpenTerminal}>Open terminal to log in</Button>
        </Row>
      ) : (
        <>
          <Row
            label="OpenRouter API key"
            description={state?.configured
              ? 'A key is already configured in OpenClaw. Leave blank to keep it, or enter a new key to replace it.'
              : state?.env_key_available
                ? 'Leave blank to use OPENROUTER_API_KEY from the DataClaw environment.'
                : <>Create a key at <a href="https://openrouter.ai/keys" target="_blank" rel="noreferrer">openrouter.ai/keys</a>. It is stored in OpenClaw's credential store, not in DataClaw.</>}
          >
            <Input.Password
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={state?.configured ? '•••••••• (configured)' : 'sk-or-…'}
              autoComplete="new-password"
            />
          </Row>
          <Row label="Model" description={catalogError || 'Search by name or id. Batch-only variants are hidden.'}>
            <Space.Compact style={{ width: '100%' }}>
              <Select
                value={model}
                onChange={setModel}
                options={modelOptions}
                loading={loadingCatalog}
                placeholder={loadingCatalog ? 'Loading OpenRouter models…' : 'Choose an OpenRouter model'}
                showSearch={{
                  filterOption: (input, option) => {
                    const search = (option as { search?: string } | undefined)?.search
                    return !!search && search.includes(input.toLowerCase())
                  },
                }}
                style={{ width: '100%' }}
                popupMatchSelectWidth={false}
              />
              <Button icon={<ReloadOutlined />} loading={loadingCatalog} onClick={() => void loadCatalog(true)} title="Reload OpenRouter models" aria-label="Reload OpenRouter models" />
            </Space.Compact>
            {modelMissing && <Alert type="warning" showIcon title={`“${model}” is not in OpenRouter's current model list.`} style={{ marginTop: 8, fontSize: 12 }} />}
          </Row>
          <Row label="Privacy and routing" description="Applied to the selected model as OpenRouter provider-routing preferences.">
            <Space orientation="vertical" size={6}>
              <label><Switch size="small" checked={denyDataCollection} onChange={setDenyDataCollection} /> <span style={{ marginLeft: 6 }}>Don't route to providers that store data</span></label>
              <label><Switch size="small" checked={requireZdr} onChange={setRequireZdr} /> <span style={{ marginLeft: 6 }}>Require zero data retention</span></label>
              <Space size={8}>
                <span style={{ fontSize: 13, color: '#555' }}>Prefer providers by</span>
                <Select<SortChoice>
                  size="small"
                  value={sort}
                  onChange={setSort}
                  style={{ minWidth: 170 }}
                  options={[
                    { value: '', label: 'OpenRouter default' },
                    { value: 'price', label: 'Lowest price' },
                    { value: 'throughput', label: 'Highest throughput' },
                    { value: 'latency', label: 'Lowest latency' },
                  ]}
                />
              </Space>
            </Space>
          </Row>
          <Button type="primary" icon={<SaveOutlined />} onClick={() => void save()} loading={saving} disabled={!model}>
            Apply to OpenClaw
          </Button>
        </>
      )}
    </div>
  )
}
