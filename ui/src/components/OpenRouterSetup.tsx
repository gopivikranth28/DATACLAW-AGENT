import { useCallback, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Alert, Button, Input, InputNumber, Segmented, Select, Space, Switch, Tag, message } from 'antd'
import { CheckCircleOutlined, KeyOutlined, ReloadOutlined, SafetyOutlined } from '@ant-design/icons'
import { API } from '../api'

// GET /api/providers/openrouter/key-status
export interface OpenRouterKeyStatus {
  configured: boolean
  valid: boolean
  message?: string
  key_hash?: string
  key_name?: string
  label?: string | null
  limit?: number | null
  limit_remaining?: number | null
  limit_reset?: string | null
  usage?: number | null
  usage_daily?: number | null
  usage_weekly?: number | null
  usage_monthly?: number | null
  is_free_tier?: boolean | null
  is_management_key?: boolean | null
  expires_at?: string | null
}

// llm.backends.openrouter.routing (provider preferences + fallback models)
export interface OpenRouterRouting {
  data_collection?: string
  zdr?: boolean
  sort?: string
  order?: string[]
  only?: string[]
  ignore?: string[]
  allow_fallbacks?: boolean
  require_parameters?: boolean
  models?: string[]
  [key: string]: unknown
}

interface ProvisionResult {
  key_name: string
  key_hash: string
  limit: number | null
  limit_reset: string | null
  use_for_llm: boolean
  use_for_decisions: boolean
}

const CARD_STYLE: CSSProperties = { border: '1px solid #d6e4ff', borderRadius: 10, padding: '16px 16px 4px', marginBottom: 14, background: '#f7faff' }
const HELP_STYLE: CSSProperties = { fontSize: 12, color: '#737373', lineHeight: 1.5 }
const PANEL_STYLE: CSSProperties = { background: '#fff', border: '1px solid #e8e8e8', borderRadius: 8, padding: '12px 12px 2px', marginBottom: 12 }
const FIELD_GRID_STYLE: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(220px, 100%), 1fr))', columnGap: 12 }

// Provider slugs offered as suggestions for the order list; any slug can be typed.
const PROVIDER_SUGGESTIONS = ['anthropic', 'openai', 'google-vertex', 'google-ai-studio', 'amazon-bedrock', 'azure', 'xai', 'deepseek', 'together', 'fireworks', 'groq', 'cerebras']

function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `$${value.toFixed(value >= 100 ? 0 : 2)}`
}

async function fetchKeyStatus(): Promise<{ status: OpenRouterKeyStatus | null; error: string | null }> {
  try {
    const res = await fetch(`${API}/providers/openrouter/key-status`)
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || 'Could not read the OpenRouter key status')
    return { status: data as OpenRouterKeyStatus, error: null }
  } catch (error) {
    return { status: null, error: error instanceof Error ? error.message : 'Could not read the OpenRouter key status' }
  }
}

function Labeled({ label, help, children }: { label: string; help?: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 500, color: '#333', marginBottom: 4 }}>{label}</div>
      {children}
      {help && <div style={{ ...HELP_STYLE, marginTop: 3 }}>{help}</div>}
    </div>
  )
}

export function OpenRouterSetupCard({
  apiKey,
  onApiKeyChange,
  routing,
  onRoutingChange,
  llmSelected,
  decisionsSelected,
  onUseForLlm,
  onUseForDecisions,
  onProvisioned,
}: {
  apiKey: string
  onApiKeyChange: (value: string) => void
  routing: OpenRouterRouting
  onRoutingChange: (value: OpenRouterRouting) => void
  llmSelected: boolean
  decisionsSelected: boolean
  onUseForLlm: () => void
  onUseForDecisions: () => void
  // Called after the server stored a new key; the page reloads that part of the config.
  onProvisioned: (result: ProvisionResult) => Promise<void> | void
}) {
  const [mode, setMode] = useState<'paste' | 'provision'>('paste')
  const [status, setStatus] = useState<OpenRouterKeyStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [statusError, setStatusError] = useState<string | null>(null)
  // The management key lives only in this input until the request is sent.
  const [managementKey, setManagementKey] = useState('')
  const [limitUsd, setLimitUsd] = useState<number | null>(null)
  const [limitReset, setLimitReset] = useState<string>('monthly')
  const [alsoLlm, setAlsoLlm] = useState(true)
  const [alsoDecisions, setAlsoDecisions] = useState(true)
  const [provisioning, setProvisioning] = useState(false)
  const [provisionError, setProvisionError] = useState<string | null>(null)
  const [rotating, setRotating] = useState(false)

  const applyStatus = useCallback((result: { status: OpenRouterKeyStatus | null; error: string | null }) => {
    setStatus(result.status)
    setStatusError(result.error)
    setStatusLoading(false)
  }, [])

  const loadStatus = useCallback(async () => {
    setStatusLoading(true)
    applyStatus(await fetchKeyStatus())
  }, [applyStatus])

  useEffect(() => {
    let active = true
    fetchKeyStatus().then(result => { if (active) applyStatus(result) })
    return () => { active = false }
  }, [applyStatus])

  const submitManagementKey = async (path: 'provision' | 'rotate') => {
    const key = managementKey
    // Cleared as soon as it is submitted, whatever the outcome.
    setManagementKey('')
    const setBusy = path === 'provision' ? setProvisioning : setRotating
    setBusy(true)
    setProvisionError(null)
    try {
      const res = await fetch(`${API}/providers/openrouter/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(key.trim() ? { management_key: key.trim() } : {}),
          ...(limitUsd !== null ? { limit_usd: limitUsd } : {}),
          ...(limitUsd !== null && limitReset !== 'none' ? { limit_reset: limitReset } : {}),
          ...(path === 'provision' ? { use_for_llm: alsoLlm, use_for_decisions: alsoDecisions } : {}),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `OpenRouter key ${path} failed`)
      if (path === 'rotate') {
        if (data.warning) message.warning(data.warning)
        else message.success('OpenRouter key rotated; the old key was deleted')
      } else {
        message.success(`Created OpenRouter key “${data.key_name}”. Only that key was saved.`)
      }
      await onProvisioned(data as ProvisionResult)
      await loadStatus()
      setMode('paste')
    } catch (error) {
      setProvisionError(error instanceof Error ? error.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  const keyReady = status?.configured && status.valid
  const updateRouting = (patch: Partial<OpenRouterRouting>) => onRoutingChange({ ...routing, ...patch })

  return (
    <section style={CARD_STYLE} data-testid="openrouter-setup">
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <h3 style={{ fontSize: 14, lineHeight: '24px', margin: 0, color: '#333' }}>
            OpenRouter <Tag color="blue" style={{ marginLeft: 6 }}>Recommended</Tag>
          </h3>
          <div style={{ ...HELP_STYLE, marginTop: 2 }}>
            One OpenRouter key gives DataClaw Anthropic, OpenAI, Google, xAI and other models, plus Jev for decisions. Set it once here.
          </div>
        </div>
        <Space size={6} wrap>
          {llmSelected ? <Tag icon={<CheckCircleOutlined />} color="success">DataClaw model</Tag> : <Button size="small" onClick={onUseForLlm}>Use for DataClaw model</Button>}
          {decisionsSelected ? <Tag icon={<CheckCircleOutlined />} color="success">Decisions (alpha)</Tag> : <Button size="small" onClick={onUseForDecisions}>Use for decisions</Button>}
        </Space>
      </div>

      <div style={PANEL_STYLE}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <Space size={6} wrap>
            <strong style={{ fontSize: 13, color: '#333' }}>Key status</strong>
            {statusLoading ? <Tag>Checking…</Tag>
              : !status?.configured ? <Tag>No key yet</Tag>
                : status.valid ? <Tag color="success">Active{status.key_name ? ` · ${status.key_name}` : ''}</Tag>
                  : <Tag color="error">Rejected</Tag>}
          </Space>
          <Button size="small" icon={<ReloadOutlined />} onClick={() => void loadStatus()} loading={statusLoading}>Refresh</Button>
        </div>
        {keyReady && (
          <div style={{ fontSize: 12, color: '#555', marginBottom: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6 }}>
            <div><div style={HELP_STYLE}>Credits used</div><strong>{usd(status?.usage)}</strong> <span style={HELP_STYLE}>({usd(status?.usage_monthly)} this month)</span></div>
            <div>
              <div style={HELP_STYLE}>Remaining</div>
              <strong>{status?.limit === null || status?.limit === undefined ? 'No key limit' : `${usd(status?.limit_remaining)} of ${usd(status?.limit)}`}</strong>
              {status?.limit_reset && <span style={HELP_STYLE}> (resets {status.limit_reset})</span>}
            </div>
            {status?.expires_at && <div><div style={HELP_STYLE}>Expires</div><strong>{new Date(status.expires_at).toLocaleDateString()}</strong></div>}
          </div>
        )}
        {status?.configured && !status.valid && <Alert type="error" showIcon title={status.message || 'OpenRouter rejected the saved key.'} style={{ marginBottom: 10 }} />}
        {statusError && <Alert type="warning" showIcon title={statusError} style={{ marginBottom: 10 }} />}
      </div>

      <Segmented
        value={mode}
        onChange={value => { setMode(value as 'paste' | 'provision'); setProvisionError(null) }}
        options={[
          { value: 'paste', label: 'Paste an API key' },
          { value: 'provision', label: 'Provision with management key' },
        ]}
        style={{ marginBottom: 12 }}
      />

      {mode === 'paste' ? (
        <Labeled label="OpenRouter API key" help="An inference key (sk-or-v1-…). Saved with Save changes; or set OPENROUTER_API_KEY on the server.">
          <Input.Password
            value={apiKey}
            onChange={event => onApiKeyChange(event.target.value)}
            placeholder="sk-or-v1-…"
            autoComplete="new-password"
          />
        </Labeled>
      ) : (
        <div>
          <Alert
            type="info"
            showIcon
            icon={<SafetyOutlined />}
            title="Your management key is not stored."
            description="DataClaw uses it once to create an inference key named after this machine, saves only that new key, and forgets the management key. It is never written to the config file or logs. Leave it empty to use OPENROUTER_MANAGEMENT_KEY from the server environment."
            style={{ marginBottom: 12 }}
          />
          <Labeled label="Management key">
            <Input.Password
              value={managementKey}
              onChange={event => setManagementKey(event.target.value)}
              placeholder="Management key (not stored)"
              autoComplete="off"
              prefix={<KeyOutlined />}
            />
          </Labeled>
          <div style={FIELD_GRID_STYLE}>
            <Labeled label="Spending limit (USD)" help="Optional cap on the new key. Empty means no key limit.">
              <InputNumber value={limitUsd} onChange={value => setLimitUsd(typeof value === 'number' ? value : null)} min={0} step={5} prefix="$" style={{ width: '100%' }} placeholder="No limit" />
            </Labeled>
            <Labeled label="Limit resets">
              <Select
                value={limitReset}
                onChange={setLimitReset}
                disabled={limitUsd === null}
                style={{ width: '100%' }}
                options={[
                  { value: 'daily', label: 'Daily' },
                  { value: 'weekly', label: 'Weekly' },
                  { value: 'monthly', label: 'Monthly' },
                  { value: 'none', label: 'Never' },
                ]}
              />
            </Labeled>
          </div>
          <Space wrap style={{ marginBottom: 12 }}>
            <Space size={6}><Switch size="small" checked={alsoLlm} onChange={setAlsoLlm} />Use for DataClaw model</Space>
            <Space size={6}><Switch size="small" checked={alsoDecisions} onChange={setAlsoDecisions} />Use for decisions (alpha)</Space>
          </Space>
          {provisionError && <Alert type="error" showIcon title={provisionError} style={{ marginBottom: 12 }} />}
          <Space wrap style={{ marginBottom: 12 }}>
            <Button type="primary" loading={provisioning} onClick={() => void submitManagementKey('provision')}>Create and save key</Button>
            {status?.key_hash && (
              <Button loading={rotating} onClick={() => void submitManagementKey('rotate')}>Rotate saved key</Button>
            )}
          </Space>
        </div>
      )}

      <div style={PANEL_STYLE}>
        <strong style={{ fontSize: 13, color: '#333', display: 'block', marginBottom: 8 }}>Privacy and routing</strong>
        <div style={FIELD_GRID_STYLE}>
          <Labeled label="Deny data collection" help="Only use providers that do not store or train on prompts.">
            <Switch checked={routing.data_collection === 'deny'} onChange={checked => updateRouting({ data_collection: checked ? 'deny' : '' })} />
          </Labeled>
          <Labeled label="Zero data retention" help="Only use endpoints that keep no prompts (ZDR).">
            <Switch checked={routing.zdr === true} onChange={checked => updateRouting({ zdr: checked })} />
          </Labeled>
          <Labeled label="Prefer providers by">
            <Select
              value={routing.sort || ''}
              onChange={value => updateRouting({ sort: value })}
              style={{ width: '100%' }}
              options={[
                { value: '', label: 'OpenRouter default' },
                { value: 'price', label: 'Lowest price' },
                { value: 'throughput', label: 'Highest throughput' },
                { value: 'latency', label: 'Lowest latency' },
              ]}
            />
          </Labeled>
          <Labeled label="Provider order" help="Try these providers first, in order.">
            <Select
              mode="tags"
              value={routing.order || []}
              onChange={value => updateRouting({ order: value })}
              style={{ width: '100%' }}
              placeholder="e.g. anthropic"
              options={PROVIDER_SUGGESTIONS.map(slug => ({ value: slug, label: slug }))}
              tokenSeparators={[',', ' ']}
            />
          </Labeled>
        </div>
        <div style={{ ...HELP_STYLE, marginBottom: 10 }}>Defaults leave OpenRouter's and your account's routing unchanged. These apply to models and decisions.</div>
      </div>
    </section>
  )
}
