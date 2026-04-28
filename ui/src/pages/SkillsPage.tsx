import { useState, useEffect, useCallback } from 'react'
import { Button, Card, Empty, Input, Modal, Popconfirm, message } from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined,
         BoldOutlined, ItalicOutlined, OrderedListOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { Markdown } from 'tiptap-markdown'
import { API } from '../api'

interface Skill {
  id: string
  name?: string
  description?: string
  tags?: string[]
  body?: string
}

// ---------------------------------------------------------------------------
// Toolbar
// ---------------------------------------------------------------------------

function EditorToolbar({ editor }: { editor: ReturnType<typeof useEditor> }) {
  if (!editor) return null

  const btn = (active: boolean, onClick: () => void, icon: React.ReactNode) => (
    <button
      type="button"
      onMouseDown={e => { e.preventDefault(); onClick() }}
      style={{
        padding: '3px 8px',
        border: '1px solid #d9d9d9',
        borderRadius: 4,
        background: active ? '#e6f4ff' : '#fff',
        borderColor: active ? '#1677ff' : '#d9d9d9',
        cursor: 'pointer',
        fontSize: 14,
        color: active ? '#1677ff' : '#555',
        lineHeight: 1,
      }}
    >
      {icon}
    </button>
  )

  return (
    <div style={{ display: 'flex', gap: 4, padding: '6px 8px', borderBottom: '1px solid #d9d9d9', flexWrap: 'wrap' }}>
      {btn(editor.isActive('bold'),          () => editor.chain().focus().toggleBold().run(),          <BoldOutlined />)}
      {btn(editor.isActive('italic'),        () => editor.chain().focus().toggleItalic().run(),        <ItalicOutlined />)}
      {btn(editor.isActive('code'),          () => editor.chain().focus().toggleCode().run(),          <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{'<>'}</span>)}
      <div style={{ width: 1, background: '#e0e0e0', margin: '0 2px' }} />
      {btn(editor.isActive('heading', { level: 1 }), () => editor.chain().focus().toggleHeading({ level: 1 }).run(), <span style={{ fontWeight: 700, fontSize: 12 }}>H1</span>)}
      {btn(editor.isActive('heading', { level: 2 }), () => editor.chain().focus().toggleHeading({ level: 2 }).run(), <span style={{ fontWeight: 700, fontSize: 12 }}>H2</span>)}
      {btn(editor.isActive('heading', { level: 3 }), () => editor.chain().focus().toggleHeading({ level: 3 }).run(), <span style={{ fontWeight: 700, fontSize: 12 }}>H3</span>)}
      <div style={{ width: 1, background: '#e0e0e0', margin: '0 2px' }} />
      {btn(editor.isActive('bulletList'),    () => editor.chain().focus().toggleBulletList().run(),    <UnorderedListOutlined />)}
      {btn(editor.isActive('orderedList'),   () => editor.chain().focus().toggleOrderedList().run(),   <OrderedListOutlined />)}
      {btn(editor.isActive('blockquote'),    () => editor.chain().focus().toggleBlockquote().run(),    <span style={{ fontWeight: 700, fontSize: 13 }}>"</span>)}
      {btn(editor.isActive('codeBlock'),     () => editor.chain().focus().toggleCodeBlock().run(),     <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{'{ }'}</span>)}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skill body editor (TipTap)
// ---------------------------------------------------------------------------

function SkillEditor({ value, onChange }: { value: string; onChange: (md: string) => void }) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Markdown,
    ],
    content: value,
    onUpdate({ editor }) {
      onChange((editor.storage as any).markdown.getMarkdown())
    },
  })

  // Sync content when the modal opens with a different skill
  const prevValue = useCallback(() => value, [value])
  useEffect(() => {
    if (!editor) return
    const current = (editor.storage as any).markdown.getMarkdown()
    if (current !== value) {
      editor.commands.setContent(value)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, prevValue])

  return (
    <div style={{ border: '1px solid #d9d9d9', borderRadius: 6, overflow: 'hidden', minHeight: 300 }}>
      <EditorToolbar editor={editor} />
      <EditorContent
        editor={editor}
        style={{ padding: '10px 14px', minHeight: 260, outline: 'none', cursor: 'text' }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [editing, setEditing] = useState<Skill | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  // OpenClaw sync
  const [openclawEnabled, setOpenclawEnabled] = useState(false)
  const [syncModalOpen, setSyncModalOpen] = useState(false)
  const [syncDeleteModalOpen, setSyncDeleteModalOpen] = useState(false)
  const [pendingSyncId, setPendingSyncId] = useState<string | null>(null)

  const loadSkills = async () => {
    try {
      const res = await fetch(`${API}/skills`)
      if (res.ok) setSkills(await res.json())
    } catch {}
  }

  useEffect(() => { loadSkills() }, [])

  useEffect(() => {
    fetch(`${API}/config`).then(r => r.ok ? r.json() : {}).then((cfg: Record<string, unknown>) => {
      setOpenclawEnabled(cfg?._active_agent === 'openclaw')
    }).catch(() => {})
  }, [])

  const openNew = () => {
    setEditing({ id: '', name: '', description: '', body: '' })
    setModalOpen(true)
  }

  const openEdit = async (skill: Skill) => {
    try {
      const res = await fetch(`${API}/skills/${skill.id}`)
      if (res.ok) {
        const full = await res.json()
        setEditing(full)
        setModalOpen(true)
      }
    } catch {}
  }

  function handleUpload() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.md'
    input.onchange = async () => {
      const file = input.files?.[0]
      if (!file) return
      const text = await file.text()

      // Parse optional YAML frontmatter
      let name = file.name.replace(/\.md$/i, '')
      let description = ''
      let body = text

      if (text.startsWith('---')) {
        const parts = text.split('---', 3)
        if (parts.length === 3) {
          const frontmatter = parts[1]
          body = parts[2].replace(/^\n+/, '')
          for (const line of frontmatter.split('\n')) {
            const [key, ...rest] = line.split(':')
            const val = rest.join(':').trim()
            if (key.trim() === 'name' && val) name = val
            if (key.trim() === 'description' && val) description = val
          }
        }
      }

      setEditing({ id: '', name, description, body })
      setModalOpen(true)
    }
    input.click()
  }

  const save = async () => {
    if (!editing) return
    const isNew = !editing.id || !skills.some(s => s.id === editing.id)
    const skillId = editing.id || slugify(editing.name || 'skill')

    const method = isNew ? 'POST' : 'PUT'
    try {
      const res = await fetch(`${API}/skills/${skillId}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: editing.name || skillId,
          description: editing.description || '',
          tags: editing.tags || [],
          body: editing.body || '',
        }),
      })
      if (res.ok) {
        message.success(isNew ? 'Skill created' : 'Skill updated')
        setModalOpen(false)
        loadSkills()
        if (openclawEnabled) {
          setPendingSyncId(skillId)
          setSyncModalOpen(true)
        }
      } else {
        message.error('Failed to save skill')
      }
    } catch {
      message.error('Failed to save skill')
    }
  }

  const deleteSkill = async (id: string) => {
    try {
      const res = await fetch(`${API}/skills/${id}`, { method: 'DELETE' })
      if (res.ok) {
        message.success('Skill deleted')
        loadSkills()
        if (openclawEnabled) {
          setPendingSyncId(id)
          setSyncDeleteModalOpen(true)
        }
      }
    } catch {}
  }

  const syncToOpenclaw = async () => {
    if (!pendingSyncId) return
    try {
      const res = await fetch(`${API}/openclaw/skills/${pendingSyncId}/sync`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        message.success(`Synced to OpenClaw: ${data.synced_to}`)
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        message.error(err.detail || 'Sync failed')
      }
    } catch {
      message.error('Sync request failed')
    } finally {
      setSyncModalOpen(false)
      setPendingSyncId(null)
    }
  }

  const removeFromOpenclaw = async () => {
    if (!pendingSyncId) return
    try {
      const res = await fetch(`${API}/openclaw/skills/${pendingSyncId}/sync`, { method: 'DELETE' })
      if (res.ok) {
        message.success('Removed from OpenClaw')
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        message.error(err.detail || 'Remove failed')
      }
    } catch {
      message.error('Remove request failed')
    } finally {
      setSyncDeleteModalOpen(false)
      setPendingSyncId(null)
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontWeight: 600 }}>Skills</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<UploadOutlined />} onClick={handleUpload}>Import .md</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNew}>New Skill</Button>
        </div>
      </div>

      {skills.length === 0 ? (
        <Empty description="No skills yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {skills.map(skill => (
            <Card
              key={skill.id}
              size="small"
              style={{ borderRadius: 8 }}
              extra={
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(skill)} />
                  <Popconfirm title="Delete this skill?" onConfirm={() => deleteSkill(skill.id)}>
                    <Button size="small" icon={<DeleteOutlined />} danger />
                  </Popconfirm>
                </div>
              }
            >
              <div style={{ fontWeight: 500 }}>{skill.name || skill.id}</div>
              {skill.description && (
                <div style={{ fontSize: 13, color: '#666', marginTop: 2 }}>{skill.description}</div>
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Edit Modal */}
      <Modal
        title={editing?.id && skills.some(s => s.id === editing.id) ? 'Edit Skill' : 'New Skill'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={save}
        okText="Save"
        okButtonProps={{ disabled: !editing?.name?.trim() }}
        width={800}
        destroyOnClose
      >
        {editing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
            <div>
              <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Name</div>
              <Input
                value={editing.name || ''}
                onChange={e => setEditing({ ...editing, name: e.target.value })}
                placeholder="e.g. data_profiling"
                autoFocus
              />
            </div>
            <div>
              <div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>Description</div>
              <Input
                value={editing.description || ''}
                onChange={e => setEditing({ ...editing, description: e.target.value })}
                placeholder="What does this skill do?"
              />
            </div>
            <div>
              <div style={{ fontSize: 13, color: '#666', fontWeight: 500, marginBottom: 8 }}>
                Instructions
              </div>
              {modalOpen && (
                <SkillEditor
                  value={editing.body || ''}
                  onChange={body => setEditing({ ...editing, body })}
                />
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* OpenClaw sync prompt */}
      <Modal
        title="Sync to OpenClaw?"
        open={syncModalOpen}
        onOk={syncToOpenclaw}
        onCancel={() => { setSyncModalOpen(false); setPendingSyncId(null) }}
        okText="Sync"
      >
        <p>Copy this skill to <code>.openclaw/extensions/dataclaw-tools/skills/</code> so OpenClaw can use it?</p>
      </Modal>

      {/* OpenClaw delete sync prompt */}
      <Modal
        title="Remove from OpenClaw?"
        open={syncDeleteModalOpen}
        onOk={removeFromOpenclaw}
        onCancel={() => { setSyncDeleteModalOpen(false); setPendingSyncId(null) }}
        okText="Remove"
        okButtonProps={{ danger: true }}
      >
        <p>Also remove this skill from <code>.openclaw/extensions/dataclaw-tools/skills/</code>?</p>
      </Modal>
    </div>
  )
}

function slugify(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'skill'
}
