import { useState, useEffect, useCallback } from 'react'
import { Button, Empty, Input, Modal, Popconfirm, Tag, Tooltip, message } from 'antd'
import { PlusOutlined, UploadOutlined, EditOutlined, DeleteOutlined, DownloadOutlined,
         CheckCircleOutlined, AppstoreOutlined, FolderOpenOutlined,
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
  source?: string
}

interface LibrarySkill {
  id: string
  name?: string
  description?: string
  tags?: string[]
  body?: string
  installed: boolean
}

type Selection = { kind: 'my' | 'library'; id: string } | null

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
// Read-only rendered skill body (TipTap, editable: false)
// ---------------------------------------------------------------------------

function SkillBody({ value }: { value: string }) {
  const editor = useEditor({
    editable: false,
    extensions: [StarterKit, Markdown],
    content: value,
  }, [value])

  if (!value?.trim()) {
    return <div style={{ color: '#999', fontStyle: 'italic' }}>No instructions provided.</div>
  }

  return (
    <div className="skill-body-render" style={{ fontSize: 14, lineHeight: 1.6, color: '#262626' }}>
      <EditorContent editor={editor} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Left-hand list row
// ---------------------------------------------------------------------------

function SkillRow({
  title, description, selected, badge, action, onClick,
}: {
  title: string
  description?: string
  selected: boolean
  badge?: React.ReactNode
  action?: React.ReactNode
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        padding: '10px 12px',
        borderRadius: 8,
        cursor: 'pointer',
        border: '1px solid',
        borderColor: selected ? '#1677ff' : '#f0f0f0',
        background: selected ? '#e6f4ff' : '#fff',
        transition: 'background 0.12s, border-color 0.12s',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 500, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {title}
          </span>
          {badge}
        </div>
        {description && (
          <div style={{
            fontSize: 12, color: '#8c8c8c', marginTop: 2,
            overflow: 'hidden', textOverflow: 'ellipsis',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
          }}>
            {description}
          </div>
        )}
      </div>
      {action && <div onClick={e => e.stopPropagation()} style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  )
}

function SectionHeader({ icon, label, count }: { icon: React.ReactNode; label: string; count: number }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '4px 4px', marginTop: 4,
      fontSize: 11, fontWeight: 600, letterSpacing: 0.4, textTransform: 'uppercase', color: '#8c8c8c',
    }}>
      {icon}
      <span>{label}</span>
      <span style={{ color: '#bfbfbf', fontWeight: 500 }}>{count}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [librarySkills, setLibrarySkills] = useState<LibrarySkill[]>([])

  const [selection, setSelection] = useState<Selection>(null)
  const [detail, setDetail] = useState<(Skill & LibrarySkill) | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Edit modal
  const [editing, setEditing] = useState<Skill | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  // Install in-flight
  const [installing, setInstalling] = useState<string | null>(null)

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

  const loadLibrarySkills = async () => {
    try {
      const res = await fetch(`${API}/skill-library`)
      if (res.ok) setLibrarySkills(await res.json())
    } catch {}
  }

  useEffect(() => { loadSkills(); loadLibrarySkills() }, [])

  useEffect(() => {
    fetch(`${API}/config`).then(r => r.ok ? r.json() : {}).then((cfg: Record<string, unknown>) => {
      setOpenclawEnabled(cfg?._active_agent === 'openclaw')
    }).catch(() => {})
  }, [])

  // Load the detail for the current selection
  const selectSkill = useCallback(async (sel: Selection) => {
    setSelection(sel)
    setDetail(null)
    if (!sel) return
    setDetailLoading(true)
    try {
      const url = sel.kind === 'my' ? `${API}/skills/${sel.id}` : `${API}/skill-library/${sel.id}`
      const res = await fetch(url)
      if (res.ok) setDetail(await res.json())
    } catch {} finally {
      setDetailLoading(false)
    }
  }, [])

  const openNew = () => {
    setEditing({ id: '', name: '', description: '', body: '' })
    setModalOpen(true)
  }

  const openEdit = async (id: string) => {
    try {
      const res = await fetch(`${API}/skills/${id}`)
      if (res.ok) {
        setEditing(await res.json())
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
        await loadSkills()
        selectSkill({ kind: 'my', id: skillId })
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
        if (selection?.kind === 'my' && selection.id === id) selectSkill(null)
        loadSkills()
        loadLibrarySkills()
        if (openclawEnabled) {
          setPendingSyncId(id)
          setSyncDeleteModalOpen(true)
        }
      }
    } catch {}
  }

  const installLibrarySkill = async (skillId: string) => {
    setInstalling(skillId)
    try {
      const res = await fetch(`${API}/skill-library/${skillId}/install`, { method: 'POST' })
      if (res.ok) {
        message.success('Skill installed')
        await Promise.all([loadSkills(), loadLibrarySkills()])
        // Refresh the detail so the Install button flips to Installed
        if (selection?.kind === 'library' && selection.id === skillId) selectSkill(selection)
        if (openclawEnabled) {
          setPendingSyncId(skillId)
          setSyncModalOpen(true)
        }
      } else {
        const err = await res.json().catch(() => ({ detail: 'Install failed' }))
        message.error(err.detail || 'Install failed')
      }
    } catch {
      message.error('Install failed')
    } finally {
      setInstalling(null)
    }
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

  const isEditingExisting = !!(editing?.id && skills.some(s => s.id === editing.id))

  // Library skills that are not yet installed (installed ones live under My Skills)
  const availableLibrary = librarySkills.filter(s => !s.installed)

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
      {/* ------------------------------------------------------------------ */}
      {/* Left column — skill list                                           */}
      {/* ------------------------------------------------------------------ */}
      <div style={{
        width: 340,
        flexShrink: 0,
        borderRight: '1px solid #f0f0f0',
        display: 'flex',
        flexDirection: 'column',
        background: '#fafafa',
      }}>
        <div style={{ padding: '18px 16px 12px', borderBottom: '1px solid #f0f0f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontWeight: 600, fontSize: 18 }}>Skills</h2>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openNew} style={{ flex: 1 }}>
              New Skill
            </Button>
            <Button size="small" icon={<UploadOutlined />} onClick={handleUpload} style={{ flex: 1 }}>
              Import .md
            </Button>
          </div>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Imported / created skills */}
          <SectionHeader icon={<FolderOpenOutlined />} label="My Skills" count={skills.length} />
          {skills.length === 0 ? (
            <div style={{ fontSize: 12, color: '#bfbfbf', padding: '6px 10px 12px' }}>
              Nothing yet — create one or install from the library.
            </div>
          ) : (
            skills.map(skill => (
              <SkillRow
                key={skill.id}
                title={skill.name || skill.id}
                description={skill.description}
                selected={selection?.kind === 'my' && selection.id === skill.id}
                badge={skill.source === 'library'
                  ? <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', margin: 0, padding: '0 6px' }}>Library</Tag>
                  : <Tag color="geekblue" style={{ fontSize: 10, lineHeight: '16px', margin: 0, padding: '0 6px' }}>Custom</Tag>}
                onClick={() => selectSkill({ kind: 'my', id: skill.id })}
              />
            ))
          )}

          {/* Skill library (not-yet-installed) */}
          <SectionHeader icon={<AppstoreOutlined />} label="Skill Library" count={availableLibrary.length} />
          {availableLibrary.length === 0 ? (
            <div style={{ fontSize: 12, color: '#bfbfbf', padding: '6px 10px 12px' }}>
              All library skills installed.
            </div>
          ) : (
            availableLibrary.map(skill => (
              <SkillRow
                key={skill.id}
                title={skill.name || skill.id}
                description={skill.description}
                selected={selection?.kind === 'library' && selection.id === skill.id}
                action={
                  <Tooltip title="Install skill">
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<DownloadOutlined />}
                      loading={installing === skill.id}
                      onClick={() => installLibrarySkill(skill.id)}
                    >
                      Install
                    </Button>
                  </Tooltip>
                }
                onClick={() => selectSkill({ kind: 'library', id: skill.id })}
              />
            ))
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Right column — skill write-up                                      */}
      {/* ------------------------------------------------------------------ */}
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
        {!selection ? (
          <div style={{ height: '100%', display: 'grid', placeItems: 'center' }}>
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Select a skill to view its write-up"
            />
          </div>
        ) : detailLoading ? (
          <div style={{ padding: 40, color: '#8c8c8c' }}>Loading…</div>
        ) : detail ? (
          <div style={{ maxWidth: 820, margin: '0 auto', padding: '28px 32px 60px' }}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 8 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>{detail.name || detail.id}</h1>
                  {selection.kind === 'my' && (
                    detail.source === 'library'
                      ? <Tag color="blue">From Library</Tag>
                      : <Tag color="geekblue">Custom</Tag>
                  )}
                  {selection.kind === 'library' && detail.installed && (
                    <Tag icon={<CheckCircleOutlined />} color="success">Installed</Tag>
                  )}
                </div>
                {detail.description && (
                  <p style={{ margin: '8px 0 0', color: '#595959', fontSize: 14 }}>{detail.description}</p>
                )}
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                {selection.kind === 'my' ? (
                  <>
                    <Button icon={<EditOutlined />} onClick={() => openEdit(detail.id)}>Edit</Button>
                    <Popconfirm title="Delete this skill?" onConfirm={() => deleteSkill(detail.id)}>
                      <Button icon={<DeleteOutlined />} danger />
                    </Popconfirm>
                  </>
                ) : !detail.installed ? (
                  <Button
                    type="primary"
                    icon={<DownloadOutlined />}
                    loading={installing === detail.id}
                    onClick={() => installLibrarySkill(detail.id)}
                  >
                    Install
                  </Button>
                ) : null}
              </div>
            </div>

            {/* Tags */}
            {detail.tags && detail.tags.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '14px 0' }}>
                {detail.tags.map(tag => <Tag key={tag}>{tag}</Tag>)}
              </div>
            )}

            <div style={{ height: 1, background: '#f0f0f0', margin: '18px 0 22px' }} />

            {/* Body */}
            <SkillBody value={detail.body || ''} />
          </div>
        ) : (
          <div style={{ padding: 40, color: '#8c8c8c' }}>Could not load this skill.</div>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Edit / New modal                                                   */}
      {/* ------------------------------------------------------------------ */}
      <Modal
        title={isEditingExisting ? 'Edit Skill' : 'New Skill'}
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
        <p>Copy this skill to <code>.openclaw/extensions/dataclaw/skills/</code> so OpenClaw can use it?</p>
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
        <p>Also remove this skill from <code>.openclaw/extensions/dataclaw/skills/</code>?</p>
      </Modal>
    </div>
  )
}

function slugify(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'skill'
}
