import { useState, useEffect, useRef } from 'react'
import { Card, Select, Input, InputNumber, Switch, Button, Modal, Tag, Space, Divider, message } from 'antd'
import { SaveOutlined, CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined, LoadingOutlined, DownloadOutlined, CodeOutlined } from '@ant-design/icons'
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

interface Props {
  plugins: PluginInfo[]
}

export default function ConfigPage({ plugins }: Props) {
  const [config, setConfig] = useState<any>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch(`${API}/config`)
      .then(r => r.json())
      .then(setConfig)
      .catch(() => message.error('Failed to load config'))
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      const res = await fetch(`${API}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      })
      if (res.ok) message.success('Configuration saved')
      else message.error('Failed to save')
    } catch {
      message.error('Failed to save')
    }
    setSaving(false)
  }

  const llm = config.llm || {}
  const backend = llm.backend || 'openclaw'
  const backendConfig = llm[backend] || {}
  const compaction = config.compaction || {}
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
  const updateCompaction = (field: string, value: any) => {
    setConfig((prev: any) => ({ ...prev, compaction: { ...prev.compaction, [field]: value } }))
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

  // OpenClaw CLI + plugin management state
  const [openclawStatus, setOpenclawStatus] = useState<{ installed: boolean; version?: string | null } | null>(null)
  const [checkingOpenclaw, setCheckingOpenclaw] = useState(false)
  const [pluginStatus, setPluginStatus] = useState<Record<string, { installed: boolean; status?: string; version?: string } | null>>({})
  const [checking, setChecking] = useState<Record<string, boolean>>({})
  const [installModalTarget, setInstallModalTarget] = useState<string | null>(null) // 'openclaw' | plugin id | null
  const [installing, setInstalling] = useState(false)
  const [buildOutput, setBuildOutput] = useState('')
  const outputRef = useRef<HTMLPreElement>(null)
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [terminalCommand, setTerminalCommand] = useState<string | undefined>(undefined)

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
  }

  const fetchOpenClawToken = async () => {
    try {
      const res = await fetch(`${API}/openclaw/fetch-token`)
      if (res.ok) {
        const data = await res.json()
        updatePluginConfig('openclaw', 'frontend_token', data.token)
        updatePluginConfig('openclaw', 'tools_token', data.token)
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

  const openclawPlugins = ['dataclaw-tools', 'dataclaw-frontend']

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
              { value: 'openclaw', label: 'OpenClaw (External Agent)' },
            ]}
          />
        </Field>

        {/* LLM provider fields */}
        {agentBackend !== 'mock' && agentBackend !== 'openclaw' && (
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
            <Field label="Frontend Token">
              <Space.Compact style={{ width: '100%' }}>
                <Input.Password
                  value={openclawConfig.frontend_token || ''}
                  onChange={e => updatePluginConfig('openclaw', 'frontend_token', e.target.value)}
                  placeholder="dataclaw-local"
                />
                <Button onClick={fetchOpenClawToken} title="Fetch from .openclaw/openclaw.json">
                  Fetch
                </Button>
              </Space.Compact>
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Sent TO OpenClaw — must match DATACLAW_FRONTEND_TOKEN on the OpenClaw side
              </div>
            </Field>
            <Field label="Tools Token">
              <Input.Password
                value={openclawConfig.tools_token || ''}
                onChange={e => updatePluginConfig('openclaw', 'tools_token', e.target.value)}
                placeholder="dataclaw-local"
              />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                Expected FROM OpenClaw — must match DATACLAW_TOOLS_TOKEN on the OpenClaw side
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
            <Field label="Plugin Source Directory">
              <Input
                value={openclawConfig.plugins_source_dir || ''}
                onChange={e => updatePluginConfig('openclaw', 'plugins_source_dir', e.target.value)}
                placeholder="(auto-detected)"
              />
            </Field>

            <Divider style={{ margin: '12px 0 8px' }} dashed>Plugins</Divider>

            {openclawPlugins.map(pid => {
              const status = pluginStatus[pid]
              const isChecking = checking[pid]
              return (
                <div key={pid} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
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
                  </div>
                  <Space size="small">
                    <Button size="small" onClick={() => checkPluginStatus(pid)} loading={isChecking}>
                      Status
                    </Button>
                    <Button size="small" type="primary" icon={<DownloadOutlined />} onClick={() => { setInstallModalTarget(pid); setBuildOutput('') }}>
                      Install
                    </Button>
                  </Space>
                </div>
              )
            })}
          </>
        )}
      </Card>

      {/* OpenClaw Install Modal */}
      <Modal
        title={`Install ${installModalTarget === 'openclaw' ? 'OpenClaw' : installModalTarget || ''}`}
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

      {/* Compaction */}
      <Card size="small" title="Message Compaction" style={{ marginBottom: 16 }}>
        <Field label="Enabled">
          <Switch checked={compaction.enabled || false} onChange={v => updateCompaction('enabled', v)} />
        </Field>
        {compaction.enabled && (
          <>
            <Field label="Max Messages">
              <InputNumber value={compaction.max_messages ?? 30} onChange={v => updateCompaction('max_messages', v)} min={5} max={200} style={{ width: '100%' }} />
            </Field>
            <Field label="Keep Recent">
              <InputNumber value={compaction.keep_recent ?? 8} onChange={v => updateCompaction('keep_recent', v)} min={1} max={50} style={{ width: '100%' }} />
            </Field>
          </>
        )}
      </Card>

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
        onCancel={() => { setTerminalOpen(false); checkOpenclawInstalled() }}
        footer={<Button onClick={() => { setTerminalOpen(false); checkOpenclawInstalled() }}>Close</Button>}
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
