import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { useBeforeUnload, useBlocker } from 'react-router-dom'
import { Alert, Button, Divider, Drawer, Input, InputNumber, Modal, Select, Space, Switch, Tabs, Tag, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, CodeOutlined, DownloadOutlined, LoginOutlined, LoadingOutlined, ReloadOutlined, SaveOutlined, SettingOutlined, UndoOutlined } from '@ant-design/icons'
import { API } from '../api'
import WebTerminal from '../components/WebTerminal'
import OpenClawModelProvider from '../components/OpenClawModelProvider'

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

interface HermesInstallStatus {
  installed: boolean
  executable?: string | null
  version?: string | null
  compatible_version?: string
  version_compatible?: boolean
  extension_installed?: boolean
  restricted_profile?: boolean
  profile?: string
  model?: string | null
  provider?: string | null
  model_selected?: boolean
  model_configured?: boolean
  provider_auth_configured?: boolean | null
  provider_auth_detail?: string | null
}

interface HermesHealthStatus {
  status?: string
  [key: string]: unknown
}

interface Props {
  plugins: PluginInfo[]
}

const AGENT_RUNTIME_OPTIONS = [
  { value: 'dataclaw', label: 'DataClaw', shortLabel: 'DataClaw' },
  { value: 'hermes', label: 'Hermes Agent', shortLabel: 'Hermes Agent' },
  { value: 'openclaw', label: 'OpenClaw', shortLabel: 'OpenClaw' },
  { value: 'mock', label: 'Mock (testing)', shortLabel: 'Mock agent' },
]

const UTILITY_BACKEND_OPTIONS = [
  { value: 'codex', label: 'OpenAI Codex' },
  { value: 'openai', label: 'OpenAI API' },
  { value: 'anthropic', label: 'Anthropic Claude' },
  { value: 'gemini', label: 'Google Gemini' },
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
const SETTINGS_GROUP_STYLE: CSSProperties = { border: '1px solid #e8e8e8', borderRadius: 10, padding: '16px 16px 2px', marginBottom: 14, background: '#fcfcfc' }
const FIELD_GRID_STYLE: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(260px, 100%), 1fr))', columnGap: 16 }
const EXTENSION_SECTION_STYLE: CSSProperties = { borderBottom: '1px solid #eee', padding: '2px 0 10px', marginBottom: 20 }
const TERMINAL_OUTPUT_STYLE: CSSProperties = { background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6, fontSize: 12, fontFamily: 'monospace', maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }

function cloneConfig(value: any): any {
  return JSON.parse(JSON.stringify(value ?? {}))
}

function configForSave(value: any): any {
  const persisted = { ...(value || {}) }
  delete persisted._active_agent
  delete persisted._runtime_status
  return persisted
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'"'"'`)}'`
}

function describeConfigChanges(before: any, after: any): string[] {
  const changed: string[] = []
  if (JSON.stringify(before?.agent) !== JSON.stringify(after?.agent)) changed.push('Agent')
  if (JSON.stringify(before?.llm) !== JSON.stringify(after?.llm)) changed.push('Agent')
  const beforeAgentPlugins = { openclaw: before?.plugins?.openclaw, hermes: before?.plugins?.hermes, codex: before?.plugins?.codex }
  const afterAgentPlugins = { openclaw: after?.plugins?.openclaw, hermes: after?.plugins?.hermes, codex: after?.plugins?.codex }
  if (JSON.stringify(beforeAgentPlugins) !== JSON.stringify(afterAgentPlugins)) changed.push('Agent')
  if (before?.app?.max_turns !== after?.app?.max_turns) changed.push('Maximum action rounds')
  if (JSON.stringify(before?.compaction) !== JSON.stringify(after?.compaction)) changed.push('Conversation history')
  if (JSON.stringify(before?.memory) !== JSON.stringify(after?.memory)) changed.push('Cross-chat memory')
  const beforeExtensions = Object.fromEntries(Object.entries(before?.plugins || {}).filter(([id]) => id !== 'openclaw' && id !== 'hermes' && id !== 'codex'))
  const afterExtensions = Object.fromEntries(Object.entries(after?.plugins || {}).filter(([id]) => id !== 'openclaw' && id !== 'hermes' && id !== 'codex'))
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
  const [utilityAccessLoading, setUtilityAccessLoading] = useState(false)
  const [utilityAuthenticated, setUtilityAuthenticated] = useState<boolean | null>(null)
  const [utilityAccessMessage, setUtilityAccessMessage] = useState<string | null>(null)
  const utilityRequestRef = useRef(0)
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
        const refreshed = await fetch(`${API}/config`).then(r => r.json()).catch(() => config)
        setConfig(refreshed)
        setSavedConfig(cloneConfig(refreshed))
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
  const app = config.app || {}
  const pluginsConfig = config.plugins || {}
  const openclawConfig = pluginsConfig.openclaw || {}
  const hermesConfig = pluginsConfig.hermes || {}
  const runtimeStatus = config._runtime_status || {}
  const legacyBackend = llm.backend || 'openclaw'
  const agentBackend = config.agent?.runtime
    || (['openclaw', 'hermes', 'mock'].includes(legacyBackend) ? legacyBackend : 'dataclaw')
  const utilityBackend = ['anthropic', 'openai', 'gemini', 'codex'].includes(legacyBackend)
    ? legacyBackend
    : hermesConfig.utility_backend || 'codex'
  const backendConfig = llm[utilityBackend] || {}

  async function loadModels() {
    const selectedBackend = String(
      ['anthropic', 'openai', 'gemini', 'codex'].includes(config.llm?.backend)
        ? config.llm.backend
        : config.plugins?.hermes?.utility_backend || 'codex',
    )
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

  async function checkUtilityAccess(): Promise<boolean> {
    const selectedBackend = String(
      ['anthropic', 'openai', 'gemini', 'codex'].includes(config.llm?.backend)
        ? config.llm.backend
        : config.plugins?.hermes?.utility_backend || '',
    )
    const requestId = ++utilityRequestRef.current
    if (!['anthropic', 'openai', 'gemini', 'codex'].includes(selectedBackend)) {
      setUtilityAuthenticated(false)
      setUtilityAccessMessage('Choose a utility backend first.')
      return false
    }

    const selectedConfig = config.llm?.[selectedBackend] || {}
    const payload: Record<string, string> = { backend: selectedBackend }
    const apiKey = String(selectedConfig.api_key || '')
    if (apiKey && apiKey !== '***' && !apiKey.includes('...')) payload.api_key = apiKey
    if (selectedBackend === 'openai') payload.base_url = selectedConfig.base_url || ''
    if (selectedBackend === 'codex') payload.auth_mode = selectedConfig.auth_mode || 'default'

    setUtilityAccessLoading(true)
    setUtilityAccessMessage(null)
    try {
      const res = await fetch(`${API}/models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Utility provider access check failed')
      if (requestId !== utilityRequestRef.current) return false
      const catalog = data as ModelCatalogResponse
      setUtilityAuthenticated(catalog.authenticated)
      setUtilityAccessMessage(
        catalog.authenticated
          ? `${selectedBackend} credentials are available to DataClaw.`
          : catalog.message || `${selectedBackend} credentials are not configured.`,
      )
      return catalog.authenticated
    } catch (error) {
      if (requestId !== utilityRequestRef.current) return false
      setUtilityAuthenticated(false)
      setUtilityAccessMessage(error instanceof Error ? error.message : 'Utility provider access check failed')
      return false
    } finally {
      if (requestId === utilityRequestRef.current) setUtilityAccessLoading(false)
    }
  }

  useEffect(() => {
    if (!config.llm) return
    loadModels()
    // Credentials are deliberately omitted: API-key fields trigger loading on
    // blur/Enter so we do not send a request for every character typed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [utilityBackend, backendConfig.auth_mode])

  const updateBackendConfig = (field: string, value: any) => {
    setConfig((prev: any) => ({
      ...prev,
      llm: {
        ...prev.llm,
        backend: utilityBackend,
        [utilityBackend]: {
          ...(prev.llm?.[utilityBackend] || {}),
          [field]: value,
        },
      },
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
        agent: { ...(prev.agent || {}), runtime: 'openclaw' },
        plugins: { ...prev.plugins, openclaw: { ...(prev.plugins?.openclaw || {}), url: prev.plugins?.openclaw?.url || 'http://127.0.0.1:18789' } },
      }))
    } else if (value === 'hermes') {
      setConfig((prev: any) => ({
        ...prev,
        agent: { ...(prev.agent || {}), runtime: 'hermes' },
        plugins: {
          ...prev.plugins,
          hermes: {
            url: 'http://127.0.0.1:8642',
            dataclaw_api_url: 'http://127.0.0.1:8000',
            profile: 'dataclaw',
            request_timeout_seconds: 60,
            reconnect_timeout_seconds: 30,
            tool_callback_timeout_seconds: 330,
            ...(prev.plugins?.hermes || {}),
          },
        },
      }))
    } else {
      setConfig((prev: any) => ({
        ...prev,
        agent: { ...(prev.agent || {}), runtime: value },
      }))
    }
  }

  const setUtilityBackend = (value: string) => {
    setConfig((prev: any) => ({
      ...prev,
      llm: { ...(prev.llm || {}), backend: value },
    }))
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
        void checkUtilityAccess()
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
                void checkUtilityAccess()
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
  const [openclawStatus, setOpenclawStatus] = useState<{ installed: boolean; version?: string | null; supported?: boolean | null; min_version?: string } | null>(null)
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
  const [terminalRuntime, setTerminalRuntime] = useState<'openclaw' | 'hermes' | null>(null)
  const [hermesHealth, setHermesHealth] = useState<HermesHealthStatus | null>(null)
  const [hermesInstall, setHermesInstall] = useState<HermesInstallStatus | null>(null)
  const [checkingHermes, setCheckingHermes] = useState(false)
  const [installingHermes, setInstallingHermes] = useState(false)
  const [restartingHermes, setRestartingHermes] = useState(false)

  const checkHermes = useCallback(async () => {
    setCheckingHermes(true)
    try {
      const [healthRes, installRes] = await Promise.all([
        fetch(`${API}/hermes/health`),
        fetch(`${API}/hermes/install/status`),
      ])
      setHermesHealth(healthRes.ok ? await healthRes.json() : { status: 'not_configured' })
      setHermesInstall(installRes.ok ? await installRes.json() : { installed: false })
    } catch {
      setHermesHealth({ status: 'unhealthy' })
      setHermesInstall({ installed: false })
    }
    setCheckingHermes(false)
  }, [])

  const installHermesExtension = async () => {
    setInstallingHermes(true)
    try {
      if (isDirty && !(await save())) return
      const res = await fetch(`${API}/hermes/install/extension`, { method: 'POST' })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || 'Hermes extension setup failed')
      message.success('Hermes profile and Dataclaw extension installed; restart Hermes')
      await checkHermes()
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Hermes extension setup failed')
    } finally {
      setInstallingHermes(false)
    }
  }

  const restartHermes = useCallback(async () => {
    setRestartingHermes(true)
    try {
      const res = await fetch(`${API}/hermes/gateway/restart`, {
        method: 'POST',
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || 'Hermes restart failed')
      message.success('Hermes gateway restarted')
      await new Promise(resolve => window.setTimeout(resolve, 1_000))
      await checkHermes()
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Hermes restart failed')
      throw error
    } finally {
      setRestartingHermes(false)
    }
  }, [checkHermes])

  useEffect(() => {
    if (agentBackend !== 'hermes') return
    const timer = window.setTimeout(() => void checkHermes(), 0)
    return () => window.clearTimeout(timer)
  }, [agentBackend, checkHermes, savedConfig])

  const openTerminal = (
    runtime: 'openclaw' | 'hermes',
    command?: string,
  ) => {
    setTerminalRuntime(runtime)
    setTerminalCommand(command)
    setTerminalOpen(true)
  }

  // External runtimes own provider credentials and model configuration.
  // Refresh the matching status when the embedded terminal closes and remind
  // the user that the long-running gateway must reload the changed model.
  const closeTerminal = () => {
    const runtime = terminalRuntime
    const wasModelConfig = runtime === 'openclaw'
      ? !!terminalCommand?.includes('models')
      : runtime === 'hermes'
        ? !!terminalCommand?.match(/\smodel(?:\s|$)/)
        : false
    setTerminalOpen(false)
    setTerminalRuntime(null)
    if (runtime === 'openclaw') void checkOpenclawInstalled()
    if (runtime === 'hermes') void checkHermes()
    if (wasModelConfig && runtime === 'openclaw') {
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
    if (wasModelConfig && runtime === 'hermes') {
      const cli = shellQuote(hermesConfig.cli_path || 'hermes')
      const profile = shellQuote(hermesConfig.profile || 'dataclaw')
      Modal.warning({
        title: 'Restart Hermes to apply the new model',
        content: (
          <div>
            <p style={{ marginTop: 0 }}>
              Hermes stores provider authentication and the primary model in its own profile. Restart the profile gateway so its API server reloads that selection.
            </p>
            <code>{cli} -p {profile} gateway restart</code>
          </div>
        ),
        okText: 'Restart Hermes now',
        cancelText: 'Later',
        okCancel: true,
        onOk: restartHermes,
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
      openTerminal('openclaw', scriptPath)
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

  // Agent-runtime plugins and Codex belong to the Agent tab. Other schemas are
  // compact enough to edit directly on the Extensions tab.
  const pluginsWithConfig = plugins.filter(
    p => p.id !== 'openclaw' && p.id !== 'hermes' && p.id !== 'codex' && p.config_schema && p.config_schema.fields && p.config_schema.fields.length > 0
  )
  const hermesPlugin = plugins.find(p => p.id === 'hermes' && p.config_schema?.fields?.length)
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
  const configuredModel = agentBackend === 'hermes'
    ? hermesConfig.model || 'Profile default model'
    : agentBackend === 'openclaw'
      ? 'OpenClaw profile model'
      : backendConfig.model || 'No model selected'
  const hermesCli = hermesConfig.cli_path || 'hermes'
  const hermesProfile = hermesConfig.profile || 'dataclaw'
  const hermesModelCommand = `${shellQuote(hermesCli)} -p ${shellQuote(hermesProfile)} model`
  const hermesInstallCommand = "uv tool install --python 3.12 'hermes-agent[messaging]==0.19.0'"
  const hermesFields = Object.fromEntries(
    (hermesPlugin?.config_schema?.fields || []).map(field => [field.name, field]),
  ) as Record<string, ConfigFieldDef>
  const renderHermesField = (name: string, overrides?: Partial<ConfigFieldDef>) => {
    const field = hermesFields[name]
    if (!field) return null
    return (
      <DynamicField
        key={name}
        field={{ ...field, ...overrides }}
        value={hermesConfig[name] ?? field.default}
        onChange={value => updatePluginConfig('hermes', name, value)}
      />
    )
  }
  const utilityBackendLabel = UTILITY_BACKEND_OPTIONS.find(
    option => option.value === utilityBackend,
  )?.label || utilityBackend
  const utilityProviderConfig = backendConfig
  const utilityCodexAuthMode = llm.codex?.auth_mode || 'default'
  const utilityCodexApiKeyMissing = utilityBackend === 'codex'
    && utilityCodexAuthMode === 'api_key'
    && !String(utilityProviderConfig.api_key || '').trim()
    && utilityAuthenticated !== true
  const utilityApiKeyMissing = !!utilityBackend
    && (utilityBackend !== 'codex' || utilityCodexAuthMode === 'api_key')
    && !String(utilityProviderConfig.api_key || '').trim()
    && utilityAuthenticated !== true
  const hermesHealthLabel = hermesHealth?.status === 'healthy'
    ? 'Connected'
    : hermesHealth?.status === 'configured_inactive'
      ? 'Configured, inactive'
      : hermesHealth?.status === 'unhealthy'
        ? 'Unavailable'
        : 'Status unknown'
  const hermesHealthError = typeof hermesHealth?.last_selection_error === 'string'
    ? hermesHealth.last_selection_error
    : null
  const hermesRuntimeError = hermesHealthError || (
    runtimeStatus.configured_runtime === 'hermes'
      ? runtimeStatus.last_selection_error
      : null
  )
  const hermesUtilityCodexAuthError = !!hermesRuntimeError
    && hermesRuntimeError.includes("Codex auth_mode is 'api_key' but no API key provided")
  const hermesUtilityModelError = !!hermesRuntimeError
    && (
      hermesRuntimeError.startsWith('DataClaw utility model')
      || hermesUtilityCodexAuthError
    )
  const hermesModelSelected = hermesInstall?.model_selected
    ?? hermesInstall?.model_configured
    ?? false
  const hermesProviderAuthConfigured = hermesInstall?.provider_auth_configured
  const authLabel = modelsAuthenticated === true
    ? 'Connected'
    : modelsAuthenticated === false
      ? 'Needs attention'
      : 'Checking access'

  useEffect(() => {
    utilityRequestRef.current += 1
    setUtilityAccessLoading(false)
    setUtilityAuthenticated(null)
    setUtilityAccessMessage(null)
  }, [utilityBackend, utilityCodexAuthMode])

  return (
    <div style={{ padding: '20px clamp(16px, 4vw, 24px) 48px', maxWidth: 920, margin: '0 auto' }}>
      <div style={{ position: 'sticky', top: 0, zIndex: 20, background: 'rgba(255,255,255,.96)', padding: '4px 0 14px', marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px 16px' }}>
          <div>
            <h2 style={{ margin: 0, fontWeight: 650 }}>Settings</h2>
            <Space size={6} wrap style={{ marginTop: 7 }}>
              <Tag>{runtimeLabel}</Tag>
              {agentBackend !== 'mock' && <Tag>{configuredModel}</Tag>}
              <Tag>{`Utility: ${utilityBackendLabel}${backendConfig.model ? ` · ${backendConfig.model}` : ''}`}</Tag>
              <Tag color={modelsAuthenticated === true ? 'success' : modelsAuthenticated === false ? 'error' : 'default'}>{authLabel}</Tag>
              {runtimeStatus.configured_runtime && (
                <Tag color={runtimeStatus.last_selection_error ? 'error' : runtimeStatus.available ? 'success' : 'warning'}>
                  Active: {runtimeStatus.active_runtime || 'unknown'}
                </Tag>
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
                <TabIntro>Configure DataClaw's model once, then choose which runtime owns the primary agent loop.</TabIntro>

                <SettingsGroup
                  step="1"
                  title="Configure the DataClaw utility model"
                  description="DataClaw uses this provider for utility work, compaction, and delegated sub-agents in every runtime."
                >
                  <Field label="Provider">
                    <Select
                      value={utilityBackend}
                      onChange={setUtilityBackend}
                      style={{ width: '100%' }}
                      options={UTILITY_BACKEND_OPTIONS}
                    />
                  </Field>

                  {utilityBackend === 'codex' ? (
                    <>
                      <Field label="Sign-in method">
                        <Select
                          value={utilityCodexAuthMode}
                          onChange={value => updateByPath('llm.codex.auth_mode', value)}
                          style={{ width: '100%' }}
                          options={[
                            { value: 'default', label: 'OpenAI account (OAuth)' },
                            { value: 'api_key', label: 'OpenAI API key' },
                          ]}
                        />
                      </Field>
                      {utilityCodexAuthMode === 'api_key' ? (
                        <Field label="OpenAI API key" description="Used by DataClaw utility calls in every runtime.">
                          <Input.Password
                            value={backendConfig.api_key || ''}
                            onChange={event => updateBackendConfig('api_key', event.target.value)}
                            placeholder="Enter OpenAI API key"
                            autoComplete="new-password"
                            onBlur={loadModels}
                            onPressEnter={loadModels}
                          />
                        </Field>
                      ) : (
                        <Field label="Codex account">
                          <Space orientation="vertical" style={{ width: '100%' }}>
                            <Space size="small" wrap>
                              <Button type="primary" icon={<LoginOutlined />} loading={codexLoggingIn} onClick={() => startCodexLogin('browser')}>Sign in with browser</Button>
                              <Button loading={codexLoggingIn} onClick={() => startCodexLogin('device_code')}>Use device code</Button>
                              {(modelsAuthenticated === true || codexLoginResult?.success) && <Tag icon={<CheckCircleOutlined />} color="success">Connected</Tag>}
                            </Space>
                            {codexLoginInfo?.method === 'device_code' && codexLoginInfo.user_code && (
                              <div style={CALLOUT_STYLE}>Go to <a href={codexLoginInfo.verification_url} target="_blank" rel="noreferrer">{codexLoginInfo.verification_url}</a> and enter <strong style={{ fontFamily: 'monospace' }}>{codexLoginInfo.user_code}</strong>.</div>
                            )}
                            {codexLoggingIn && codexLoginInfo?.method === 'browser' && !codexLoginResult && (
                              <div style={CALLOUT_STYLE}>
                                <div style={{ marginBottom: 6 }}>If the browser could not redirect back, paste its <code>http://localhost:1455/…</code> URL here.</div>
                                <Space.Compact style={{ width: '100%' }}>
                                  <Input value={codexRedirectUrl} onChange={event => setCodexRedirectUrl(event.target.value)} placeholder="http://localhost:1455/auth/callback?code=…&state=…" onPressEnter={finishCodexRedirect} disabled={codexFinishingRedirect} />
                                  <Button type="primary" loading={codexFinishingRedirect} disabled={!codexRedirectUrl.trim()} onClick={finishCodexRedirect}>Submit</Button>
                                </Space.Compact>
                              </div>
                            )}
                            {codexLoggingIn && !codexLoginResult && <div style={HELP_STYLE}><LoadingOutlined style={{ marginRight: 6 }} />Waiting for sign-in to complete…</div>}
                            {codexLoginResult && !codexLoginResult.success && <Alert type="error" showIcon title={codexLoginResult.error || 'Sign-in failed'} />}
                          </Space>
                        </Field>
                      )}
                    </>
                  ) : (
                    <>
                      <Field label={`${utilityBackendLabel} API key`} description="Stored securely and used by DataClaw in every runtime.">
                        <Input.Password
                          value={backendConfig.api_key || ''}
                          onChange={event => updateBackendConfig('api_key', event.target.value)}
                          placeholder={`Enter ${utilityBackendLabel} API key`}
                          autoComplete="new-password"
                          onBlur={loadModels}
                          onPressEnter={loadModels}
                        />
                      </Field>
                      {utilityBackend === 'openai' && (
                        <Field label="API endpoint" description="Optional. Set only for an OpenAI-compatible proxy or hosted endpoint.">
                          <Input
                            value={backendConfig.base_url || ''}
                            onChange={event => updateBackendConfig('base_url', event.target.value)}
                            placeholder="https://api.openai.com/v1"
                            onBlur={loadModels}
                            onPressEnter={loadModels}
                          />
                        </Field>
                      )}
                    </>
                  )}

                  <ModelSelector
                    value={backendConfig.model || ''}
                    onChange={value => updateBackendConfig('model', value)}
                    models={availableModels}
                    loading={modelsLoading}
                    authenticated={modelsAuthenticated}
                    statusMessage={modelsMessage}
                    error={modelsError}
                    onReload={loadModels}
                  />
                  <Space wrap style={{ marginBottom: 14 }}>
                    <Button icon={<ReloadOutlined />} loading={utilityAccessLoading} onClick={() => void checkUtilityAccess()}>
                      Check utility access
                    </Button>
                    {utilityAuthenticated === true && <Tag color="success">DataClaw utility ready</Tag>}
                    {utilityAuthenticated === false && <Tag color="error">Utility credentials need attention</Tag>}
                  </Space>
                  {utilityAccessMessage && utilityAuthenticated !== null && (
                    <Alert
                      type={utilityAuthenticated ? 'success' : 'error'}
                      showIcon
                      title={utilityAccessMessage}
                      style={{ marginBottom: 14 }}
                    />
                  )}
                  {!backendConfig.model && <Alert type="warning" showIcon title="Choose a DataClaw utility model" style={{ marginBottom: 14 }} />}
                  {utilityCodexApiKeyMissing && (
                    <Alert
                      type="error"
                      showIcon
                      title="DataClaw utility Codex is set to API-key sign-in"
                      description="Use Codex OAuth, or keep API-key mode and enter an OpenAI API key."
                      action={<Button size="small" onClick={() => updateByPath('llm.codex.auth_mode', 'default')}>Use Codex OAuth</Button>}
                      style={{ marginBottom: 14 }}
                    />
                  )}
                  {utilityApiKeyMissing && !utilityCodexApiKeyMissing && (
                    <Alert type="error" showIcon title={`${utilityBackendLabel} API key required for DataClaw utility calls`} style={{ marginBottom: 14 }} />
                  )}
                </SettingsGroup>

                <SettingsGroup
                  step="2"
                  title="Choose the agent runtime"
                  description="DataClaw uses the utility model above as its agent. Hermes and OpenClaw use their own primary models while retaining the same DataClaw utility provider."
                >
                  <Field label="Agent runtime">
                    <Select value={agentBackend} onChange={setAgentBackend} style={{ width: '100%' }} options={AGENT_RUNTIME_OPTIONS} />
                  </Field>
                  {agentBackend === 'dataclaw' && (
                    <Alert type="info" showIcon title={`DataClaw will run the primary agent with ${utilityBackendLabel} · ${backendConfig.model || 'select a model above'}`} style={{ marginBottom: 14 }} />
                  )}
                  {agentBackend === 'mock' && <Alert type="warning" showIcon title="Testing runtime" description="Returns test responses without calling the configured utility model." style={{ marginBottom: 14 }} />}
                </SettingsGroup>

                {agentBackend === 'hermes' && (
                  <div data-testid="hermes-runtime-setup">
                    <Divider />
                    <SectionTitle title="Hermes Agent" description="Hermes owns the agent loop; DataClaw keeps conversation history, tools, policy, approvals, and run visibility." />
                    {!hermesPlugin && <Alert type="warning" showIcon title="Hermes adapter is not installed" />}

                    {hermesPlugin && (
                      <>
                        <div data-testid="hermes-readiness" style={{ ...CALLOUT_STYLE, marginBottom: 14 }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
                            <Space wrap size={[6, 6]}>
                              <strong style={{ fontSize: 13, color: '#333' }}>Setup status</strong>
                              <Tag color={hermesHealth?.status === 'healthy' ? 'success' : hermesHealth?.status === 'unhealthy' ? 'error' : 'default'}>
                                {hermesHealthLabel}
                              </Tag>
                              <Tag color={!hermesInstall?.installed ? 'default' : hermesInstall?.version_compatible ? 'success' : 'error'}>
                                {!hermesInstall?.installed
                                  ? 'CLI not found'
                                  : hermesInstall?.version_compatible
                                    ? `CLI ${hermesInstall.version || hermesInstall.compatible_version || 'installed'}`
                                    : `CLI ${hermesInstall.version || 'incompatible'}`}
                              </Tag>
                              <Tag color={hermesInstall?.extension_installed && hermesInstall?.restricted_profile ? 'success' : 'warning'}>
                                {hermesInstall?.extension_installed && hermesInstall?.restricted_profile ? 'Bridge ready' : 'Bridge setup needed'}
                              </Tag>
                            </Space>
                            <Button size="small" icon={<ReloadOutlined />} onClick={checkHermes} loading={checkingHermes}>Refresh</Button>
                          </div>
                          {hermesRuntimeError && (
                            <Alert
                              type="error"
                              showIcon
                              title={hermesUtilityModelError
                                ? 'Hermes is configured; the DataClaw utility model needs authentication'
                                : 'Hermes cannot start with the current settings'}
                              description={hermesUtilityCodexAuthError
                                ? 'Hermes provider sign-in succeeded. DataClaw utility calls are separately set to Codex API-key authentication, but no API key is saved.'
                                : hermesRuntimeError}
                              action={hermesUtilityCodexAuthError && utilityCodexApiKeyMissing
                                ? (
                                    <Button
                                      size="small"
                                      onClick={() => updateByPath('llm.codex.auth_mode', 'default')}
                                    >
                                      Use Codex OAuth
                                    </Button>
                                  )
                                : undefined}
                              style={{ marginTop: 10 }}
                            />
                          )}
                        </div>

                        <SettingsGroup
                          step="1"
                          title="Connect DataClaw and Hermes"
                          description="These values let DataClaw reach the Hermes API and let Hermes call DataClaw tools."
                        >
                          {renderHermesField('url')}
                          {renderHermesField('api_key')}
                          <div style={FIELD_GRID_STYLE}>
                            {renderHermesField('dataclaw_api_url')}
                            {renderHermesField('profile')}
                          </div>
                          {!hermesConfig.api_key && (
                            <Alert
                              type="info"
                              showIcon
                              title="Add a Hermes API key to continue"
                              description="Hermes 0.19 requires this bearer key even on loopback. Setup writes the same value to the restricted profile."
                              style={{ marginBottom: 14 }}
                            />
                          )}
                          <div style={{ ...HELP_STYLE, marginBottom: 14 }}>
                            Local/private deployment only: callback routes are unauthenticated, so keep DataClaw and Hermes on loopback or a trusted private network.
                          </div>
                        </SettingsGroup>

                        <SettingsGroup
                          step="2"
                          title="Install the CLI and tool bridge"
                          description="Use the Hermes 0.19 CLI, then create or update the restricted DataClaw profile."
                        >
                          <Space wrap style={{ marginBottom: 14 }}>
                            <Tag color={!hermesInstall?.installed ? 'default' : hermesInstall?.version_compatible ? 'success' : 'error'}>
                              {!hermesInstall?.installed
                                ? 'CLI not installed'
                                : hermesInstall?.version_compatible
                                  ? `CLI ${hermesInstall.version || hermesInstall.compatible_version || 'installed'}`
                                  : `Incompatible CLI ${hermesInstall.version || ''}`}
                            </Tag>
                            <Tag color={hermesInstall?.extension_installed && hermesInstall?.restricted_profile ? 'success' : 'warning'}>
                              {hermesInstall?.extension_installed && hermesInstall?.restricted_profile ? 'Restricted bridge installed' : 'Bridge setup required'}
                            </Tag>
                          </Space>
                          <Space wrap style={{ marginBottom: 14 }}>
                            {(!hermesInstall?.installed || !hermesInstall?.version_compatible) && (
                              <Button icon={<DownloadOutlined />} onClick={() => openTerminal('hermes', hermesInstallCommand)}>
                                Install compatible CLI
                              </Button>
                            )}
                            <Button
                              type="primary"
                              icon={<DownloadOutlined />}
                              onClick={installHermesExtension}
                              loading={installingHermes}
                              disabled={!hermesInstall?.installed || !hermesInstall?.version_compatible || !hermesConfig.api_key}
                            >
                              {isDirty
                                ? 'Save & set up bridge'
                                : hermesInstall?.extension_installed && hermesInstall?.restricted_profile
                                  ? 'Update bridge'
                                  : 'Set up profile and bridge'}
                            </Button>
                            <Button icon={<CodeOutlined />} onClick={() => openTerminal('hermes')} disabled={!hermesInstall?.installed}>
                              Open terminal
                            </Button>
                          </Space>
                        </SettingsGroup>

                        <SettingsGroup
                          step="3"
                          title="Choose the Hermes primary model"
                          description="Provider sign-in and the primary model live in the Hermes profile, independently of DataClaw credentials."
                        >
                          <Space wrap style={{ marginBottom: 12 }}>
                            <Tag color={!hermesModelSelected ? 'warning' : hermesProviderAuthConfigured === true ? 'success' : hermesProviderAuthConfigured === false ? 'error' : 'warning'}>
                              {!hermesModelSelected
                                ? 'Model sign-in required'
                                : hermesProviderAuthConfigured === true
                                  ? `${hermesInstall?.provider ? `${hermesInstall.provider} · ` : ''}${hermesInstall?.model} · credentials found`
                                  : hermesProviderAuthConfigured === false
                                    ? `${hermesInstall?.provider ? `${hermesInstall.provider} · ` : ''}${hermesInstall?.model} · no credentials detected`
                                    : `${hermesInstall?.provider ? `${hermesInstall.provider} · ` : ''}${hermesInstall?.model} · auth status unknown`}
                            </Tag>
                            {hermesModelSelected && <span style={HELP_STYLE}>Restart after changing this selection.</span>}
                          </Space>
                          {hermesModelSelected && hermesProviderAuthConfigured === false && (
                            <Alert
                              type="warning"
                              showIcon
                              title={`No credentials detected for ${hermesInstall?.provider || 'the selected Hermes provider'}`}
                              description="Run model setup again to sign in or add an API key. For a deliberately auth-free local provider, this warning can be ignored after a successful test run."
                              style={{ marginBottom: 14 }}
                            />
                          )}
                          <Space wrap style={{ marginBottom: 14 }}>
                            <Button
                              type="primary"
                              icon={<LoginOutlined />}
                              onClick={() => openTerminal('hermes', hermesModelCommand)}
                              disabled={!hermesInstall?.installed || !hermesInstall?.version_compatible}
                            >
                              Configure model / sign in
                            </Button>
                            <Button
                              icon={<ReloadOutlined />}
                              loading={restartingHermes}
                              onClick={() => void restartHermes().catch(() => {})}
                              disabled={!hermesInstall?.installed || !hermesInstall?.version_compatible}
                              title={!hermesInstall?.installed ? 'Install the compatible Hermes CLI first' : undefined}
                            >
                              Restart gateway
                            </Button>
                          </Space>
                        </SettingsGroup>

                        <details style={{ ...SETTINGS_GROUP_STYLE, paddingBottom: 14 }}>
                          <summary style={{ cursor: 'pointer', fontWeight: 600, color: '#444' }}>Advanced Hermes settings</summary>
                          <div style={{ ...HELP_STYLE, margin: '6px 0 14px' }}>
                            Override profile routing, executable discovery, or timeout defaults only when needed.
                          </div>
                          {renderHermesField('model', {
                            label: 'API model route override',
                            description: 'Leave blank to use the primary model selected in the Hermes profile.',
                          })}
                          {renderHermesField('cli_path')}
                          <div style={FIELD_GRID_STYLE}>
                            {renderHermesField('request_timeout_seconds')}
                            {renderHermesField('reconnect_timeout_seconds')}
                            {renderHermesField('tool_callback_timeout_seconds')}
                          </div>
                        </details>
                      </>
                    )}
                  </div>
                )}

                {agentBackend === 'openclaw' && (
                  <div data-testid="openclaw-runtime-setup">
                    <Divider />
                    <SectionTitle title="OpenClaw" description="The external runtime connection and local OpenClaw installation are managed together here." />
                    <Field label="Gateway URL">
                      <Input value={openclawConfig.url || ''} onChange={e => updatePluginConfig('openclaw', 'url', e.target.value)} placeholder="http://127.0.0.1:18789" />
                    </Field>
                    <Field label="Token" description="Shared by DataClaw and the OpenClaw gateway.">
                      <Space.Compact style={{ width: '100%' }}>
                        <Input.Password value={openclawConfig.token || ''} onChange={e => updatePluginConfig('openclaw', 'token', e.target.value)} placeholder="(Dataclaw API token)" />
                        <Button onClick={fetchOpenClawToken}>Load token</Button>
                      </Space.Compact>
                    </Field>
                    <Field label="Callback URL" description="Address OpenClaw uses for DataClaw tools. Use host.docker.internal when OpenClaw runs in Docker.">
                      <Input value={openclawConfig.tools_api_url || ''} onChange={e => updatePluginConfig('openclaw', 'tools_api_url', e.target.value)} placeholder="http://localhost:8000" />
                    </Field>
                    <Field label="Timeout" description="Set 0 to wait indefinitely.">
                      <NumberWithUnit ariaLabel="OpenClaw timeout" value={openclawConfig.wait_ms ?? 0} onChange={v => updatePluginConfig('openclaw', 'wait_ms', v)} min={0} max={900000} unit="ms" />
                    </Field>

                    <Divider />
                    <SectionTitle title="Model provider" description="The model OpenClaw's agent runs on. OpenRouter is configured here; other providers sign in from a terminal." />
                    <OpenClawModelProvider onOpenTerminal={() => openTerminal('openclaw', 'openclaw models auth login --set-default')} />

                    <Divider />
                    <SectionTitle title="OpenClaw installation and authentication" description="Install or maintain the CLI, then authenticate its model provider. These credentials belong to OpenClaw." />
                    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                      <Space wrap>
                        {checkingOpenclaw ? <Tag icon={<LoadingOutlined />} color="processing">Checking</Tag> : openclawStatus?.installed ? (openclawStatus.supported === false ? <Tag icon={<CloseCircleOutlined />} color="warning">{`${openclawStatus.version} — requires ${openclawStatus.min_version} or newer`}</Tag> : <Tag icon={<CheckCircleOutlined />} color="success">{openclawStatus.version || 'Installed'}</Tag>) : <Tag icon={<CloseCircleOutlined />}>{openclawStatus === null ? 'Status unknown' : 'Not installed'}</Tag>}
                        <Button onClick={checkOpenclawInstalled} loading={checkingOpenclaw}>Check status</Button>
                        <Button type="primary" icon={<DownloadOutlined />} onClick={handleOpenclawInstall}>Install</Button>
                        {openclawStatus?.installed && <Button icon={<LoginOutlined />} onClick={() => openTerminal('openclaw', 'openclaw models auth login --set-default')}>Configure model / sign in</Button>}
                        {openclawStatus?.installed && <Button icon={<CodeOutlined />} onClick={() => openTerminal('openclaw')}>Open terminal</Button>}
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
                  </div>
                )}

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
                <TabIntro>Configure installed plugin settings directly. Runtime and Codex controls are on the Agent tab.</TabIntro>
                {pluginsWithConfig.map((plugin, index) => (
                  <div key={plugin.id} style={index === pluginsWithConfig.length - 1 ? { padding: '2px 0 0' } : EXTENSION_SECTION_STYLE}>
                    <SectionTitle title={plugin.config_schema!.title || plugin.label} />
                    {plugin.config_schema!.fields.map(field => (
                      <DynamicField key={field.name} field={field} value={(pluginsConfig[plugin.id] || {})[field.name] ?? field.default} onChange={v => updatePluginConfig(plugin.id, field.name, v)} />
                    ))}
                  </div>
                ))}
                {pluginsWithConfig.length === 0 && <Alert type="info" showIcon title="No configurable extensions installed" description="Runtime and Codex controls are available on the Agent tab." />}
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

      <Modal
        title={
          terminalRuntime === 'hermes'
            ? terminalCommand?.includes('uv tool install')
              ? 'Install Hermes CLI'
              : terminalCommand?.match(/\smodel(?:\s|$)/)
                ? 'Configure Hermes model and authentication'
                : 'Hermes terminal'
            : terminalCommand?.includes('install')
              ? 'Install and configure OpenClaw'
              : terminalCommand?.includes('models')
                ? 'Configure OpenClaw model and authentication'
                : 'OpenClaw terminal'
        }
        open={terminalOpen}
        onCancel={closeTerminal}
        footer={<Button onClick={closeTerminal}>Close</Button>}
        width={720}
        destroyOnHidden
      >
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

function SettingsGroup({
  step,
  title,
  description,
  children,
}: {
  step: string
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <section style={SETTINGS_GROUP_STYLE}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 14 }}>
        <div
          aria-hidden="true"
          style={{
            flex: '0 0 auto',
            width: 24,
            height: 24,
            borderRadius: 12,
            background: '#eaf1ff',
            color: '#2468e5',
            display: 'grid',
            placeItems: 'center',
            fontSize: 12,
            fontWeight: 700,
          }}
        >
          {step}
        </div>
        <div style={{ minWidth: 0 }}>
          <h3 style={{ fontSize: 14, lineHeight: '24px', margin: 0, color: '#333' }}>{title}</h3>
          <div style={{ ...HELP_STYLE, marginTop: 2 }}>{description}</div>
        </div>
      </div>
      {children}
    </section>
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
      case 'secret':
        return <Input.Password value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled} />
      case 'string':
      default:
        return /(?:api[_-]?key|token|secret|password)/i.test(field.name)
          ? <Input.Password value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled} autoComplete="new-password" />
          : <Input value={value || ''} onChange={e => onChange(e.target.value)} disabled={disabled} />
    }
  }
  return (
    <Field label={field.label} description={field.description}>
      {renderInput()}
    </Field>
  )
}
