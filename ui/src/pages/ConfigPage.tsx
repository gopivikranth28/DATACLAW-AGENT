import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useBeforeUnload, useBlocker } from 'react-router-dom'
import { Alert, Button, Divider, Drawer, Input, InputNumber, Modal, Select, Space, Switch, Tabs, Tag, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, CodeOutlined, DownloadOutlined, LoginOutlined, LoadingOutlined, ReloadOutlined, SaveOutlined, SettingOutlined, UndoOutlined } from '@ant-design/icons'
import { API } from '../api'
import WebTerminal from '../components/WebTerminal'

interface PluginInfo {
  id: string
  name: string
  label: string
  config_schema: { title: string; fields: ConfigFieldDef[] } | null
}

interface ConfigFieldDef {
  name: string
  field_type: string
  label: string
  description?: string
  default?: any
  options?: { value: string; label: string }[]
}

interface ProviderInfo {
  slot: string
  name: string | null
  config_schema: ConfigFieldDef[]
  config_path?: string | null
  backend?: {
    config_key: string
    current: string
    options: { value: string; label: string }[]
    config_paths?: Record<string, string | null>
    schemas?: Record<string, ConfigFieldDef[]>
  }
}

interface ModelOption {
  id: string
  label: string
}

interface ModelCatalogResponse {
  backend: string
  authenticated: boolean
  models: ModelOption[]
  message?: string | null
}

interface Props {
  plugins: PluginInfo[]
}

const AGENT_RUNTIME_OPTIONS = [
  { value: 'codex', label: 'OpenAI Codex', shortLabel: 'OpenAI Codex' },
  { value: 'openai', label: 'OpenAI API', shortLabel: 'OpenAI API' },
  { value: 'anthropic', label: 'Anthropic Claude', shortLabel: 'Anthropic Claude' },
  { value: 'gemini', label: 'Google Gemini', shortLabel: 'Google Gemini' },
  { value: 'openclaw', label: 'OpenClaw', shortLabel: 'OpenClaw' },
  { value: 'mock', label: 'Mock (testing)', shortLabel: 'Mock agent' },
]

const HISTORY_STRATEGY_OPTIONS = [
  { value: 'noop', label: 'Keep all history' },
  { value: 'llm_summarizer', label: 'Summarize older turns' },
  { value: 'drop_old', label: 'Remove older turns' },
]

const MEMORY_STRATEGY_OPTIONS = [
  { value: 'noop', label: 'Off' },
  { value: 'keyword', label: 'Keyword matching' },
  { value: 'rag', label: 'Semantic matching' },
  { value: 'gbrain', label: 'GBrain' },
]

const HELP_STYLE: CSSProperties = { fontSize: 12, color: '#737373', lineHeight: 1.5 }
const CALLOUT_STYLE: CSSProperties = { background: '#fafafa', border: '1px solid #eee', padding: '10px 12px', borderRadius: 7, fontSize: 12, color: '#555' }
const INACTIVE_GROUP_STYLE: CSSProperties = { background: '#fafafa', border: '1px solid #e8e8e8', borderRadius: 8, padding: '14px 14px 1px' }
const TAB_PANEL_STYLE: CSSProperties = { border: '1px solid #eee', borderRadius: 10, padding: 'clamp(16px, 4vw, 22px) clamp(16px, 4vw, 22px) 8px', background: '#fff' }
const EXTENSION_SECTION_STYLE: CSSProperties = { borderBottom: '1px solid #eee', padding: '2px 0 10px', marginBottom: 20 }
const TERMINAL_OUTPUT_STYLE: CSSProperties = { background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6, fontSize: 12, fontFamily: 'monospace', maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }

function cloneConfig(value: any): any {
  return JSON.parse(JSON.stringify(value ?? {}))
}

function configForSave(value: any): any {
  const persisted = { ...(value || {}) }
  delete persisted._active_agent
  return persisted
}

function describeConfigChanges(before: any, after: any): string[] {
  const changed: string[] = []
  if (JSON.stringify(before?.llm) !== JSON.stringify(after?.llm)) changed.push('Agent')
  const beforeAgentPlugins = { openclaw: before?.plugins?.openclaw, codex: before?.plugins?.codex }
  const afterAgentPlugins = { openclaw: after?.plugins?.openclaw, codex: after?.plugins?.codex }
  if (JSON.stringify(beforeAgentPlugins) !== JSON.stringify(afterAgentPlugins)) changed.push('Agent')
  if (before?.app?.max_turns !== after?.app?.max_turns) changed.push('Maximum action rounds')
  if (JSON.stringify(before?.compaction) !== JSON.stringify(after?.compaction)) changed.push('Conversation history')
  if (JSON.stringify(before?.memory) !== JSON.stringify(after?.memory)) changed.push('Cross-chat memory')
  const beforeExtensions = Object.fromEntries(Object.entries(before?.plugins || {}).filter(([id]) => id !== 'openclaw' && id !== 'codex'))
  const afterExtensions = Object.fromEntries(Object.entries(after?.plugins || {}).filter(([id]) => id !== 'openclaw' && id !== 'codex'))
  if (JSON.stringify(beforeExtensions) !== JSON.stringify(afterExtensions)) changed.push('Extensions')
  const beforeAdvanced = { debug: before?.app?.debug, max_auto_turns: before?.app?.max_auto_turns }
  const afterAdvanced = { debug: after?.app?.debug, max_auto_turns: after?.app?.max_auto_turns }
  if (JSON.stringify(beforeAdvanced) !== JSON.stringify(afterAdvanced)) changed.push('Advanced settings')
  return [...new Set(changed)]
}

function friendlyMemoryField(field: ConfigFieldDef): ConfigFieldDef {
  if (field.name === 'top_k') return { ...field, label: 'Memories per response', description: 'Maximum number of relevant memories retrieved for one response.' }
  if (field.name === 'min_score') return { ...field, label: 'Minimum relevance score' }
  if (field.name === 'model') return { ...field, label: 'Embedding model' }
  return field
}

export default function ConfigPage({ plugins }: Props) {
  const [config, setConfig] = useState<any>({})
  const [savedConfig, setSavedConfig] = useState<any | null>(null)
  const [saving, setSaving] = useState(false)
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsAuthenticated, setModelsAuthenticated] = useState<boolean | null>(null)
  const [modelsMessage, setModelsMessage] = useState<string | null>(null)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const modelRequestRef = useRef(0)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  useEffect(() => {
    fetch(`${API}/config`)
      .then(r => r.json())
      .then(data => {
        setConfig(data)
        setSavedConfig(cloneConfig(data))
      })
      .catch(() => message.error('Failed to load config'))
    fetch(`${API}/providers`)
      .then(r => r.json())
      .then(setProviders)
      .catch(() => {})
  }, [])

  const save = async (): Promise<boolean> => {
    setSaving(true)
    try {
      const res = await fetch(`${API}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(configForSave(config)),
      })
      if (res.ok) {
        message.success('Configuration saved')
        setSavedConfig(cloneConfig(config))
        // Re-fetch providers so config schemas reflect the new backend selections
        fetch(`${API}/providers`).then(r => r.json()).then(setProviders).catch(() => {})
        await loadModels()
        setSaving(false)
        return true
      }
      else message.error('Failed to save')
    } catch {
      message.error('Failed to save')
    }
    setSaving(false)
    return false
  }

  const isDirty = useMemo(
    () => savedConfig !== null && JSON.stringify(configForSave(config)) !== JSON.stringify(configForSave(savedConfig)),
    [config, savedConfig],
  )
  const changedSettings = useMemo(
    () => savedConfig ? describeConfigChanges(savedConfig, config) : [],
    [config, savedConfig],
  )
  const blocker = useBlocker(isDirty)
  useBeforeUnload(useCallback((event) => {
    if (!isDirty) return
    event.preventDefault()
    event.returnValue = ''
  }, [isDirty]))

  const discard = () => {
    if (savedConfig) setConfig(cloneConfig(savedConfig))
  }

  const saveAndLeave = async () => {
    if (await save()) blocker.proceed?.()
  }

  const discardAndLeave = () => {
    discard()
    blocker.proceed?.()
  }

  const llm = config.llm || {}
  const backend = llm.backend || 'openclaw'
  const backendConfig = llm[backend] || {}
  const app = config.app || {}
  const pluginsConfig = config.plugins || {}
  const openclawConfig = pluginsConfig.openclaw || {}
  const agentBackend = backend === 'openclaw' ? 'openclaw' : backend

  async function loadModels() {
    const selectedBackend = (config.llm?.backend || 'openclaw') as string
    if (!['anthropic', 'openai', 'gemini', 'codex'].includes(selectedBackend)) {
      setAvailableModels([])
      setModelsAuthenticated(null)
      setModelsMessage(null)
      setModelsError(null)
      return
    }

    const selectedConfig = config.llm?.[selectedBackend] || {}
    const payload: Record<string, string> = { backend: selectedBackend }
    const apiKey = selectedConfig.api_key || ''
    if (apiKey && apiKey !== '***' && !apiKey.includes('...')) payload.api_key = apiKey
    if (selectedBackend === 'openai') payload.base_url = selectedConfig.base_url || ''
    if (selectedBackend === 'codex') payload.auth_mode = selectedConfig.auth_mode || 'default'

    const requestId = ++modelRequestRef.current
    setModelsLoading(true)
    setModelsError(null)
    try {
      const res = await fetch(`${API}/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Failed to load models')
      if (requestId !== modelRequestRef.current) return

      const catalog = data as ModelCatalogResponse
      setAvailableModels(catalog.models || [])
      setModelsAuthenticated(catalog.authenticated)
      setModelsMessage(catalog.message || null)
    } catch (error) {
      if (requestId !== modelRequestRef.current) return
      setAvailableModels([])
      setModelsAuthenticated(false)
      setModelsMessage(null)
      setModelsError(error instanceof Error ? error.message : 'Failed to load models')
    } finally {
      if (requestId === modelRequestRef.current) setModelsLoading(false)
    }
  }

  useEffect(() => {
    if (!config.llm) return
    loadModels()
    // Credentials are deliberately omitted: API-key fields trigger loading on
    // blur/Enter so we do not send a request for every character typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentBackend, backendConfig.auth_mode])

  const updateBackendConfig = (field: string, value: any) => {
    setConfig((prev: any) => ({
      ...prev,
      llm: { ...prev.llm, [backend]: { ...(prev.llm?.[backend] || {}), [field]: value } },
    }))
  }
  const updateApp = (field: string, value: any) => {
    setConfig((prev: any) => ({ ...prev, app: { ...prev.app, [field]: value } }))
  }
  const updatePluginConfig = (pluginId: string, field: string, value: any) => {
    setConfig((prev: any) => ({
      ...prev,
      plugins: {
        ...prev.plugins,
        [pluginId]: { ...(prev.plugins?.[pluginId] || {}), [field]: value },
      },
    }))
  }
  const updateByPath = (dotPath: string, value: any) => {
    setConfig((prev: any) => {
      const parts = dotPath.split('.')
      const result = { ...prev }
      let current: any = result
      for (let i = 0; i < parts.length - 1; i++) {
        current[parts[i]] = { ...(current[parts[i]] || {}) }
        current = current[parts[i]]
      }
      current[parts[parts.length - 1]] = value
      return result
    })
  }
  const getByPath = (obj: any, dotPath: string): any => {
    const parts = dotPath.split('.')
    let current = obj
    for (const p of parts) {
      current = current?.[p]
      if (current === undefined) return undefined
    }
    return current
  }
  const setAgentBackend = (value: string) => {
    if (value === 'openclaw') {
      setConfig((prev: any) => ({
        ...prev,
        llm: { ...prev.llm, backend: 'openclaw' },
        plugins: { ...prev.plugins, openclaw: { ...(prev.plugins?.openclaw || {}), url: prev.plugins?.openclaw?.url || 'http://127.0.0.1:18789' } },
      }))
    } else {
      setConfig((prev: any) => ({
        ...prev,
        llm: { ...prev.llm, backend: value },
      }))
    }
  }

  // Codex login state
  const [codexLoggingIn, setCodexLoggingIn] = useState(false)
  const [codexLoginInfo, setCodexLoginInfo] = useState<{ method: string; auth_url?: string; verification_url?: string; user_code?: string } | null>(null)
  const [codexLoginResult, setCodexLoginResult] = useState<{ success: boolean; error?: string } | null>(null)
  const [codexRedirectUrl, setCodexRedirectUrl] = useState('')
  const [codexFinishingRedirect, setCodexFinishingRedirect] = useState(false)

  const finishCodexRedirect = async () => {
    if (!codexRedirectUrl.trim()) return
    setCodexFinishingRedirect(true)
    try {
      const res = await fetch(`${API}/codex/login/finish-redirect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: codexRedirectUrl.trim() }),
      })
      const data = await res.json()
      if (!data.success) {
        message.error(data.error || 'Redirect replay failed')
      } else if (data.completed) {
        // Codex wrote auth.json — done. The lingering /login/status SSE
        // will time out on its own; the UI doesn't need to wait on it.
        message.success('Codex login successful')
        setCodexLoginResult({ success: true })
        setCodexLoggingIn(false)
        setCodexRedirectUrl('')
        loadModels()
      } else {
        message.success('Redirect replayed — waiting for Codex to confirm…')
        setCodexRedirectUrl('')
      }
    } catch {
      message.error('Redirect replay failed')
    }
    setCodexFinishingRedirect(false)
  }

  const startCodexLogin = async (method: 'browser' | 'device_code' = 'browser') => {
    setCodexLoggingIn(true)
    setCodexLoginInfo(null)
    setCodexLoginResult(null)
    try {
      const res = await fetch(`${API}/codex/login/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ method }),
      })
      if (!res.ok) {
        message.error('Failed to start Codex login')
        setCodexLoggingIn(false)
        return
      }
      const data = await res.json()
      setCodexLoginInfo(data)
      if (data.auth_url) window.open(data.auth_url, '_blank')

      // Poll for completion via SSE
      const sse = await fetch(`${API}/codex/login/status`)
      if (!sse.ok || !sse.body) {
        setCodexLoggingIn(false)
        return
      }
      const reader = sse.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))
            if (evt.status === 'completed' || evt.status === 'failed') {
              setCodexLoginResult({ success: evt.success, error: evt.error })
              if (evt.success) {
                message.success('Codex login successful')
                loadModels()
              }
              else message.error(evt.error || 'Codex login failed')
            }
          } catch { /* skip */ }
        }
      }
    } catch {
      message.error('Codex login failed')
    }
    setCodexLoggingIn(false)
  }

  // OpenClaw CLI + plugin management state
  const [openclawStatus, setOpenclawStatus] = useState<{ installed: boolean; version?: string | null } | null>(null)
  const [checkingOpenclaw, setCheckingOpenclaw] = useState(false)
  const [pluginStatus, setPluginStatus] = useState<Record<string, { installed: boolean; status?: string; version?: string } | null>>({})
  const [, setChecking] = useState<Record<string, boolean>>({})
  // Drift between the live tool registry and the snapshot the openclaw plugin
  // was last installed with. UI nags the user to reinstall when this is out
  // of sync (`has_snapshot && !in_sync`).
  type SyncStatus = {
    has_snapshot: boolean
    in_sync: boolean
    live_count: number
    installed_count?: number
    added: string[]
    removed: string[]
    installed_at?: string | null
  }
  const [syncStatus, setSyncStatus] = useState<Record<string, SyncStatus | null>>({})
  const [installModalTarget, setInstallModalTarget] = useState<string | null>(null) // 'openclaw' | plugin id | null
  const [installing, setInstalling] = useState(false)
  const [buildOutput, setBuildOutput] = useState('')
  const outputRef = useRef<HTMLPreElement>(null)
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [terminalCommand, setTerminalCommand] = useState<string | undefined>(undefined)

  // The "Configure Model" button under OpenClaw settings shells out to
  // `openclaw models auth login --set-default`, which writes the new model
  // to OpenClaw's config but doesn't push it to the running gateway — the
  // gateway needs a restart to pick the new model up. When the user closes
  // the wizard, pop a confirmation modal with the restart commands so they
  // have to actively acknowledge it.
  const closeTerminal = () => {
    const wasModelConfig = !!terminalCommand?.includes('models')
    setTerminalOpen(false)
    checkOpenclawInstalled()
    if (wasModelConfig) {
      Modal.warning({
        title: 'Restart OpenClaw to apply the new model',
        content: (
          <div>
            <p style={{ marginTop: 0 }}>
              The model selection is written to OpenClaw's config, but the running gateway won't pick it up until it restarts.
            </p>
            <p style={{ marginBottom: 4 }}>Run one of these:</p>
            <ul style={{ paddingLeft: 20, margin: 0 }}>
              <li><code>openclaw gateway restart</code> in a terminal</li>
              <li>Restart your container if running the bundled image, e.g. <code>docker compose -f docker-compose.bundled.yml restart</code></li>
            </ul>
          </div>
        ),
        okText: 'Got it',
      })
    }
  }

  // Build WebSocket URL from the API URL
  const wsBase = API.replace(/^\/api$/, `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/api`)
    .replace(/^http/, 'ws')

  const checkOpenclawInstalled = async () => {
    setCheckingOpenclaw(true)
    try {
      const res = await fetch(`${API}/openclaw/check`)
      if (res.ok) setOpenclawStatus(await res.json())
      else setOpenclawStatus({ installed: false })
    } catch {
      setOpenclawStatus({ installed: false })
    }
    setCheckingOpenclaw(false)
  }

  // Check OpenClaw status on mount when backend is openclaw
  useEffect(() => {
    if (agentBackend === 'openclaw' && openclawStatus === null) checkOpenclawInstalled()
  }, [agentBackend])

  const checkPluginStatus = async (pluginId: string) => {
    setChecking(prev => ({ ...prev, [pluginId]: true }))
    try {
      const res = await fetch(`${API}/openclaw/plugins/${pluginId}/status`)
      if (res.ok) {
        const data = await res.json()
        setPluginStatus(prev => ({ ...prev, [pluginId]: data }))
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        message.error(err.detail || `Status check failed (${res.status})`)
        setPluginStatus(prev => ({ ...prev, [pluginId]: null }))
      }
    } catch {
      message.error('Failed to check plugin status')
    }
    setChecking(prev => ({ ...prev, [pluginId]: false }))
    // Refresh sync status alongside install status — they're closely related
    // and the user expects both to update together.
    fetchSyncStatus(pluginId)
  }

  const fetchSyncStatus = async (pluginId: string) => {
    try {
      const res = await fetch(`${API}/openclaw/plugins/${pluginId}/sync-status`)
      if (res.ok) {
        const data = (await res.json()) as SyncStatus
        setSyncStatus(prev => ({ ...prev, [pluginId]: data }))
      } else {
        setSyncStatus(prev => ({ ...prev, [pluginId]: null }))
      }
    } catch {
      setSyncStatus(prev => ({ ...prev, [pluginId]: null }))
    }
  }

  // Check sync status for openclaw plugins on mount when openclaw backend
  // is selected. Re-runs whenever the backend selection changes.
  useEffect(() => {
    if (agentBackend !== 'openclaw') return
    fetchSyncStatus('dataclaw')
  }, [agentBackend])

  const fetchOpenClawToken = async () => {
    try {
      const res = await fetch(`${API}/openclaw/fetch-token`)
      if (res.ok) {
        const data = await res.json()
        updatePluginConfig('openclaw', 'token', data.token)
        message.success(`Token loaded from ${data.source}`)
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        message.error(err.detail || 'Failed to fetch token')
      }
    } catch {
      message.error('Failed to fetch token')
    }
  }

  /** Stream an SSE install endpoint, appending output to buildOutput. */
  const streamInstall = async (url: string, label: string, onSuccess?: () => void) => {
    setInstalling(true)
    setBuildOutput('')
    try {
      const res = await fetch(url, { method: 'POST' })
      if (!res.ok || !res.body) {
        message.error('Install request failed')
        setInstalling(false)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const evt = JSON.parse(line.slice(6))
            if (evt.line !== undefined) setBuildOutput(prev => prev + evt.line + '\n')
            if (evt.error) setBuildOutput(prev => prev + `ERROR: ${evt.error}\n`)
            if (evt.exit_code !== undefined) {
              if (evt.exit_code === 0) {
                message.success(`${label} installed successfully`)
                onSuccess?.()
              } else if (!evt.error) {
                message.error(`Install failed (exit ${evt.exit_code})`)
              }
            }
          } catch { /* skip malformed SSE */ }
        }
      }
    } catch {
      message.error('Install stream failed')
    }
    setInstalling(false)
  }

  const handleOpenclawInstall = async () => {
    // Ask the server to write the bootstrap script to a temp file,
    // then open the terminal to run it. This keeps stdin connected
    // to the PTY so interactive commands (model auth) work.
    try {
      const res = await fetch(`${API}/openclaw/bootstrap-script`, { method: 'POST' })
      if (!res.ok) {
        message.error('Failed to generate bootstrap script')
        return
      }
      const { script: scriptPath } = await res.json()
      setTerminalCommand(scriptPath)
      setTerminalOpen(true)
    } catch {
      message.error('Failed to generate bootstrap script')
    }
  }

  const handleModalInstall = () => {
    if (!installModalTarget) return
    if (installModalTarget === 'openclaw') {
      handleOpenclawInstall()
      setInstallModalTarget(null)
    } else {
      streamInstall(`${API}/openclaw/plugins/${installModalTarget}/install`, installModalTarget, () => checkPluginStatus(installModalTarget))
    }
  }

  // Auto-scroll build output
  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight
  }, [buildOutput])

  const openclawPlugins = ['dataclaw']

  // OpenClaw and Codex belong to the Agent tab. Other plugin schemas are
  // compact enough to edit directly on the Extensions tab.
  const pluginsWithConfig = plugins.filter(
    p => p.id !== 'openclaw' && p.id !== 'codex' && p.config_schema && p.config_schema.fields && p.config_schema.fields.length > 0
  )
  const codexPlugin = plugins.find(p => p.id === 'codex' && p.config_schema?.fields?.length)
  const compactionProvider = providers.find(provider => provider.slot === 'compaction')
  const memoryProvider = providers.find(provider => provider.slot === 'memory')
  const compactionBackend = config.compaction?.backend || compactionProvider?.backend?.current || 'noop'
  const memoryBackend = config.memory?.backend || memoryProvider?.backend?.current || 'noop'
  const localBehaviorDisabled = agentBackend === 'openclaw'
  const memoryPath = memoryProvider?.backend?.config_paths?.[memoryBackend]
    || (memoryBackend === 'noop' ? null : `memory.${memoryBackend}`)
  const memoryFields = memoryProvider?.backend?.schemas?.[memoryBackend]
    || (memoryProvider && memoryProvider.backend?.current === memoryBackend ? memoryProvider.config_schema : [])
  const runtimeLabel = AGENT_RUNTIME_OPTIONS.find(option => option.value === agentBackend)?.shortLabel || agentBackend
  const configuredModel = backendConfig.model || 'No model selected'
  const authLabel = modelsAuthenticated === true
    ? 'Connected'
    : modelsAuthenticated === false
      ? 'Needs attention'
      : 'Checking access'

  return (
    <div style={{ padding: '20px clamp(16px, 4vw, 24px) 48px', maxWidth: 920, margin: '0 auto' }}>
      <div style={{ position: 'sticky', top: 0, zIndex: 20, background: 'rgba(255,255,255,.96)', padding: '4px 0 14px', marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px 16px' }}>
          <div>
            <h2 style={{ margin: 0, fontWeight: 650 }}>Settings</h2>
            <Space size={6} wrap style={{ marginTop: 7 }}>
              <Tag>{runtimeLabel}</Tag>
              {agentBackend !== 'openclaw' && agentBackend !== 'mock' && <Tag>{configuredModel}</Tag>}
              {agentBackend !== 'openclaw' && agentBackend !== 'mock' && (
                <Tag color={modelsAuthenticated === true ? 'success' : modelsAuthenticated === false ? 'error' : 'default'}>{authLabel}</Tag>
              )}
              {isDirty && <Tag color="warning">{changedSettings.length} unsaved {changedSettings.length === 1 ? 'change' : 'changes'}</Tag>}
            </Space>
          </div>
          <Space style={{ marginLeft: 'auto' }}>
            <Button icon={<UndoOutlined />} onClick={discard} disabled={!isDirty || saving}>Discard</Button>
            <Button type="primary" icon={<SaveOutlined />} onClick={() => void save()} loading={saving} disabled={!isDirty}>Save changes</Button>
          </Space>
        </div>
      </div>

      <Tabs
        defaultActiveKey="agent"
        items={[
          {
            key: 'agent',
            label: 'Agent',
            children: (
              <div style={TAB_PANEL_STYLE}>
                <TabIntro>Choose the primary runtime, its model access, and optional agent integrations.</TabIntro>
                <SectionTitle title="Primary runtime" description="Built-in runtimes execute in DataClaw. OpenClaw executes the agent loop in its own gateway." />
                <Field label="Agent runtime">
                  <Select value={agentBackend} onChange={setAgentBackend} style={{ width: '100%' }} options={AGENT_RUNTIME_OPTIONS} />
                </Field>

                {agentBackend !== 'mock' && agentBackend !== 'openclaw' && agentBackend !== 'codex' && (
                  <>
                    <Field label="API key" description="Stored securely and never displayed again in full.">
                      <Input.Password value={backendConfig.api_key || ''} onChange={e => updateBackendConfig('api_key', e.target.value)} placeholder="Enter API key" onBlur={loadModels} onPressEnter={loadModels} />
                    </Field>
                    <ModelSelector value={backendConfig.model || ''} onChange={value => updateBackendConfig('model', value)} models={availableModels} loading={modelsLoading} authenticated={modelsAuthenticated} statusMessage={modelsMessage} error={modelsError} onReload={loadModels} />
                    {agentBackend === 'openai' && (
                      <Field label="API endpoint" description="Optional. Override only for an OpenAI-compatible proxy or hosted endpoint.">
                        <Input value={backendConfig.base_url || ''} onChange={e => updateBackendConfig('base_url', e.target.value)} placeholder="https://api.openai.com/v1" onBlur={loadModels} onPressEnter={loadModels} />
                      </Field>
                    )}
                  </>
                )}

                {agentBackend === 'codex' && (
                  <>
                    <Field label="Sign-in method">
                      <Select value={backendConfig.auth_mode || 'default'} onChange={v => updateBackendConfig('auth_mode', v)} style={{ width: '100%' }} options={[{ value: 'default', label: 'OpenAI account (OAuth)' }, { value: 'api_key', label: 'OpenAI API key' }]} />
                    </Field>
                    {backendConfig.auth_mode === 'api_key' && (
                      <Field label="OpenAI API key" description="Used only when API-key sign-in is selected.">
                        <Input.Password value={backendConfig.api_key || ''} onChange={e => updateBackendConfig('api_key', e.target.value)} placeholder="Enter OpenAI API key" onBlur={loadModels} onPressEnter={loadModels} />
                      </Field>
                    )}
                    {(!backendConfig.auth_mode || backendConfig.auth_mode === 'default') && (
                      <Field label="Codex account">
                        <Space orientation="vertical" style={{ width: '100%' }}>
                          <Space size="small" wrap>
                            <Button type="primary" icon={<LoginOutlined />} loading={codexLoggingIn} onClick={() => startCodexLogin('browser')}>Sign in with browser</Button>
                            <Button loading={codexLoggingIn} onClick={() => startCodexLogin('device_code')}>Use device code</Button>
                            {modelsAuthenticated === true && <Tag icon={<CheckCircleOutlined />} color="success">Connected</Tag>}
                          </Space>
                          {codexLoginInfo?.method === 'device_code' && codexLoginInfo.user_code && (
                            <div style={CALLOUT_STYLE}>Go to <a href={codexLoginInfo.verification_url} target="_blank" rel="noreferrer">{codexLoginInfo.verification_url}</a> and enter <strong style={{ fontFamily: 'monospace' }}>{codexLoginInfo.user_code}</strong>.</div>
                          )}
                          {codexLoggingIn && codexLoginInfo?.method === 'browser' && !codexLoginResult && (
                            <div style={CALLOUT_STYLE}>
                              <div style={{ marginBottom: 6 }}>If the browser could not redirect back, paste its <code>http://localhost:1455/…</code> URL here.</div>
                              <Space.Compact style={{ width: '100%' }}>
                                <Input value={codexRedirectUrl} onChange={e => setCodexRedirectUrl(e.target.value)} placeholder="http://localhost:1455/auth/callback?code=…&state=…" onPressEnter={finishCodexRedirect} disabled={codexFinishingRedirect} />
                                <Button type="primary" loading={codexFinishingRedirect} disabled={!codexRedirectUrl.trim()} onClick={finishCodexRedirect}>Submit</Button>
                              </Space.Compact>
                            </div>
                          )}
                          {codexLoggingIn && !codexLoginResult && <div style={HELP_STYLE}><LoadingOutlined style={{ marginRight: 6 }} />Waiting for sign-in to complete…</div>}
                          {codexLoginResult && !codexLoginResult.success && <Alert type="error" showIcon title={codexLoginResult.error || 'Sign-in failed'} />}
                        </Space>
                      </Field>
                    )}
                    <ModelSelector value={backendConfig.model || ''} onChange={value => updateBackendConfig('model', value)} models={availableModels} loading={modelsLoading} authenticated={modelsAuthenticated} statusMessage={modelsMessage} error={modelsError} onReload={loadModels} />
                  </>
                )}

                {agentBackend === 'mock' && <Alert type="warning" showIcon title="Testing runtime" description="Returns test responses without calling a language model." />}

                <Divider />
                <SectionTitle title="OpenClaw" description="The external runtime connection and the local OpenClaw installation are managed together here." />
                <DisabledSettings disabled={agentBackend !== 'openclaw'} message="OpenClaw is not the selected runtime. Connection values remain saved; installation controls below are still available.">
                  <Field label="Gateway URL">
                    <Input disabled={agentBackend !== 'openclaw'} value={openclawConfig.url || ''} onChange={e => updatePluginConfig('openclaw', 'url', e.target.value)} placeholder="http://127.0.0.1:18789" />
                  </Field>
                  <Field label="Token" description="Shared by DataClaw and the OpenClaw gateway.">
                    <Space.Compact style={{ width: '100%' }}>
                      <Input.Password disabled={agentBackend !== 'openclaw'} value={openclawConfig.token || ''} onChange={e => updatePluginConfig('openclaw', 'token', e.target.value)} placeholder="dataclaw-local" />
                      <Button disabled={agentBackend !== 'openclaw'} onClick={fetchOpenClawToken}>Load token</Button>
                    </Space.Compact>
                  </Field>
                  <Field label="Callback URL" description="Address OpenClaw uses for DataClaw tools. Use host.docker.internal when OpenClaw runs in Docker.">
                    <Input disabled={agentBackend !== 'openclaw'} value={openclawConfig.tools_api_url || ''} onChange={e => updatePluginConfig('openclaw', 'tools_api_url', e.target.value)} placeholder="http://localhost:8000" />
                  </Field>
                  <Field label="Timeout" description="Set 0 to wait indefinitely.">
                    <NumberWithUnit ariaLabel="OpenClaw timeout" disabled={agentBackend !== 'openclaw'} value={openclawConfig.wait_ms ?? 0} onChange={v => updatePluginConfig('openclaw', 'wait_ms', v)} min={0} max={900000} unit="ms" />
                  </Field>
                </DisabledSettings>

                <Divider />
                <SectionTitle title="OpenClaw installation" description="Install or maintain the CLI on this DataClaw host. This is separate from selecting OpenClaw as the runtime." />
                <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                  <Space wrap>
                    {checkingOpenclaw ? <Tag icon={<LoadingOutlined />} color="processing">Checking</Tag> : openclawStatus?.installed ? <Tag icon={<CheckCircleOutlined />} color="success">{openclawStatus.version || 'Installed'}</Tag> : <Tag icon={<CloseCircleOutlined />}>{openclawStatus === null ? 'Status unknown' : 'Not installed'}</Tag>}
                    <Button onClick={checkOpenclawInstalled} loading={checkingOpenclaw}>Check status</Button>
                    <Button type="primary" icon={<DownloadOutlined />} onClick={handleOpenclawInstall}>Install</Button>
                    {openclawStatus?.installed && <Button onClick={() => { setTerminalCommand('openclaw models auth login --set-default'); setTerminalOpen(true) }}>Configure model</Button>}
                    {openclawStatus?.installed && <Button icon={<CodeOutlined />} onClick={() => { setTerminalCommand(undefined); setTerminalOpen(true) }}>Open terminal</Button>}
                  </Space>
                  <Field label="CLI command"><Input value={openclawConfig.openclaw_cmd || ''} onChange={e => updatePluginConfig('openclaw', 'openclaw_cmd', e.target.value)} placeholder="openclaw" /></Field>
                  <Field label="Config folder"><Input value={openclawConfig.openclaw_dir || ''} onChange={e => updatePluginConfig('openclaw', 'openclaw_dir', e.target.value)} placeholder="~" /></Field>
                  <Field label="Plugin source (DataClaw)"><Input value={openclawConfig.plugins_source_dir || ''} onChange={e => updatePluginConfig('openclaw', 'plugins_source_dir', e.target.value)} placeholder="Auto-detected" /></Field>
                  <Field label="Plugin source (OpenClaw)" description="Override only when OpenClaw sees the source at a different mounted path."><Input value={openclawConfig.openclaw_plugins_dir || ''} onChange={e => updatePluginConfig('openclaw', 'openclaw_plugins_dir', e.target.value)} placeholder="Same path" /></Field>
                </Space>

                <Divider />
                <SectionTitle title="OpenClaw tool bridge" description="Expose DataClaw tools to the OpenClaw gateway." />
                {openclawPlugins.map(pid => {
                  const status = pluginStatus[pid]
                  const sync = syncStatus[pid]
                  const driftDetected = !!sync && sync.has_snapshot && !sync.in_sync
                  return <div key={pid} style={{ paddingBottom: 8 }}>
                    <ExtensionRow name="DataClaw bridge" detail={driftDetected ? `${sync.added.length + sync.removed.length} tool changes pending` : 'Current DataClaw tool registry'} status={status?.installed ? 'Installed' : status === null ? 'Error' : 'Unknown'} statusColor={status?.installed ? 'success' : status === null ? 'error' : 'default'} onManage={() => checkPluginStatus(pid)} actionLabel="Check" extraAction={<Button size="small" type="primary" onClick={() => { setInstallModalTarget(pid); setBuildOutput('') }}>{status?.installed ? 'Update' : 'Install'}</Button>} />
                    {driftDetected && <Alert type="warning" showIcon title="Tools changed since the last install" description="Update the bridge so OpenClaw receives the current tool registry." />}
                  </div>
                })}

                {codexPlugin && (
                  <>
                    <Divider />
                    <SectionTitle title="Codex delegation" description="Allow the active agent to delegate coding tasks to Codex. This is independent of the primary runtime above." />
                    {codexPlugin.config_schema!.fields.map(field => (
                      <DynamicField
                        key={field.name}
                        field={field.name === 'enabled' ? { ...field, label: 'Allow Codex delegation', description: undefined } : field}
                        value={(pluginsConfig.codex || {})[field.name] ?? field.default}
                        onChange={v => updatePluginConfig('codex', field.name, v)}
                      />
                    ))}
                  </>
                )}
              </div>
            ),
          },
          {
            key: 'behavior',
            label: 'Behavior',
            children: (
              <div style={TAB_PANEL_STYLE}>
                <TabIntro>Control how long one response may run and how DataClaw manages conversation context.</TabIntro>
                <SectionTitle title="Per response" description="Limits one agent run, not the length of the conversation." />
                <Field label="Maximum action rounds" description="Maximum model-and-tool cycles allowed while producing one response. The run stops with an explanation at this limit.">
                  <NumberWithUnit ariaLabel="Maximum action rounds" value={app.max_turns ?? 30} onChange={v => updateApp('max_turns', v)} min={1} max={100} unit="rounds" />
                </Field>

                <Divider />
                <SectionTitle title="Conversation history" description="Older history is processed only at complete user-turn boundaries. Tool calls and their results always stay together." />
                <DisabledSettings disabled={localBehaviorDisabled} message="OpenClaw currently manages conversation history. These saved DataClaw values will apply when you select a built-in runtime.">
                  <Field label="When history grows">
                    <Select disabled={localBehaviorDisabled} value={compactionBackend} onChange={v => updateByPath('compaction.backend', v)} style={{ width: '100%' }} options={HISTORY_STRATEGY_OPTIONS} />
                  </Field>
                  {compactionBackend === 'noop' && !localBehaviorDisabled && (
                    <Alert type="info" showIcon title="Automatic history processing is off" description="The thresholds remain saved and can be edited after selecting a history strategy." style={{ marginBottom: 14 }} />
                  )}
                  <Field label="Start after" description="Process history after this many complete conversation turns.">
                    <NumberWithUnit ariaLabel="Start after" disabled={localBehaviorDisabled || compactionBackend === 'noop'} value={config.compaction?.max_messages ?? 30} onChange={v => updateByPath('compaction.max_messages', v)} min={2} unit="turns" />
                  </Field>
                  <Field label="Keep unchanged" description="Most recent complete turns preserved verbatim when history is processed.">
                    <NumberWithUnit ariaLabel="Keep unchanged" disabled={localBehaviorDisabled || compactionBackend === 'noop'} value={config.compaction?.keep_recent ?? 8} onChange={v => updateByPath('compaction.keep_recent', v)} min={1} unit="turns" />
                  </Field>
                  <Field label="Token threshold" description="Also process history when its estimated size reaches this limit. Set 0 to disable the token trigger.">
                    <NumberWithUnit ariaLabel="Token threshold" disabled={localBehaviorDisabled || compactionBackend === 'noop'} value={config.compaction?.max_tokens ?? 100000} onChange={v => updateByPath('compaction.max_tokens', v)} min={0} step={1000} unit="tokens" />
                  </Field>
                  {compactionBackend !== 'noop' && Number(config.compaction?.keep_recent ?? 8) >= Number(config.compaction?.max_messages ?? 30) && (
                    <Alert type="error" showIcon title="Keep unchanged must be lower than Start after." />
                  )}
                </DisabledSettings>

                <Divider />
                <SectionTitle title="Cross-chat memory" description="Choose whether DataClaw can retrieve saved information in later conversations." />
                <DisabledSettings disabled={localBehaviorDisabled} message="OpenClaw currently manages memory. These saved DataClaw values will apply when you select a built-in runtime.">
                  <Field label="Remember across chats">
                    <Select disabled={localBehaviorDisabled} value={memoryBackend} onChange={v => updateByPath('memory.backend', v)} style={{ width: '100%' }} options={MEMORY_STRATEGY_OPTIONS} />
                  </Field>
                  {memoryBackend === 'noop' ? (
                    <div style={{ ...HELP_STYLE, marginBottom: 4 }}>No information is retrieved from previous conversations.</div>
                  ) : memoryPath && memoryFields.length > 0 ? memoryFields.map(field => (
                    <DynamicField key={field.name} field={friendlyMemoryField(field)} value={getByPath(config, memoryPath)?.[field.name] ?? field.default} onChange={v => updateByPath(`${memoryPath}.${field.name}`, v)} disabled={localBehaviorDisabled} />
                  )) : (
                    <Alert type="warning" showIcon title="No settings schema is available for this memory strategy." />
                  )}
                </DisabledSettings>

                <Divider />
                <Button type="link" icon={<SettingOutlined />} onClick={() => setAdvancedOpen(true)} style={{ paddingInline: 0 }}>Advanced settings</Button>
              </div>
            ),
          },
          {
            key: 'extensions',
            label: 'Extensions',
            children: (
              <div style={TAB_PANEL_STYLE}>
                <TabIntro>Configure installed plugin settings directly. OpenClaw and Codex controls are on the Agent tab.</TabIntro>
                {pluginsWithConfig.map((plugin, index) => (
                  <div key={plugin.id} style={index === pluginsWithConfig.length - 1 ? { padding: '2px 0 0' } : EXTENSION_SECTION_STYLE}>
                    <SectionTitle title={plugin.config_schema!.title || plugin.label} />
                    {plugin.config_schema!.fields.map(field => (
                      <DynamicField key={field.name} field={field} value={(pluginsConfig[plugin.id] || {})[field.name] ?? field.default} onChange={v => updatePluginConfig(plugin.id, field.name, v)} />
                    ))}
                  </div>
                ))}
                {pluginsWithConfig.length === 0 && <Alert type="info" showIcon title="No configurable extensions installed" description="OpenClaw and Codex controls are available on the Agent tab." />}
              </div>
            ),
          },
        ]}
      />

      <Drawer title="Advanced settings" open={advancedOpen} onClose={() => setAdvancedOpen(false)} size="large">
        <SectionTitle title="Diagnostics" description="Settings intended for development and troubleshooting." />
        <Field label="Diagnostic logging" description="Include additional technical detail in server logs.">
          <Switch checked={app.debug || false} onChange={v => updateApp('debug', v)} />
        </Field>
        <Field label="Maximum automatic follow-ups" description="Maximum number of automatically continued agent runs in a session.">
          <NumberWithUnit ariaLabel="Maximum automatic follow-ups" value={app.max_auto_turns ?? 10} onChange={v => updateApp('max_auto_turns', v)} min={0} max={100} unit="runs" />
        </Field>
      </Drawer>

      <Modal title="Leave without saving?" open={blocker.state === 'blocked'} closable={false} mask={{ closable: false }} footer={[
        <Button key="stay" onClick={() => blocker.reset?.()}>Stay</Button>,
        <Button key="discard" danger onClick={discardAndLeave}>Discard and leave</Button>,
        <Button key="save" type="primary" loading={saving} onClick={() => void saveAndLeave()}>Save and leave</Button>,
      ]}>
        <p>You have unsaved settings. {changedSettings.length > 0 && <>Changes include: {changedSettings.join(', ')}.</>}</p>
      </Modal>

      <Modal title={`${installModalTarget !== 'openclaw' && pluginStatus[installModalTarget || '']?.installed ? 'Update' : 'Install'} ${installModalTarget === 'openclaw' ? 'OpenClaw' : installModalTarget || ''}`} open={!!installModalTarget} onCancel={() => { if (!installing) setInstallModalTarget(null) }} footer={[<Button key="close" onClick={() => setInstallModalTarget(null)} disabled={installing}>Close</Button>, <Button key="install" type="primary" icon={<DownloadOutlined />} loading={installing} onClick={handleModalInstall}>{installing ? 'Installing…' : 'Install'}</Button>]} width={640} mask={{ closable: !installing }}>
        {installModalTarget && <div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>{installModalTarget === 'openclaw' ? 'This downloads and configures the OpenClaw CLI, then starts its gateway.' : <>This updates the <code>{installModalTarget}</code> bridge and restarts the OpenClaw gateway. Save settings first.</>}</div>
          {buildOutput ? <pre ref={outputRef} style={TERMINAL_OUTPUT_STYLE}>{buildOutput}</pre> : !installing ? <div style={HELP_STYLE}>Select Install to begin.</div> : null}
        </div>}
      </Modal>

      <Modal title={terminalCommand?.includes('install') ? 'Install and configure OpenClaw' : terminalCommand?.includes('models') ? 'Configure OpenClaw model' : 'OpenClaw terminal'} open={terminalOpen} onCancel={closeTerminal} footer={<Button onClick={closeTerminal}>Close</Button>} width={720} destroyOnHidden>
        {terminalOpen && <WebTerminal wsUrl={`${wsBase}/terminal/ws`} initialCommand={terminalCommand} style={{ height: 400 }} />}
      </Modal>
    </div>
  )
}

function TabIntro({ children }: { children: ReactNode }) {
  return <div style={{ ...HELP_STYLE, margin: '0 0 20px' }}>{children}</div>
}

function SectionTitle({ title, description }: { title: string; description?: string }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 650, color: '#555', textTransform: 'uppercase', letterSpacing: '.055em' }}>{title}</div>
      {description && <div style={{ ...HELP_STYLE, marginTop: 3 }}>{description}</div>}
    </div>
  )
}

function DisabledSettings({ disabled, message, children }: { disabled: boolean; message: string; children: ReactNode }) {
  return (
    <div style={disabled ? INACTIVE_GROUP_STYLE : undefined} aria-disabled={disabled || undefined}>
      {disabled && <Alert type="info" showIcon title="Not currently applied" description={message} style={{ marginBottom: 14 }} />}
      {children}
    </div>
  )
}

function ExtensionRow({
  name,
  detail,
  status,
  statusColor,
  onManage,
  actionLabel = 'Manage',
  extraAction,
}: {
  name: string
  detail: string
  status: string
  statusColor: string
  onManage: () => void
  actionLabel?: string
  extraAction?: ReactNode
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
          <span style={{ fontWeight: 600 }}>{name}</span>
          <Tag color={statusColor}>{status}</Tag>
        </div>
        <div style={HELP_STYLE}>{detail}</div>
      </div>
      <Space size="small">
        <Button size="small" onClick={onManage}>{actionLabel}</Button>
        {extraAction}
      </Space>
    </div>
  )
}

function NumberWithUnit({
  ariaLabel,
  value,
  onChange,
  unit,
  disabled = false,
  min,
  max,
  step,
}: {
  ariaLabel: string
  value: number | null | undefined
  onChange: (value: number | null) => void
  unit: string
  disabled?: boolean
  min?: number
  max?: number
  step?: number
}) {
  return (
    <Space.Compact block>
      <InputNumber aria-label={ariaLabel} value={value} onChange={onChange} disabled={disabled} min={min} max={max} step={step} style={{ width: '100%' }} />
      <Button disabled style={{ minWidth: 72, color: '#666' }}>{unit}</Button>
    </Space.Compact>
  )
}

function Field({ label, description, children }: { label: string; description?: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 13, color: '#555', fontWeight: 520, marginBottom: 4 }}>{label}</div>
      {children}
      {description && <div style={{ ...HELP_STYLE, marginTop: 4 }}>{description}</div>}
    </div>
  )
}

function ModelSelector({
  value,
  onChange,
  models,
  loading,
  authenticated,
  statusMessage,
  error,
  onReload,
}: {
  value: string
  onChange: (value: string) => void
  models: ModelOption[]
  loading: boolean
  authenticated: boolean | null
  statusMessage: string | null
  error: string | null
  onReload: () => void
}) {
  const configuredModelMissing = !!value && authenticated === true && !models.some(model => model.id === value)
  const helpText = error
    || statusMessage
    || (loading ? 'Loading models from the authenticated provider…' : null)
    || (authenticated && models.length === 0 ? 'The provider returned no available models.' : null)

  return (
    <Field label="Model">
      <Space.Compact style={{ width: '100%' }}>
        <Select
          value={value || undefined}
          onChange={onChange}
          options={models.map(model => ({ value: model.id, label: model.label }))}
          loading={loading}
          disabled={authenticated !== true || models.length === 0}
          placeholder={loading ? 'Loading models…' : 'Authenticate to choose a model'}
          showSearch
          optionFilterProp="label"
          style={{ width: '100%' }}
          notFoundContent={loading ? <LoadingOutlined /> : 'No models available'}
        />
        <Button
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={onReload}
          title="Reload available models"
          aria-label="Reload available models"
        />
      </Space.Compact>
      {helpText && (
        <div style={{ fontSize: 11, color: error ? '#cf1322' : '#999', marginTop: 2 }}>
          {helpText}
        </div>
      )}
      {configuredModelMissing && (
        <Alert
          type="warning"
          showIcon
          title={`The configured model “${value}” is not in the provider's current model list. Choose an available model before saving.`}
          style={{ marginTop: 8, fontSize: 12 }}
        />
      )}
    </Field>
  )
}

function DynamicField({ field, value, onChange, disabled = false }: { field: ConfigFieldDef; value: any; onChange: (v: any) => void; disabled?: boolean }) {
  const renderInput = () => {
    switch (field.field_type) {
      case 'bool':
        return <Switch checked={!!value} onChange={onChange} disabled={disabled} />
      case 'int':
        return <InputNumber value={value} onChange={onChange} disabled={disabled} style={{ width: '100%' }} />
      case 'select':
        return (
          <Select value={value} onChange={onChange} disabled={disabled} style={{ width: '100%' }}
            options={(field.options || []).map(o => ({ value: o.value, label: o.label }))} />
        )
      case 'string':
      default:
        return <Input value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled} />
    }
  }
  return (
    <Field label={field.label} description={field.description}>
      {renderInput()}
    </Field>
  )
}
