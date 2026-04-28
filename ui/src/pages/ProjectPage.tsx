import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { Tabs, Button, Card, Empty, Input, Popconfirm, Spin, Switch, Table, Tag } from 'antd'
import { PlusOutlined, DeleteOutlined, MessageOutlined, ArrowLeftOutlined, ExperimentOutlined, FolderOutlined, ReloadOutlined } from '@ant-design/icons'
import { API } from '../api'
import { FileViewerModal } from '../components/FilePreview'
import FileIcon from '../components/FileIcon'
import ChatPage from './ChatPage'

interface Project { id: string; name: string; description: string; directory: string; created_at: string; dataset_ids?: string[] | null }
interface Session { id: string; title: string; createdAt: string; updatedAt?: string }
interface FileNode { name: string; path: string; is_dir: boolean; size: number; children?: FileNode[] }

export default function ProjectPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)

  const activeTab = searchParams.get('tab') || 'sessions'
  const selectedSessionId = searchParams.get('session') || null

  const setActiveTab = (tab: string) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('tab', tab)
      return next
    }, { replace: true })
  }

  const setSelectedSessionId = (id: string | null) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (id) { next.set('session', id); next.set('tab', 'chat') }
      else next.delete('session')
      return next
    }, { replace: true })
  }

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    fetch(`${API}/projects/${projectId}`)
      .then(r => r.ok ? r.json() : null)
      .then(setProject)
      .catch(() => setProject(null))
      .finally(() => setLoading(false))
  }, [projectId])

  if (loading) return <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
  if (!project) return <div style={{ padding: 48, textAlign: 'center' }}>Project not found</div>

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/projects')} />
        <div>
          <div style={{ fontWeight: 600, fontSize: 16 }}>{project.name}</div>
          {project.description && <div style={{ fontSize: 12, color: '#888' }}>{project.description}</div>}
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 11, color: '#bbb', fontFamily: 'monospace' }}>{project.directory}</div>
      </div>

      {/* Tabs */}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        style={{ flex: 1, overflow: 'hidden' }}
        tabBarStyle={{ padding: '0 24px', marginBottom: 0 }}
        items={[
          { key: 'sessions', label: 'Sessions', children: <SessionsTab projectId={project.id} visible={activeTab === 'sessions'} onOpenChat={(sessionId) => setSelectedSessionId(sessionId)} /> },
          { key: 'chat', label: 'Chat', children: <div style={{ height: 'calc(100vh - 140px)' }}><ChatPage projectId={project.id} initialSessionId={selectedSessionId} initialDatasetIds={project.dataset_ids} onSessionChange={setSelectedSessionId} /></div> },
          { key: 'data', label: 'Data Sources', children: <DataSourcesTab projectId={project.id} initialDatasetIds={project.dataset_ids} onDatasetIdsChange={(ids) => setProject(prev => prev ? { ...prev, dataset_ids: ids } : prev)} /> },
          { key: 'files', label: 'Files', children: <FilesTab projectId={project.id} /> },
          { key: 'experiments', label: 'Experiments', children: <ExperimentsTab projectId={project.id} /> },
        ]}
      />
    </div>
  )
}

// ── Sessions Tab ───────────────────────────────────────────────────────────

function SessionsTab({ projectId, onOpenChat, visible }: { projectId: string; onOpenChat?: (sessionId: string) => void; visible?: boolean }) {
  const [sessions, setSessions] = useState<Session[]>([])

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/chat/sessions?project_id=${projectId}`)
      if (res.ok) setSessions(await res.json())
    } catch {}
  }, [projectId])

  useEffect(() => { load() }, [load])

  // Reload sessions when tab becomes visible again (e.g. after deleting from chat)
  useEffect(() => { if (visible) load() }, [visible, load])

  const create = async () => {
    try {
      const res = await fetch(`${API}/chat/sessions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, title: 'New Chat' }),
      })
      if (res.ok) {
        const s = await res.json()
        onOpenChat?.(s.id)
      }
    } catch {}
  }

  const remove = async (id: string) => {
    await fetch(`${API}/chat/sessions/${id}`, { method: 'DELETE' })
    load()
  }

  return (
    <div style={{ padding: 24, maxWidth: 700 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <span style={{ fontWeight: 500 }}>{sessions.length} session(s)</span>
        <Button icon={<PlusOutlined />} onClick={create}>New Session</Button>
      </div>
      {sessions.length === 0 ? (
        <Empty description="No sessions yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sessions.map(s => (
            <Card key={s.id} size="small" style={{ borderRadius: 6, cursor: 'pointer' }} hoverable
              onClick={() => onOpenChat?.(s.id)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 500 }}><MessageOutlined style={{ marginRight: 6, color: '#999' }} />{s.title || s.id.slice(0, 12)}</div>
                  <div style={{ fontSize: 11, color: '#999' }}>{new Date(s.createdAt).toLocaleString()}</div>
                </div>
                <div onClick={e => e.stopPropagation()}>
                  <Popconfirm title="Delete?" onConfirm={() => remove(s.id)}>
                    <Button size="small" icon={<DeleteOutlined />} danger />
                  </Popconfirm>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Files Tab ──────────────────────────────────────────────────────────────

function FilesTab({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<FileNode[]>([])
  const [loading, setLoading] = useState(true)
  const [previewTarget, setPreviewTarget] = useState<{ name: string; path: string } | null>(null)

  const loadFiles = useCallback(() => {
    setLoading(true)
    fetch(`${API}/projects/${projectId}/files`)
      .then(r => r.ok ? r.json() : { project: [] })
      .then(d => setFiles(d.project || []))
      .catch(() => setFiles([]))
      .finally(() => setLoading(false))
  }, [projectId])

  useEffect(() => { loadFiles() }, [loadFiles])

  if (loading) return <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={loadFiles}>Refresh</Button>
      </div>
      {files.length === 0 ? (
        <Empty description="No files" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <FileTree items={files} depth={0} onPreview={(path, name) => setPreviewTarget({ name, path })} />
      )}
      <FileViewerModal file={previewTarget} onClose={() => setPreviewTarget(null)} />
    </div>
  )
}

function FileTree({ items, depth, onPreview }: { items: FileNode[]; depth: number; onPreview: (path: string, name: string) => void }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (name: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  return (
    <div style={{ paddingLeft: depth * 16 }}>
      {items.map((item, i) => (
        <div key={i}>
          <div
            onClick={() => item.is_dir ? toggle(item.name) : onPreview(item.path, item.name)}
            style={{
              padding: '5px 8px', fontSize: 13, fontFamily: 'monospace', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 6, borderRadius: 4,
              color: item.is_dir ? '#1677ff' : '#333',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = '#f5f5f5')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            <span style={{ fontSize: 11, width: 14, textAlign: 'center' }}>
              {item.is_dir ? (expanded.has(item.name) ? '▼' : '▶') : ''}
            </span>
            {item.is_dir ? <FolderOutlined style={{ fontSize: 12, color: '#1677ff' }} /> : <FileIcon name={item.name} size={12} />}
            <span>{item.name}</span>
            {!item.is_dir && <span style={{ color: '#999', fontSize: 11, marginLeft: 'auto' }}>{(item.size / 1024).toFixed(1)}KB</span>}
          </div>
          {item.is_dir && expanded.has(item.name) && item.children && (
            <FileTree items={item.children} depth={depth + 1} onPreview={onPreview} />
          )}
        </div>
      ))}
    </div>
  )
}

// ── Data Sources Tab ───────────────────────────────────────────────────────

function DataSourcesTab({ projectId, initialDatasetIds, onDatasetIdsChange }: {
  projectId: string
  initialDatasetIds?: string[] | null
  onDatasetIdsChange?: (ids: string[] | null) => void
}) {
  const [datasets, setDatasets] = useState<any[]>([])
  const [selectedIds, setSelectedIds] = useState<string[] | null>(initialDatasetIds ?? null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    fetch(`${API}/data/datasets`).then(r => r.ok ? r.json() : []).then(setDatasets).catch(() => {})
  }, [projectId])

  // Load saved dataset_ids from project on mount
  useEffect(() => {
    fetch(`${API}/projects/${projectId}`)
      .then(r => r.ok ? r.json() : null)
      .then(p => { if (p?.dataset_ids !== undefined) setSelectedIds(p.dataset_ids) })
      .catch(() => {})
  }, [projectId])

  const filtered = datasets.filter(ds => !search || ds.name?.toLowerCase().includes(search.toLowerCase()))
  const limiting = selectedIds !== null
  const isSelected = (id: string) => !limiting || selectedIds!.includes(id)

  const saveSelection = (ids: string[] | null) => {
    setSelectedIds(ids)
    onDatasetIdsChange?.(ids)
    fetch(`${API}/projects/${projectId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_ids: ids }),
    }).catch(() => {})
  }

  const toggle = (id: string, on: boolean) => {
    const current = limiting ? [...selectedIds!] : datasets.map(d => d.id)
    const next = on ? [...current, id] : current.filter(x => x !== id)
    saveSelection(next)
  }

  return (
    <div style={{ padding: 24, maxWidth: 700 }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <Input placeholder="Search datasets..." value={search} onChange={e => setSearch(e.target.value)} style={{ maxWidth: 300 }} allowClear />
        <Button size="small" onClick={() => saveSelection(null)}>Use all</Button>
        <Button size="small" onClick={() => saveSelection([])}>Use none</Button>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#888' }}>
          {limiting ? `${selectedIds!.length} of ${datasets.length} selected` : `All ${datasets.length} datasets`}
        </span>
      </div>
      {filtered.length === 0 ? (
        <Empty description="No datasets" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {filtered.map(ds => (
            <Card key={ds.id} size="small" style={{ borderRadius: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Switch size="small" checked={isSelected(ds.id)} onChange={on => toggle(ds.id, on)} />
                <span style={{ fontWeight: 500 }}>{ds.name}</span>
                <Tag style={{ fontSize: 10 }}>{ds.type}</Tag>
                <Tag color={ds.status === 'connected' ? 'green' : 'red'} style={{ fontSize: 10 }}>{ds.status}</Tag>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Experiments Tab ────────────────────────────────────────────────────────

interface MlflowExperiment { session_id: string; session_title: string; experiment_id: string | null; runs: any[] }

function ExperimentsTab({ projectId }: { projectId: string }) {
  const [experiments, setExperiments] = useState<MlflowExperiment[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(`${API}/mlflow/project-runs?project_id=${projectId}`)
      .then(r => r.ok ? r.json() : [])
      .then(setExperiments)
      .catch(() => setExperiments([]))
      .finally(() => setLoading(false))
  }, [projectId])

  if (loading) return <div style={{ padding: 24, textAlign: 'center' }}><Spin /></div>

  const totalRuns = experiments.reduce((sum, e) => sum + e.runs.length, 0)

  if (experiments.length === 0) return (
    <div style={{ padding: 24 }}>
      <Empty description="No experiments yet — propose a plan in a chat session to create an MLflow experiment" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    </div>
  )

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 12, fontSize: 12, color: '#888' }}>
        {totalRuns} total run(s) across {experiments.length} session(s)
      </div>
      {experiments.map(exp => (
        <div key={exp.session_id} style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, padding: '6px 10px', background: '#fafafa', borderRadius: 6 }}>
            <ExperimentOutlined style={{ color: '#1677ff' }} />
            <span style={{ fontWeight: 600, fontSize: 13 }}>{exp.session_title}</span>
            <Tag style={{ fontSize: 10 }}>{exp.runs.length} run(s)</Tag>
            {exp.experiment_id && <span style={{ fontSize: 10, color: '#bbb', fontFamily: 'monospace', marginLeft: 'auto' }}>{exp.experiment_id}</span>}
          </div>
          <Table size="small" scroll={{ x: 'max-content' }} pagination={exp.runs.length > 10 ? { pageSize: 10, size: 'small' } : false}
            dataSource={exp.runs.map((r: any, i: number) => ({ key: i, ...r }))}
            columns={[
              { title: 'Run', dataIndex: 'run_id', key: 'run_id', width: 80,
                render: (v: string) => <code style={{ fontSize: 11 }}>{v?.slice(0, 8)}</code> },
              { title: 'Name', key: 'name', width: 120,
                render: (_: any, r: any) => r.tags?.['mlflow.runName'] || <span style={{ color: '#ccc' }}>&mdash;</span> },
              { title: 'Status', dataIndex: 'status', key: 'status', width: 80,
                render: (v: string) => <Tag color={v === 'FINISHED' ? 'green' : v === 'RUNNING' ? 'blue' : 'default'} style={{ fontSize: 10 }}>{v}</Tag> },
              { title: 'Params', dataIndex: 'params', key: 'params',
                render: (v: any) => v ? Object.entries(v).map(([k, val]) => <Tag key={k} color="blue" style={{ fontSize: 10 }}>{k}: {String(val)}</Tag>) : null },
              { title: 'Metrics', dataIndex: 'metrics', key: 'metrics',
                render: (v: any) => v ? Object.entries(v).map(([k, val]) => <Tag key={k} color="green" style={{ fontSize: 10 }}>{k}: {Number(val).toFixed(4)}</Tag>) : null },
              { title: 'Tags', dataIndex: 'tags', key: 'tags',
                render: (v: any) => v ? Object.entries(v).filter(([k]) => !k.startsWith('mlflow.')).map(([k, val]) => <Tag key={k} color="purple" style={{ fontSize: 10 }}>{k}: {String(val)}</Tag>) : null },
              { title: 'Datasets', dataIndex: 'datasets', key: 'datasets',
                render: (v: any[]) => v?.length ? v.map((d, i) => <Tag key={i} color="cyan" style={{ fontSize: 10 }}>{d.name}</Tag>) : null },
              { title: 'Artifacts', dataIndex: 'artifacts', key: 'artifacts',
                render: (v: any[]) => v?.length ? <Tag style={{ fontSize: 10 }}>{v.length} file(s)</Tag> : null },
              { title: 'Started', dataIndex: 'start_time', key: 'start_time', width: 140,
                render: (v: number) => v ? <span style={{ fontSize: 11, color: '#999' }}>{new Date(v).toLocaleString()}</span> : '' },
            ]}
          />
        </div>
      ))}
    </div>
  )
}
