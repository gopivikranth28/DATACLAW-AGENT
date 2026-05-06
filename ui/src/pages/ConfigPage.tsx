import { useState, useEffect, useRef } from 'react'
import { Alert, Card, Select, Input, InputNumber, Switch, Button, Modal, Tag, Space, Divider, message } from 'antd'
import { SaveOutlined, CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined, LoadingOutlined, DownloadOutlined, CodeOutlined, LoginOutlined } from '@ant-design/icons'
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
  }
}

interface Props {
  plugins: PluginInfo[]
}

export default function ConfigPage({ plugins }: Props) {
  const [config, setConfig] = useState<any>({})
  const [saving, setSaving] = useState(false)
  const [providers, setProviders] = useState<ProviderInfo[]>([])

  useEffect(() => {
    fetch(`${API}/config`)
      .then(r => r.json())
      .then(setConfig)
      .catch(() => message.error('Failed to load config'))
    fetch(`${API}/providers`)
      .then(r => r.json())
      .then(setProviders)
      .catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const res = await fetch(`${API}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (res.ok) {
        message.success('Configuration saved')
        // Re-fetch providers so config schemas reflect the new backend selections
        fetch(`${API}/providers`).then(r => r.json()).then(setProviders).catch(() => {})
      }
      else message.error('Failed to save')
    } catch {
      message.error('Failed to save')
    }
    setSaving(false)
  }

  const llm = config.llm || {}
  const backend = llm.backend || 'openclaw'
  const backendConfig = llm[backend] || {}
  const app = config.app || {}
  const pluginsConfig = config.plugins || {}
  const openclawConfig = pluginsConfig.openclaw || {}
  const agentBackend = backend === 'openclaw' ? 'openclaw' : backend

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
        plugins: { ...prev.plugins, openclaw: { ...(prev.plugins?.openclaw || {}), url: '' } },
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
              if (evt.success) message.success('Codex login successful')
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
  const [checking, setChecking] = useState<Record<string, boolean>>({})
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

  // Plugins with config schemas (exclude openclaw — handled inline in Agent Backend card)
  const pluginsWithConfig = plugins.filter(
    p => p.id !== 'openclaw' && p.config_schema && p.config_schema.fields && p.config_schema.fields.length > 0
  )

  return (
    <div style={{ padding: 24, maxWidth: 640, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontWeight: 600 }}>Configuration</h2>
        <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving}>
          Save
        </Button>
      </div>

      {/* Agent Backend */}
      <Card size="small" title="Agent Backend" style={{ marginBottom: 16 }}>
        <Field label="Provider">
          <Select
            value={agentBackend}
            onChange={setAgentBackend}
            style={{ width: '100%' }}
            options={[
              { value: 'mock', label: 'Mock (Testing)' },
              { value: 'anthropic', label: 'Anthropic (Claude)' },
              { value: 'openai', label: 'OpenAI' },
              { value: 'gemini', label: 'Google Gemini' },
              { value: 'codex', label: 'OpenAI Codex' },
              { value: 'openclaw', label: 'OpenClaw (External Agent)' },
            ]}
          />
        </Field>

        {/* LLM provider fields (anthropic / openai / gemini) */}
        {agentBackend !== 'mock' && agentBackend !== 'openclaw' && agentBackend !== 'codex' && (
          <>
            <Field label="API Key">
              <Input.Password
                value={backendConfig.api_key || ''}
                onChange={e => updateBackendConfig('api_key', e.target.value)}
                placeholder="Enter API key"
              />
            </Field>
            <Field label="Model">
              <Input
                value={backendConfig.model || ''}
                onChange={e => updateBackendConfig('model', e.target.value)}
                placeholder={agentBackend === 'anthropic' ? 'claude-sonnet-4-20250514' : agentBackend === 'openai' ? 'gpt-4o' : 'gemini-2.5-flash'}
              />
            </Field>
            {agentBackend === 'openai' && (
              <Field label="Base URL (optional)">
                <Input
                  value={backendConfig.base_url || ''}
                  onChange={e => updateBackendConfig('base_url', e.target.value)}
                  placeholder="https://api.openai.com/v1"
                />
              </Field>
            )}
          </>
        )}

        {/* Codex fields */}
        {agentBackend === 'codex' && (
          <>
            <Field label="Authentication">
              <Select
                value={backendConfig.auth_mode || 'default'}
                onChange={v => updateBackendConfig('auth_mode', v)}
                style={{ width: '100%' }}
                options={[
                  { value: 'default', label: 'OAuth Login' },
                  { value: 'api_key', label: 'API Key' },
                ]}
              />
            </Field>
            {backendConfig.auth_mode === 'api_key' && (
              <Field label="API Key">
                <Input.Password
                  value={backendConfig.api_key || ''}
                  onChange={e => updateBackendConfig('api_key', e.target.value)}
                  placeholder="Enter OpenAI API key"
                />
              </Field>
            )}
            {(!backendConfig.auth_mode || backendConfig.auth_mode === 'default') && (
              <Field label="Codex Login">
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space size="small">
                    <Button
                      type="primary"
                      icon={<LoginOutlined />}
                      loading={codexLoggingIn}
                      onClick={() => startCodexLogin('browser')}
                    >
                      Login with Browser
                    </Button>
                    <Button
                      loading={codexLoggingIn}
                      onClick={() => startCodexLogin('device_code')}
                    >
                      Device Code
                    </Button>
                  </Space>
                  {codexLoginInfo?.method === 'device_code' && codexLoginInfo.user_code && (
                    <div style={{ background: '#f5f5f5', padding: '8px 12px', borderRadius: 6, fontSize: 13 }}>
                      Go to <a href={codexLoginInfo.verification_url} target="_blank" rel="noreferrer">{codexLoginInfo.verification_url}</a> and enter code: <strong style={{ fontFamily: 'monospace', fontSize: 15 }}>{codexLoginInfo.user_code}</strong>
                    </div>
                  )}
                  {codexLoggingIn && codexLoginInfo?.method === 'browser' && !codexLoginResult && (
                    <div style={{ background: '#fafafa', padding: '8px 12px', borderRadius: 6, fontSize: 12, color: '#555' }}>
                      <div style={{ marginBottom: 6 }}>
                        Browser didn't redirect back automatically? Paste the URL it tried to open (something starting with <code>http://localhost:1455/</code>) below — we'll replay it inside the container.
                      </div>
                      <Space.Compact style={{ width: '100%' }}>
                        <Input
                          value={codexRedirectUrl}
                          onChange={e => setCodexRedirectUrl(e.target.value)}
                          placeholder="http://localhost:1455/auth/callback?code=…&state=…"
                          onPressEnter={finishCodexRedirect}
                          disabled={codexFinishingRedirect}
                        />
                        <Button
                          type="primary"
                          loading={codexFinishingRedirect}
                          disabled={!codexRedirectUrl.trim()}
                          onClick={finishCodexRedirect}
                        >
                          Submit
                        </Button>
                      </Space.Compact>
                    </div>
                  )}
                  {codexLoggingIn && !codexLoginResult && (
                    <div style={{ fontSize: 12, color: '#999' }}>
                      <LoadingOutlined style={{ marginRight: 6 }} />Waiting for login to complete...
                    </div>
                  )}
                  {codexLoginResult && (
                    <Tag
                      icon={codexLoginResult.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                      color={codexLoginResult.success ? 'success' : 'error'}
                    >
                      {codexLoginResult.success ? 'Logged in' : (codexLoginResult.error || 'Login failed')}
                    </Tag>
                  )}
                </Space>
              </Field>
            )}
            <Field label="Model">
              <Input
                value={backendConfig.model || ''}
                onChange={e => updateBackendConfig('model', e.target.value)}
                placeholder="gpt-5.5"
              />
            </Field>
          </>
        )}

        {/* OpenClaw fields */}
        {agentBackend === 'openclaw' && (
          <>
            <Field label="OpenClaw Gateway URL">
              <Input
                value={openclawConfig.url || ''}
                onChange={e => updatePluginConfig('openclaw', 'url', e.target.value)}
                placeholder="http://127.0.0.1:18789"
              />
            </Field>
            <Field label="Shared Token">
              <Space.Compact style={{ width: '100%' }}>
                <Input.Password
                  value={openclawConfig.token || ''}
                  onChange={e => updatePluginConfig('openclaw', 'token', e.target.value)}
                  placeholder="dataclaw-local"
                />
                <Button onClick={fetchOpenClawToken} title="Fetch from .openclaw/openclaw.json">
                  Fetch
                </Button>
              </Space.Compact>
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Shared between Dataclaw and OpenClaw (sent in X-Dataclaw-Token header in both directions). Must match DATACLAW_TOKEN on the OpenClaw side.
              </div>
            </Field>
            <Field label="Dataclaw API URL (as seen by OpenClaw)">
              <Input
                value={openclawConfig.tools_api_url || ''}
                onChange={e => updatePluginConfig('openclaw', 'tools_api_url', e.target.value)}
                placeholder="http://localhost:8000"
              />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Base URL OpenClaw uses to call back into Dataclaw. Use <code>http://host.docker.internal:8000</code> when OpenClaw runs in Docker on the same host.
              </div>
            </Field>
            <Field label="Wait Timeout (ms)">
              <InputNumber
                value={openclawConfig.wait_ms ?? 0}
                onChange={v => updatePluginConfig('openclaw', 'wait_ms', v)}
                min={0} max={900000} style={{ width: '100%' }}
              />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                0 = no timeout (wait indefinitely)
              </div>
            </Field>

            <Divider style={{ margin: '16px 0 12px' }}>OpenClaw Installation</Divider>

            <div style={{ padding: '8px 0', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>OpenClaw CLI</span>
                {checkingOpenclaw ? (
                  <Tag icon={<LoadingOutlined />} color="processing">checking</Tag>
                ) : openclawStatus === null ? (
                  <Tag icon={<QuestionCircleOutlined />}>unknown</Tag>
                ) : openclawStatus.installed ? (
                  <Tag icon={<CheckCircleOutlined />} color="success">{openclawStatus.version || 'installed'}</Tag>
                ) : (
                  <Tag icon={<CloseCircleOutlined />} color="default">not installed</Tag>
                )}
              </div>
              <Space size="small" wrap>
                <Button size="small" onClick={checkOpenclawInstalled} loading={checkingOpenclaw}>
                  Status
                </Button>
                <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={handleOpenclawInstall}>
                  Install
                </Button>
                {openclawStatus?.installed && (
                  <>
                    <Button size="small" onClick={() => { setTerminalCommand('openclaw models auth login --set-default'); setTerminalOpen(true) }}>
                      Configure Model
                    </Button>
                    <Button size="small" icon={<CodeOutlined />} onClick={() => { setTerminalCommand(undefined); setTerminalOpen(true) }} title="Open terminal">
                      Terminal
                    </Button>
                  </>
                )}
              </Space>
            </div>

            <Field label="OpenClaw CLI Command">
              <Input
                value={openclawConfig.openclaw_cmd || ''}
                onChange={e => updatePluginConfig('openclaw', 'openclaw_cmd', e.target.value)}
                placeholder="openclaw"
              />
            </Field>
            <Field label="OpenClaw Config Directory">
              <Input
                value={openclawConfig.openclaw_dir || ''}
                onChange={e => updatePluginConfig('openclaw', 'openclaw_dir', e.target.value)}
                placeholder={`${window.location.hostname === 'localhost' ? '~' : '/home/user'}`}
              />
            </Field>
            <Field label="Plugin Source Directory (Dataclaw side)">
              <Input
                value={openclawConfig.plugins_source_dir || ''}
                onChange={e => updatePluginConfig('openclaw', 'plugins_source_dir', e.target.value)}
                placeholder="(auto-detected)"
              />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Path to the openclaw-plugins directory as Dataclaw sees it. Used for the pre-flight manifest read.
              </div>
            </Field>
            <Field label="Plugin Source Directory (OpenClaw side)">
              <Input
                value={openclawConfig.openclaw_plugins_dir || ''}
                onChange={e => updatePluginConfig('openclaw', 'openclaw_plugins_dir', e.target.value)}
                placeholder="(same as Dataclaw side)"
              />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Path the OpenClaw CLI sees. Override when OpenClaw runs in Docker and the source is mounted at a different path (e.g. <code>/dataclaw/openclaw-plugins</code>). Leave blank to reuse the Dataclaw-side path.
              </div>
            </Field>

            <Divider style={{ margin: '12px 0 8px' }} dashed>Plugins</Divider>

            {openclawPlugins.map(pid => {
              const status = pluginStatus[pid]
              const isChecking = checking[pid]
              const sync = syncStatus[pid]
              const driftDetected = !!sync && sync.has_snapshot && !sync.in_sync
              return (
                <div key={pid} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 13, fontFamily: 'monospace' }}>{pid}</span>
                      {isChecking ? (
                        <Tag icon={<LoadingOutlined />} color="processing">checking</Tag>
                      ) : status === undefined ? (
                        <Tag icon={<QuestionCircleOutlined />}>unknown</Tag>
                      ) : status === null ? (
                        <Tag icon={<CloseCircleOutlined />} color="error">error</Tag>
                      ) : status.installed ? (
                        <Tag icon={<CheckCircleOutlined />} color="success">{status.status || 'installed'}</Tag>
                      ) : (
                        <Tag icon={<CloseCircleOutlined />} color="default">not installed</Tag>
                      )}
                      {driftDetected && (
                        <Tag color="warning">{sync.added.length + sync.removed.length} tool change(s) pending</Tag>
                      )}
                    </div>
                    <Space size="small">
                      <Button size="small" onClick={() => checkPluginStatus(pid)} loading={isChecking}>
                        Status
                      </Button>
                      <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => { setInstallModalTarget(pid); setBuildOutput('') }}>
                        {status?.installed ? 'Update' : 'Install'}
                      </Button>
                    </Space>
                  </div>
                  {driftDetected && (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ margin: '0 0 8px' }}
                      message={`Tools changed since last install — reinstall the ${pid} plugin so OpenClaw picks up the changes`}
                      description={
                        <div style={{ fontSize: 12 }}>
                          {sync.added.length > 0 && (
                            <div>
                              <strong>Added ({sync.added.length}):</strong>{' '}
                              <span style={{ fontFamily: 'monospace' }}>{sync.added.join(', ')}</span>
                            </div>
                          )}
                          {sync.removed.length > 0 && (
                            <div>
                              <strong>Removed ({sync.removed.length}):</strong>{' '}
                              <span style={{ fontFamily: 'monospace' }}>{sync.removed.join(', ')}</span>
                            </div>
                          )}
                          {sync.installed_at && (
                            <div style={{ color: '#999', marginTop: 4 }}>
                              Last installed: {new Date(sync.installed_at).toLocaleString()}
                            </div>
                          )}
                        </div>
                      }
                      action={
                        <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => { setInstallModalTarget(pid); setBuildOutput('') }}>
                          Update
                        </Button>
                      }
                    />
                  )}
                </div>
              )
            })}
          </>
        )}
      </Card>

      {/* OpenClaw Install Modal */}
      <Modal
        title={`${installModalTarget !== 'openclaw' && pluginStatus[installModalTarget || '']?.installed ? 'Update' : 'Install'} ${installModalTarget === 'openclaw' ? 'OpenClaw' : installModalTarget || ''}`}
        open={!!installModalTarget}
        onCancel={() => { if (!installing) setInstallModalTarget(null) }}
        footer={[
          <Button key="close" onClick={() => setInstallModalTarget(null)} disabled={installing}>
            Close
          </Button>,
          <Button
            key="install"
            type="primary"
            icon={<DownloadOutlined />}
            loading={installing}
            onClick={handleModalInstall}
          >
            {installing ? 'Installing...' : 'Install'}
          </Button>,
        ]}
        width={640}
        maskClosable={!installing}
      >
        {installModalTarget && (
          <div>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
              {installModalTarget === 'openclaw'
                ? 'This will download and install the OpenClaw CLI, run non-interactive onboard, and start the gateway.'
                : <>This will configure environment variables, restart the OpenClaw gateway, and install the <code>{installModalTarget}</code> plugin. Make sure config is saved first.</>
              }
            </div>
            {buildOutput ? (
              <pre
                ref={outputRef}
                style={{
                  background: '#1e1e1e',
                  color: '#d4d4d4',
                  padding: 12,
                  borderRadius: 6,
                  fontSize: 12,
                  fontFamily: 'monospace',
                  maxHeight: 400,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {buildOutput}
              </pre>
            ) : !installing ? (
              <div style={{ color: '#999', fontStyle: 'italic' }}>
                Click Install to begin.
              </div>
            ) : null}
          </div>
        )}
      </Modal>

      {/* App */}
      <Card size="small" title="App Settings" style={{ marginBottom: 16 }}>
        <Field label="Debug Mode">
          <Switch checked={app.debug || false} onChange={v => updateApp('debug', v)} />
        </Field>
        <Field label="Max Agent Turns">
          <InputNumber value={app.max_turns ?? 30} onChange={v => updateApp('max_turns', v)} min={1} max={100} style={{ width: '100%' }} />
        </Field>
      </Card>

      {/* Interactive Terminal Modal */}
      <Modal
        title={terminalCommand?.includes('install') ? 'Install & Configure OpenClaw' : terminalCommand?.includes('models') ? 'Configure OpenClaw Model' : 'OpenClaw Terminal'}
        open={terminalOpen}
        onCancel={closeTerminal}
        footer={<Button onClick={closeTerminal}>Close</Button>}
        width={720}
        destroyOnClose
      >
        {terminalOpen && (
          <WebTerminal
            wsUrl={`${wsBase}/terminal/ws`}
            initialCommand={terminalCommand}
            style={{ height: 400 }}
          />
        )}
      </Modal>

      {/* Dynamic plugin config sections */}
      {pluginsWithConfig.map(plugin => (
        <Card
          key={plugin.id}
          size="small"
          title={plugin.config_schema!.title || plugin.label}
          style={{ marginBottom: 16 }}
        >
          {plugin.config_schema!.fields.map(field => (
            <DynamicField
              key={field.name}
              field={field}
              value={(pluginsConfig[plugin.id] || {})[field.name] ?? field.default}
              onChange={v => updatePluginConfig(plugin.id, field.name, v)}
            />
          ))}
        </Card>
      ))}

      {/* Dynamic provider config sections */}
      {providers
        .filter(p => p.backend || (p.config_schema && p.config_schema.length > 0))
        .filter(p => !["agent", "llm", "system_prompt", "tool_availability", "skill", "sub_agent"].includes(p.slot))
        .map(provider => {
          const title = provider.slot.charAt(0).toUpperCase() + provider.slot.slice(1).replace(/_/g, ' ')
          const configValues = provider.config_path ? getByPath(config, provider.config_path) || {} : {}
          const outsourcedToOpenclaw =
            agentBackend === 'openclaw' && (provider.slot === 'compaction' || provider.slot === 'memory')
          return (
            <Card key={provider.slot} size="small" title={`${title} Provider`} style={{ marginBottom: 16 }}>
              {outsourcedToOpenclaw && (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`${title} is handled by OpenClaw`}
                  description={`While the agent backend is set to OpenClaw, ${provider.slot} runs inside the OpenClaw agent loop. Settings on this card are unused.`}
                />
              )}
              {provider.backend && (
                <Field label="Backend">
                  <Select
                    value={getByPath(config, provider.backend.config_key) ?? provider.backend.current}
                    onChange={v => {
                      updateByPath(provider.backend!.config_key, v)
                      // Persist backend change and refresh provider schemas immediately
                      const parts = provider.backend!.config_key.split('.')
                      const patch: any = {}
                      let cur = patch
                      for (let i = 0; i < parts.length - 1; i++) { cur[parts[i]] = {}; cur = cur[parts[i]] }
                      cur[parts[parts.length - 1]] = v
                      fetch(`${API}/config`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(patch),
                      }).then(() =>
                        fetch(`${API}/providers`).then(r => r.json()).then(setProviders)
                      ).catch(() => {})
                    }}
                    style={{ width: '100%' }}
                    options={provider.backend.options}
                  />
                </Field>
              )}
              {provider.config_path && provider.config_schema.map(field => (
                <DynamicField
                  key={field.name}
                  field={field}
                  value={configValues[field.name] ?? field.default}
                  onChange={v => updateByPath(`${provider.config_path}.${field.name}`, v)}
                />
              ))}
              {provider.backend && !provider.config_path && (
                <div style={{ fontSize: 12, color: '#999', fontStyle: 'italic' }}>
                  No configuration options for this backend.
                </div>
              )}
            </Card>
          )
        })
      }
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  )
}

function DynamicField({ field, value, onChange }: { field: ConfigFieldDef; value: any; onChange: (v: any) => void }) {
  const renderInput = () => {
    switch (field.field_type) {
      case 'bool':
        return <Switch checked={!!value} onChange={onChange} />
      case 'int':
        return <InputNumber value={value} onChange={onChange} style={{ width: '100%' }} />
      case 'select':
        return (
          <Select value={value} onChange={onChange} style={{ width: '100%' }}
            options={(field.options || []).map(o => ({ value: o.value, label: o.label }))} />
        )
      case 'string':
      default:
        return <Input value={value || ''} onChange={e => onChange(e.target.value)} />
    }
  }
  return (
    <Field label={field.label}>
      {renderInput()}
      {field.description && <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{field.description}</div>}
    </Field>
  )
}
