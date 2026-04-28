import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Card, Empty, Input, Modal, Select, Popconfirm, Tag, message } from 'antd'
import { PlusOutlined, DeleteOutlined, RightOutlined } from '@ant-design/icons'
import { API } from '../api'

interface Project {
  id: string; name: string; description: string; directory: string; created_at: string
  kernel?: { mode: string; python_version: string; packages: string[] }
}

const REQUIRED_PACKAGES = [
  'ipykernel', 'requests', 'duckdb', 'mlflow',
]

const DEFAULT_PACKAGES = [
  ...REQUIRED_PACKAGES,
  // Data Manipulation & Analysis
  'pandas', 'numpy', 'polars',
  // Visualization
  'matplotlib', 'seaborn', 'plotly',
  // ML & Statistics
  'scikit-learn', 'statsmodels', 'xgboost', 'lightgbm', 'catboost',
  // Scientific Computing
  'scipy',
  // Data Access
  'beautifulsoup4', 'sqlalchemy',
]

const COMMON_PACKAGES = [
  ...DEFAULT_PACKAGES,
  // Deep Learning (large downloads, opt-in)
  'torch', 'tensorflow', 'keras',
  // Additional suggestions
  'scrapy', 'opencv-python', 'pillow',
  'httpx', 'transformers', 'langchain',
  'openai', 'anthropic',
]

export default function ProjectsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [projects, setProjects] = useState<Project[]>([])
  const [addOpen, setAddOpen] = useState(false)

  // Auto-open create modal if ?new=1
  useEffect(() => {
    if (searchParams.get('new') === '1') { resetForm(); setAddOpen(true) }
  }, [searchParams])
  const [form, setForm] = useState({
    name: '', description: '', directory: '',
    kernel_mode: 'new_env', python_version: '', kernel_python: '',
    packages: [...DEFAULT_PACKAGES],
  })

  const load = async () => {
    try { const r = await fetch(`${API}/projects/`); if (r.ok) setProjects(await r.json()) } catch {}
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    try {
      const res = await fetch(`${API}/projects/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name, description: form.description, directory: form.directory,
          kernel_mode: form.kernel_mode, python_version: form.python_version,
          kernel_python: form.kernel_python,
          packages: form.kernel_mode === 'new_env' ? form.packages : undefined,
        }),
      })
      if (res.ok) {
        const proj = await res.json()
        message.success('Project created')
        setAddOpen(false)
        resetForm()
        navigate(`/projects/${proj.id}`)
      } else message.error('Failed to create project')
    } catch { message.error('Failed to create project') }
  }

  const resetForm = () => setForm({
    name: '', description: '', directory: '',
    kernel_mode: 'new_env', python_version: '', kernel_python: '',
    packages: [...DEFAULT_PACKAGES],
  })

  const remove = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    await fetch(`${API}/projects/${id}`, { method: 'DELETE' })
    message.success('Project deleted')
    load()
  }

  return (
    <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontWeight: 600 }}>Projects</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { resetForm(); setAddOpen(true) }}>New Project</Button>
      </div>

      {projects.length === 0 ? (
        <Empty description="No projects yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {projects.map(p => (
            <Card key={p.id} size="small" style={{ borderRadius: 8, cursor: 'pointer' }} hoverable
              onClick={() => navigate(`/projects/${p.id}`)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{p.name}</div>
                  {p.description && <div style={{ fontSize: 13, color: '#666', marginTop: 2 }}>{p.description}</div>}
                  <div style={{ fontSize: 12, color: '#999', marginTop: 4, fontFamily: 'monospace' }}>{p.directory}</div>
                  <div style={{ fontSize: 11, color: '#bbb', marginTop: 2, display: 'flex', gap: 4, alignItems: 'center' }}>
                    {p.created_at && <span>Created {new Date(p.created_at).toLocaleDateString()}</span>}
                    {p.kernel && <Tag style={{ fontSize: 10 }}>{p.kernel.mode === 'new_env' ? 'Isolated env' : p.kernel.mode === 'system' ? 'System Python' : 'Custom'}</Tag>}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <Popconfirm title="Delete this project?" onConfirm={e => remove(e as any, p.id)} onPopupClick={e => e.stopPropagation()}>
                    <Button size="small" icon={<DeleteOutlined />} danger onClick={e => e.stopPropagation()} />
                  </Popconfirm>
                  <RightOutlined style={{ color: '#ccc' }} />
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create Project Modal */}
      <Modal title="New Project" open={addOpen} onCancel={() => setAddOpen(false)} onOk={create} okText="Create" width={600}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
          <Field label="Name">
            <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="My Analysis" />
          </Field>
          <Field label="Description (optional)">
            <Input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          </Field>
          <Field label="Directory (optional — defaults to ~/dataclaw-projects/)">
            <Input value={form.directory} onChange={e => setForm(f => ({ ...f, directory: e.target.value }))} placeholder="/path/to/project" />
          </Field>

          <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 14 }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>Python Environment</div>

            <Field label="Kernel Mode">
              <Select value={form.kernel_mode} onChange={v => setForm(f => ({ ...f, kernel_mode: v }))} style={{ width: '100%' }}
                options={[
                  { value: 'new_env', label: 'New isolated environment (recommended)' },
                  { value: 'system', label: 'System Python (no isolation)' },
                  { value: 'custom', label: 'Custom Python binary' },
                ]} />
            </Field>

            {form.kernel_mode === 'new_env' && (
              <>
                <Field label="Python Version (optional — uses current if empty)">
                  <Input value={form.python_version} onChange={e => setForm(f => ({ ...f, python_version: e.target.value }))}
                    placeholder="e.g. 3.12" />
                  <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>Leave empty to use the same Python as Dataclaw</div>
                </Field>

                <Field label="Packages to install">
                  <Select mode="tags" value={form.packages}
                    onChange={v => {
                      const withRequired = [...new Set([...REQUIRED_PACKAGES, ...v])]
                      setForm(f => ({ ...f, packages: withRequired }))
                    }}
                    style={{ width: '100%' }} placeholder="Type to add packages"
                    options={COMMON_PACKAGES.map(p => ({ value: p, label: p }))} />
                  <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                    Type a package name and press Enter to add custom packages.
                    Required packages (ipykernel, requests, duckdb, mlflow) cannot be removed.
                  </div>
                </Field>
              </>
            )}

            {form.kernel_mode === 'custom' && (
              <Field label="Python binary path">
                <Input value={form.kernel_python} onChange={e => setForm(f => ({ ...f, kernel_python: e.target.value }))}
                  placeholder="/path/to/python3" />
              </Field>
            )}
          </div>
        </div>
      </Modal>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{label}</div>{children}</div>
}
