import { useState, useEffect } from 'react'
import { Button, Card, Empty, Input, InputNumber, Modal, Select, Switch, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { API } from '../api'

interface Subagent {
  id: string
  name: string
  description: string
  agent_type: string
  allowed_tools?: string[]
}

interface AgentType {
  agent_type: string
  provider: string
  config_schema: any[]
}

export default function SubagentsPage() {
  const [subagents, setSubagents] = useState<Subagent[]>([])
  const [tools, setTools] = useState<{ name: string; description: string }[]>([])
  const [agentTypes, setAgentTypes] = useState<AgentType[]>([])
  const [editing, setEditing] = useState<any>(null)
  const [modalOpen, setModalOpen] = useState(false)

  const load = async () => {
    try {
      const res = await fetch(`${API}/subagents/`)
      if (res.ok) setSubagents(await res.json())
    } catch {}
  }

  const loadTools = async () => {
    try {
      const res = await fetch(`${API}/tools`)
      if (res.ok) setTools(await res.json())
    } catch {}
  }

  const loadAgentTypes = async () => {
    try {
      const res = await fetch(`${API}/providers`)
      if (res.ok) {
        const providers = await res.json()
        const subAgentEntry = providers.find((p: any) => p.slot === 'sub_agent')
        if (subAgentEntry?.agent_types) {
          setAgentTypes(subAgentEntry.agent_types)
        }
      }
    } catch {}
  }

  useEffect(() => { load(); loadTools(); loadAgentTypes() }, [])

  const openNew = () => {
    setEditing({ name: '', description: '', agent_type: 'llm', allowed_tools: [], config: {} })
    setModalOpen(true)
  }

  const openEdit = async (sa: Subagent) => {
    try {
      const res = await fetch(`${API}/subagents/${sa.id}`)
      if (res.ok) {
        setEditing(await res.json())
        setModalOpen(true)
      }
    } catch {}
  }

  const save = async () => {
    if (!editing) return
    const isNew = !editing.id || !subagents.some(s => s.id === editing.id)
    const method = isNew ? 'POST' : 'PUT'
    const url = isNew ? `${API}/subagents/` : `${API}/subagents/${editing.id}`

    try {
      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editing.name,
          description: editing.description,
          agent_type: editing.agent_type,
          allowed_tools: editing.allowed_tools || [],
          config: editing.config || {},
        }),
      })
      if (res.ok) {
        message.success(isNew ? 'Subagent created' : 'Subagent updated')
        setModalOpen(false)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        message.error(err.detail || 'Failed to save')
      }
    } catch {
      message.error('Failed to save')
    }
  }

  const remove = async (id: string) => {
    await fetch(`${API}/subagents/${id}`, { method: 'DELETE' })
    message.success('Subagent deleted')
    load()
  }

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontWeight: 600 }}>Subagents</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>New Subagent</Button>
      </div>

      {subagents.length === 0 ? (
        <Empty description="No subagents defined" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {subagents.map(sa => (
            <Card key={sa.id} size="small" style={{ borderRadius: 8 }}
              extra={
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(sa)} />
                  <Popconfirm title="Delete this subagent?" onConfirm={() => remove(sa.id)}>
                    <Button size="small" icon={<DeleteOutlined />} danger />
                  </Popconfirm>
                </div>
              }
            >
              <div style={{ fontWeight: 500 }}>{sa.name}</div>
              {sa.description && <div style={{ fontSize: 13, color: '#666', marginTop: 2 }}>{sa.description}</div>}
              <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>Type: {sa.agent_type}</div>
            </Card>
          ))}
        </div>
      )}

      {/* Edit Modal */}
      <Modal title={editing?.id ? 'Edit Subagent' : 'New Subagent'} open={modalOpen}
        onCancel={() => setModalOpen(false)} onOk={save} okText="Save" width={600}>
        {editing && (
          <EditForm
            editing={editing}
            setEditing={setEditing}
            agentTypes={agentTypes}
            tools={tools}
          />
        )}
      </Modal>
    </div>
  )
}

/** Dynamic edit form that renders config fields based on the selected agent_type */
function EditForm({ editing, setEditing, agentTypes, tools }: {
  editing: any
  setEditing: (v: any) => void
  agentTypes: AgentType[]
  tools: { name: string; description: string }[]
}) {
  const selectedType = agentTypes.find(t => t.agent_type === editing.agent_type)
  const configFields = selectedType?.config_schema || []
  const isLLMType = editing.agent_type === 'llm'

  const updateConfig = (key: string, value: any) => {
    setEditing({ ...editing, config: { ...editing.config, [key]: value } })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
      <Field label="Name">
        <Input value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} placeholder="Research Bot" />
      </Field>
      <Field label="Description">
        <Input value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} />
      </Field>
      <Field label="Agent Type">
        <Select value={editing.agent_type}
          onChange={v => setEditing({ ...editing, agent_type: v, config: {} })}
          style={{ width: '100%' }}
          options={agentTypes.length > 0
            ? agentTypes.map(t => ({ value: t.agent_type, label: `${t.agent_type} (${t.provider})` }))
            : [{ value: 'llm', label: 'LLM Agent' }]
          } />
      </Field>

      {/* Allowed Tools — only for LLM type which uses dataclaw tools */}
      {isLLMType && (
        <Field label="Allowed Tools">
          <Select mode="multiple" value={editing.allowed_tools || []}
            onChange={v => setEditing({ ...editing, allowed_tools: v })}
            style={{ width: '100%' }} placeholder="Select tools (empty = all)"
            options={tools.map(t => ({ value: t.name, label: t.name }))} />
        </Field>
      )}

      {/* Dynamic config fields from the provider's config_schema */}
      {configFields.map((field: any) => (
        <Field key={field.name} label={field.label || field.name}>
          <ConfigFieldInput
            field={field}
            value={editing.config?.[field.name] ?? field.default ?? ''}
            onChange={v => updateConfig(field.name, v)}
          />
          {field.description && (
            <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{field.description}</div>
          )}
        </Field>
      ))}
    </div>
  )
}

/** Renders the appropriate input for a config field based on field_type */
function ConfigFieldInput({ field, value, onChange }: { field: any; value: any; onChange: (v: any) => void }) {
  switch (field.field_type) {
    case 'string':
      return <Input value={value || ''} onChange={e => onChange(e.target.value)} />
    case 'text':
      return (
        <Input.TextArea value={value || ''} onChange={e => onChange(e.target.value)}
          rows={4} style={{ fontFamily: 'monospace', fontSize: 13 }} />
      )
    case 'int':
      return <InputNumber value={value} onChange={v => onChange(v)} style={{ width: '100%' }} />
    case 'bool':
      return <Switch checked={!!value} onChange={v => onChange(v)} />
    case 'select':
      return (
        <Select value={value} onChange={v => onChange(v)} style={{ width: '100%' }}
          options={(field.options || []).map((o: any) => ({ value: o.value, label: o.label }))} />
      )
    default:
      return <Input value={value || ''} onChange={e => onChange(e.target.value)} />
  }
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  )
}
