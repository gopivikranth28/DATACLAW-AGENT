import { useState, useEffect, useCallback } from 'react'
import { Button, Card, Empty, Input, Modal, Popconfirm, Select, Space, Switch, Tabs, Tag, message } from 'antd'
import {
  PlusOutlined, UploadOutlined, DeleteOutlined, ReloadOutlined,
  ApiOutlined, CodeOutlined, CheckCircleOutlined, CloseCircleOutlined,
  SearchOutlined, LinkOutlined,
} from '@ant-design/icons'
import { API } from '../api'
import { OpenClawToolDriftAlert } from '../components/OpenClawToolDriftAlert'

// ── Types ────────────────────────────────────────────────────────────────────

interface ToolDef {
  name: string
  description: string
  parameters?: Record<string, any>
  source?: string
  enabled?: boolean
}

interface CustomToolFile {
  file: string
  path: string
}

interface MCPServer {
  name: string
  transport: string
  enabled: boolean
  connected: boolean
  tool_count: number
  tools: string[]
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const sourceColor = (source?: string) => {
  if (!source) return 'default'
  if (source === 'custom') return 'blue'
  if (source.startsWith('mcp:')) return 'purple'
  return 'default'
}

const sourceLabel = (source?: string) => {
  if (!source || source === 'builtin') return 'builtin'
  if (source === 'custom') return 'custom'
  if (source.startsWith('mcp:')) return source
  return source
}

// ── All Tools Tab ────────────────────────────────────────────────────────────

function AllToolsTab() {
  const [tools, setTools] = useState<ToolDef[]>([])
  const [search, setSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [disabledSet, setDisabledSet] = useState<Set<string>>(new Set())

  const fetchTools = useCallback(() => {
    fetch(`${API}/tools`)
      .then(r => r.json())
      .then(data => {
        const list: ToolDef[] = data.tools ?? data ?? []
        setTools(list)
        setDisabledSet(new Set(list.filter(t => t.enabled === false).map(t => t.name)))
      })
      .catch(() => message.error('Failed to load tools'))
  }, [])

  useEffect(() => { fetchTools() }, [fetchTools])

  const toggleTool = async (name: string, enabled: boolean) => {
    setDisabledSet(prev => {
      const next = new Set(prev)
      if (enabled) next.delete(name)
      else next.add(name)
      return next
    })
    try {
      const cfg = await fetch(`${API}/tools/config`).then(r => r.json())
      const disabled: string[] = cfg.disabled ?? []
      const updated = enabled
        ? disabled.filter((n: string) => n !== name)
        : [...disabled, name]
      await fetch(`${API}/tools/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disabled: updated }),
      })
    } catch {
      message.error('Failed to update tool config')
      fetchTools()
    }
  }

  const sources = Array.from(new Set(tools.map(t => t.source || 'builtin')))

  const filtered = tools.filter(t => {
    if (search && !t.name.toLowerCase().includes(search.toLowerCase()) &&
        !t.description?.toLowerCase().includes(search.toLowerCase())) return false
    if (sourceFilter !== 'all' && (t.source || 'builtin') !== sourceFilter) return false
    return true
  })

  return (
    <div>
      {/* Search + filter */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder="Search tools..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1 }}
          allowClear
        />
        <Select
          value={sourceFilter}
          onChange={setSourceFilter}
          style={{ width: 160 }}
          options={[
            { value: 'all', label: 'All sources' },
            ...sources.map(s => ({ value: s, label: s })),
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchTools}>Refresh</Button>
      </div>

      {filtered.length === 0 ? (
        <Empty description="No tools found" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {filtered.map(tool => {
            const isEnabled = !disabledSet.has(tool.name)
            return (
              <Card key={tool.name} size="small" style={{ opacity: isEnabled ? 1 : 0.6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <Switch
                    size="small"
                    checked={isEnabled}
                    onChange={checked => toggleTool(tool.name, checked)}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 500 }}>
                        {tool.name}
                      </span>
                      <Tag color={sourceColor(tool.source)} style={{ fontSize: 11 }}>
                        {sourceLabel(tool.source)}
                      </Tag>
                    </div>
                    {tool.description && (
                      <div style={{ fontSize: 12, color: '#666', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {tool.description}
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Custom Tools Tab ─────────────────────────────────────────────────────────

function CustomToolsTab() {
  const [files, setFiles] = useState<CustomToolFile[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newCode, setNewCode] = useState(TEMPLATE_CODE)

  const fetchFiles = useCallback(() => {
    fetch(`${API}/tools/custom`)
      .then(r => r.json())
      .then(setFiles)
      .catch(() => message.error('Failed to load custom tools'))
  }, [])

  useEffect(() => { fetchFiles() }, [fetchFiles])

  const handleCreate = async () => {
    if (!newName.trim()) {
      message.warning('Please enter a filename')
      return
    }
    try {
      await fetch(`${API}/tools/custom`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: newName, code: newCode }),
      })
      message.success('Tool created')
      setCreateOpen(false)
      setNewName('')
      setNewCode(TEMPLATE_CODE)
      fetchFiles()
    } catch {
      message.error('Failed to create tool')
    }
  }

  const handleDelete = async (filename: string) => {
    try {
      await fetch(`${API}/tools/custom/${filename}`, { method: 'DELETE' })
      message.success('Tool deleted')
      fetchFiles()
    } catch {
      message.error('Failed to delete tool')
    }
  }

  const handleReload = async () => {
    try {
      const res = await fetch(`${API}/tools/custom/reload`, { method: 'POST' })
      const data = await res.json()
      message.success(`Reloaded ${data.reloaded} tool(s)`)
    } catch {
      message.error('Failed to reload tools')
    }
  }

  const handleUpload = () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.py'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      const code = await file.text()
      try {
        await fetch(`${API}/tools/custom`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: file.name, code }),
        })
        message.success('Tool uploaded')
        fetchFiles()
      } catch {
        message.error('Failed to upload tool')
      }
    }
    input.click()
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          New Tool
        </Button>
        <Button icon={<UploadOutlined />} onClick={handleUpload}>
          Upload .py
        </Button>
        <Button icon={<ReloadOutlined />} onClick={handleReload}>
          Reload All
        </Button>
      </div>

      {files.length === 0 ? (
        <Empty description={<>No custom tools yet. Create one or add .py files to <code>~/.dataclaw/tools/</code></>} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {files.map(f => (
            <Card key={f.file} size="small">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <CodeOutlined style={{ color: '#1677ff' }} />
                  <span style={{ fontFamily: 'monospace', fontSize: 13 }}>{f.file}</span>
                </div>
                <Popconfirm title="Delete this tool file?" onConfirm={() => handleDelete(f.file)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        title="Create Custom Tool"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        okText="Create"
        width={640}
      >
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Filename</div>
          <Input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            placeholder="my_tool.py"
            addonAfter=".py"
          />
        </div>
        <div>
          <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Code</div>
          <Input.TextArea
            value={newCode}
            onChange={e => setNewCode(e.target.value)}
            rows={14}
            style={{ fontFamily: 'Menlo, Monaco, "Courier New", monospace', fontSize: 12 }}
          />
        </div>
      </Modal>
    </div>
  )
}

const TEMPLATE_CODE = `from dataclaw.tools import tool


@tool(name="my_tool", description="Describe what this tool does")
async def my_tool(arg: str) -> dict:
    """Tool implementation."""
    return {"content": f"Result: {arg}"}
`

// ── MCP Servers Tab ──────────────────────────────────────────────────────────

function MCPServersTab() {
  const [servers, setServers] = useState<MCPServer[]>([])
  const [addOpen, setAddOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newTransport, setNewTransport] = useState('stdio')
  const [newCommand, setNewCommand] = useState('')
  const [newArgs, setNewArgs] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [newEnv, setNewEnv] = useState('')

  const fetchServers = useCallback(() => {
    fetch(`${API}/tools/mcp/servers`)
      .then(r => r.json())
      .then(setServers)
      .catch(() => {})
  }, [])

  useEffect(() => { fetchServers() }, [fetchServers])

  const handleAdd = async () => {
    if (!newName.trim()) {
      message.warning('Please enter a server name')
      return
    }

    // Parse env as KEY=VALUE lines
    const env: Record<string, string> = {}
    if (newEnv.trim()) {
      for (const line of newEnv.split('\n')) {
        const eq = line.indexOf('=')
        if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
      }
    }

    const body: Record<string, any> = {
      name: newName,
      transport: newTransport,
      enabled: true,
    }
    if (newTransport === 'stdio') {
      body.command = newCommand
      body.args = newArgs.trim() ? newArgs.split(/\s+/) : []
      if (Object.keys(env).length) body.env = env
    } else {
      body.url = newUrl
    }

    try {
      const res = await fetch(`${API}/tools/mcp/servers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        message.error(err.detail || 'Failed to add server')
        return
      }
      const data = await res.json()
      message.success(`Connected to ${newName} (${data.tool_count} tools)`)
      setAddOpen(false)
      setNewName('')
      setNewCommand('')
      setNewArgs('')
      setNewUrl('')
      setNewEnv('')
      fetchServers()
    } catch {
      message.error('Failed to add server')
    }
  }

  const handleRemove = async (name: string) => {
    try {
      await fetch(`${API}/tools/mcp/servers/${name}`, { method: 'DELETE' })
      message.success('Server removed')
      fetchServers()
    } catch {
      message.error('Failed to remove server')
    }
  }

  const handleReconnect = async (name: string) => {
    try {
      const res = await fetch(`${API}/tools/mcp/servers/${name}/reconnect`, { method: 'POST' })
      if (!res.ok) {
        message.error('Failed to reconnect')
        return
      }
      const data = await res.json()
      message.success(`Reconnected (${data.tool_count} tools)`)
      fetchServers()
    } catch {
      message.error('Failed to reconnect')
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
          Add Server
        </Button>
      </div>

      {servers.length === 0 ? (
        <Empty description="No MCP servers configured" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {servers.map(srv => (
            <Card key={srv.name} size="small">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <ApiOutlined style={{ color: srv.connected ? '#52c41a' : '#999' }} />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{srv.name}</span>
                  <Tag>{srv.transport}</Tag>
                  {srv.connected ? (
                    <Tag icon={<CheckCircleOutlined />} color="success">
                      connected ({srv.tool_count} tools)
                    </Tag>
                  ) : (
                    <Tag icon={<CloseCircleOutlined />} color="default">disconnected</Tag>
                  )}
                </div>
                <Space size="small">
                  <Button size="small" icon={<LinkOutlined />} onClick={() => handleReconnect(srv.name)}>
                    Reconnect
                  </Button>
                  <Popconfirm title="Remove this server?" onConfirm={() => handleRemove(srv.name)}>
                    <Button size="small" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                </Space>
              </div>
              {srv.connected && srv.tools.length > 0 && (
                <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
                  <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>Tools:</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {srv.tools.map(t => (
                      <Tag key={t} style={{ fontSize: 11, fontFamily: 'monospace' }}>{t}</Tag>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <Modal
        title="Add MCP Server"
        open={addOpen}
        onCancel={() => setAddOpen(false)}
        onOk={handleAdd}
        okText="Connect"
        width={520}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Name</div>
            <Input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="github"
            />
          </div>
          <div>
            <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Transport</div>
            <Select
              value={newTransport}
              onChange={setNewTransport}
              style={{ width: '100%' }}
              options={[
                { value: 'stdio', label: 'stdio (subprocess)' },
                { value: 'sse', label: 'SSE (HTTP)' },
              ]}
            />
          </div>
          {newTransport === 'stdio' ? (
            <>
              <div>
                <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Command</div>
                <Input
                  value={newCommand}
                  onChange={e => setNewCommand(e.target.value)}
                  placeholder="npx"
                />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Arguments (space-separated)</div>
                <Input
                  value={newArgs}
                  onChange={e => setNewArgs(e.target.value)}
                  placeholder="-y @modelcontextprotocol/server-github"
                />
              </div>
              <div>
                <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>
                  Environment Variables (KEY=VALUE, one per line)
                </div>
                <Input.TextArea
                  value={newEnv}
                  onChange={e => setNewEnv(e.target.value)}
                  rows={3}
                  placeholder={'GITHUB_TOKEN=ghp_...\nGITHUB_OWNER=myorg'}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
              </div>
            </>
          ) : (
            <div>
              <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>SSE URL</div>
              <Input
                value={newUrl}
                onChange={e => setNewUrl(e.target.value)}
                placeholder="http://localhost:3001/sse"
              />
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ToolsPage() {
  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <h2 style={{ marginTop: 0, fontWeight: 600 }}>Tools</h2>
      <OpenClawToolDriftAlert style={{ marginBottom: 16 }} />
      <Tabs
        defaultActiveKey="all"
        items={[
          { key: 'all', label: 'All Tools', children: <AllToolsTab /> },
          { key: 'custom', label: 'Custom Tools', children: <CustomToolsTab /> },
          { key: 'mcp', label: 'MCP Servers', children: <MCPServersTab /> },
        ]}
      />
    </div>
  )
}
