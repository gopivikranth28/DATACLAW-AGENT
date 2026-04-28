import { useState, useEffect } from 'react'
import { Button, Card, Collapse, Empty, Input, Modal, Select, Segmented, Table, Tag, Upload, Popconfirm, message, Alert } from 'antd'
import { PlusOutlined, DeleteOutlined, ReloadOutlined, EyeOutlined, EditOutlined, ApiOutlined, UploadOutlined, InboxOutlined } from '@ant-design/icons'
import { API } from '../api'

interface ColumnDetail { name: string; type: string }
interface TableInfo { name: string; rows: number; columns: number; column_details?: ColumnDetail[] }
interface Dataset {
  id: string; name: string; type: string; status: string; connection: string
  description: string; tables: TableInfo[]; created_at?: string
}

const TYPE_OPTIONS = [
  { value: 'local_file', label: 'Local File (CSV/Parquet)' },
  { value: 'duckdb', label: 'DuckDB Database' },
  { value: 'csv', label: 'CSV' },
  { value: 'parquet', label: 'Parquet' },
  { value: 'postgres', label: 'PostgreSQL' },
  { value: 'snowflake', label: 'Snowflake' },
  { value: 'bigquery', label: 'BigQuery' },
]

const TYPE_HELP: Record<string, string> = {
  local_file: 'Path to a CSV or Parquet file, or a directory containing them',
  duckdb: 'Path to a .duckdb database file',
  csv: 'Path to a .csv file or directory of CSV files',
  parquet: 'Path to a .parquet file or directory',
  postgres: 'PostgreSQL connection string: postgresql://user:pass@host:5432/db',
  snowflake: 'Snowflake connection: snowflake://user:pass@account/db/schema?warehouse=WH',
  bigquery: 'BigQuery project ID or service account JSON path',
}

export default function DataPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'local_file', connection: '', description: '' })
  const [testing, setTesting] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editForm, setEditForm] = useState<Partial<Dataset>>({})
  const [defsOpen, setDefsOpen] = useState(false)
  const [defsDs, setDefsDs] = useState<Dataset | null>(null)
  const [defsDesc, setDefsDesc] = useState('')
  const [defsDef, setDefsDef] = useState('')
  const [defsTable, setDefsTable] = useState<Record<string, string>>({})
  const [defsCol, setDefsCol] = useState<Record<string, Record<string, string>>>({})
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewData, setPreviewData] = useState<any>(null)
  const [previewTitle, setPreviewTitle] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadMode, setUploadMode] = useState<'file' | 'folder'>('file')
  const [uploadName, setUploadName] = useState('')
  const [uploadDesc, setUploadDesc] = useState('')
  const [uploadFiles, setUploadFiles] = useState<any[]>([])

  const load = async () => {
    setLoading(true)
    try { const r = await fetch(`${API}/data/datasets`); if (r.ok) setDatasets(await r.json()) } catch {}
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const testAndCreate = async () => {
    setTesting(true)
    try {
      const res = await fetch(`${API}/data/datasets`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (res.ok) {
        const ds = await res.json()
        message.success(ds.status === 'connected' ? `Connected! Found ${ds.tables?.length || 0} table(s)` : 'Created (could not introspect tables)')
        setAddOpen(false)
        setForm({ name: '', type: 'local_file', connection: '', description: '' })
        load()
      } else message.error('Failed to create dataset')
    } catch { message.error('Connection failed') }
    setTesting(false)
  }

  const openEdit = (ds: Dataset) => {
    setEditForm({ id: ds.id, name: ds.name, description: ds.description, type: ds.type, connection: ds.connection })
    setEditOpen(true)
  }

  const saveEdit = async () => {
    if (!editForm.id) return
    try {
      const res = await fetch(`${API}/data/datasets/${editForm.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editForm.name, description: editForm.description, connection: editForm.connection, type: editForm.type }),
      })
      if (res.ok) { message.success('Dataset updated'); setEditOpen(false); load() }
      else message.error('Failed to update')
    } catch { message.error('Failed to update') }
  }

  const openDefs = (ds: Dataset) => {
    setDefsDs(ds)
    setDefsDesc((ds as any).description || '')
    setDefsDef((ds as any).definition || '')
    setDefsTable((ds as any).table_definitions || {})
    setDefsCol((ds as any).column_definitions || {})
    setDefsOpen(true)
  }

  const saveDefs = async () => {
    if (!defsDs) return
    try {
      const res = await fetch(`${API}/data/datasets/${defsDs.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: defsDesc, definition: defsDef, table_definitions: defsTable, column_definitions: defsCol }),
      })
      if (res.ok) { message.success('Definitions saved'); setDefsOpen(false); load() }
      else message.error('Failed to save')
    } catch { message.error('Failed to save') }
  }

  const remove = async (id: string) => { await fetch(`${API}/data/datasets/${id}`, { method: 'DELETE' }); load() }
  const refresh = async (id: string) => { await fetch(`${API}/data/datasets/${id}/refresh`, { method: 'POST' }); message.success('Refreshed'); load() }

  const preview = async (datasetId: string, tableName: string) => {
    try {
      const res = await fetch(`${API}/data/datasets/${datasetId}/preview?table=${encodeURIComponent(tableName)}&n_rows=50`)
      if (res.ok) { setPreviewData(await res.json()); setPreviewTitle(tableName); setPreviewOpen(true) }
    } catch {}
  }

  const handleUpload = async () => {
    if (uploadFiles.length === 0) return
    setUploading(true)
    try {
      const formData = new FormData()
      for (const f of uploadFiles) {
        const file = f.originFileObj || f
        formData.append('files', file, f.originFileObj?.webkitRelativePath || file.name)
      }
      if (uploadName) formData.append('name', uploadName)
      if (uploadDesc) formData.append('description', uploadDesc)
      const res = await fetch(`${API}/data/datasets/upload`, { method: 'POST', body: formData })
      if (res.ok) {
        const ds = await res.json()
        message.success(`Uploaded! Found ${ds.tables?.length || 0} table(s)`)
        setUploadOpen(false)
        setUploadFiles([]); setUploadName(''); setUploadDesc('')
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        message.error(err.detail || 'Upload failed')
      }
    } catch { message.error('Upload failed') }
    setUploading(false)
  }

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontWeight: 600 }}>Datasets</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<UploadOutlined />} onClick={() => { setUploadFiles([]); setUploadName(''); setUploadDesc(''); setUploadMode('file'); setUploadOpen(true) }}>Upload</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setForm({ name: '', type: 'local_file', connection: '', description: '' }); setAddOpen(true) }}>Add Dataset</Button>
        </div>
      </div>

      {datasets.length === 0 && !loading ? (
        <Empty description="No datasets registered" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {datasets.map(ds => (
            <Card key={ds.id} size="small" style={{ borderRadius: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>{ds.name}</div>
                  <div style={{ fontSize: 12, color: '#888', marginTop: 2, display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                    <Tag color={ds.status === 'connected' ? 'green' : 'red'}>{ds.status}</Tag>
                    <Tag>{ds.type}</Tag>
                    {ds.description && <span>{ds.description}</span>}
                  </div>
                  <div style={{ fontSize: 11, color: '#bbb', marginTop: 2, fontFamily: 'monospace' }}>
                    {ds.connection.length > 80 ? ds.connection.slice(0, 80) + '...' : ds.connection}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(ds)} title="Edit" />
                  <Button size="small" onClick={() => openDefs(ds)} title="Definitions">Defs</Button>
                  <Button size="small" icon={<ReloadOutlined />} onClick={() => refresh(ds.id)} title="Refresh" />
                  <Popconfirm title="Delete this dataset?" onConfirm={() => remove(ds.id)}>
                    <Button size="small" icon={<DeleteOutlined />} danger />
                  </Popconfirm>
                </div>
              </div>

              {ds.tables && ds.tables.length > 0 && (
                <Collapse size="small" ghost style={{ marginTop: 8 }}
                  items={ds.tables.map((t, i) => ({
                    key: i,
                    label: (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                        <span style={{ fontFamily: 'monospace' }}>{t.name}</span>
                        <span style={{ color: '#999', fontSize: 11 }}>{t.rows} rows, {t.columns} cols</span>
                        <Button size="small" icon={<EyeOutlined />} onClick={e => { e.stopPropagation(); preview(ds.id, t.name) }} style={{ marginLeft: 'auto' }} />
                      </div>
                    ),
                    children: t.column_details && t.column_details.length > 0 ? (
                      <Table size="small" pagination={false}
                        dataSource={t.column_details.map((c, j) => ({ key: j, ...c }))}
                        columns={[
                          { title: 'Column', dataIndex: 'name', key: 'name', render: (v: string) => <code style={{ fontSize: 12 }}>{v}</code> },
                          { title: 'Type', dataIndex: 'type', key: 'type', render: (v: string) => <Tag style={{ fontSize: 11 }}>{v}</Tag> },
                        ]}
                      />
                    ) : <span style={{ color: '#999', fontSize: 12 }}>No column details</span>,
                  }))}
                />
              )}
            </Card>
          ))}
        </div>
      )}

      {/* Add Dataset Modal */}
      <Modal title="Add Dataset" open={addOpen} onCancel={() => setAddOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setAddOpen(false)}>Cancel</Button>,
          <Button key="test" type="primary" icon={<ApiOutlined />} loading={testing} onClick={testAndCreate}>Test & Create</Button>,
        ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
          <Field label="Name">
            <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Sales Data" />
          </Field>
          <Field label="Type">
            <Select value={form.type} onChange={v => setForm(f => ({ ...f, type: v }))} style={{ width: '100%' }} options={TYPE_OPTIONS} />
          </Field>
          <Field label="Connection">
            <Input value={form.connection} onChange={e => setForm(f => ({ ...f, connection: e.target.value }))}
              placeholder={TYPE_HELP[form.type] || 'Connection string or path'} />
            <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>{TYPE_HELP[form.type]}</div>
          </Field>
          <Field label="Description (optional)">
            <Input.TextArea value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} rows={2} />
          </Field>
        </div>
      </Modal>

      {/* Edit Dataset Modal */}
      <Modal title="Edit Dataset" open={editOpen} onCancel={() => setEditOpen(false)} onOk={saveEdit} okText="Save">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
          <Field label="Name"><Input value={editForm.name || ''} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} /></Field>
          <Field label="Type"><Select value={editForm.type} onChange={v => setEditForm(f => ({ ...f, type: v }))} style={{ width: '100%' }} options={TYPE_OPTIONS} /></Field>
          <Field label="Connection"><Input value={editForm.connection || ''} onChange={e => setEditForm(f => ({ ...f, connection: e.target.value }))} /></Field>
          <Field label="Description"><Input.TextArea value={editForm.description || ''} onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))} rows={2} /></Field>
          <Alert type="info" message="Changing the connection will re-introspect tables on save." showIcon />
        </div>
      </Modal>

      {/* Preview Modal */}
      <Modal title={`Preview: ${previewTitle}`} open={previewOpen} onCancel={() => setPreviewOpen(false)} footer={null} width={800}>
        {previewData && (
          <Table size="small" scroll={{ x: true }} pagination={{ pageSize: 20, size: 'small' }}
            dataSource={(previewData.rows || []).map((r: any, i: number) => ({ key: i, ...r }))}
            columns={(previewData.columns || []).map((col: string) => ({
              title: col, dataIndex: col, key: col, ellipsis: true,
              render: (v: any) => <span style={{ fontSize: 12 }}>{v === null ? <span style={{ color: '#ccc' }}>null</span> : String(v)}</span>,
            }))}
          />
        )}
      </Modal>

      {/* Definitions Modal */}
      <Modal title={`Definitions: ${defsDs?.name || ''}`} open={defsOpen} onCancel={() => setDefsOpen(false)} onOk={saveDefs} okText="Save" width={700}>
        {defsDs && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12, maxHeight: '60vh', overflow: 'auto' }}>
            <Field label="Description">
              <Input.TextArea value={defsDesc} onChange={e => setDefsDesc(e.target.value)} rows={2} placeholder="Short description of this dataset" />
            </Field>
            <Field label="Definition">
              <Input.TextArea value={defsDef} onChange={e => setDefsDef(e.target.value)} rows={3} placeholder="Detailed definition — grain, scope, business context" />
            </Field>
            {defsDs.tables?.map(t => {
              const tKey = t.name
              return (
                <div key={tKey} style={{ border: '1px solid #eee', borderRadius: 6, padding: 10 }}>
                  <div style={{ fontWeight: 500, fontFamily: 'monospace', marginBottom: 6 }}>{tKey}</div>
                  <Field label="Table description">
                    <Input value={defsTable[tKey] || ''} onChange={e => setDefsTable(prev => ({ ...prev, [tKey]: e.target.value }))} placeholder="What this table contains" />
                  </Field>
                  {t.column_details?.map(col => (
                    <div key={col.name} style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                      <code style={{ fontSize: 12, minWidth: 120, color: '#555' }}>{col.name}</code>
                      <Tag style={{ fontSize: 10 }}>{col.type}</Tag>
                      <Input size="small" value={(defsCol[tKey] || {})[col.name] || ''} placeholder="Column description"
                        onChange={e => setDefsCol(prev => ({ ...prev, [tKey]: { ...(prev[tKey] || {}), [col.name]: e.target.value } }))} />
                    </div>
                  ))}
                </div>
              )
            })}
          </div>
        )}
      </Modal>
      {/* Upload Modal */}
      <Modal title="Upload CSV / Parquet" open={uploadOpen} onCancel={() => setUploadOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setUploadOpen(false)}>Cancel</Button>,
          <Button key="upload" type="primary" icon={<UploadOutlined />}
            loading={uploading} disabled={uploadFiles.length === 0} onClick={handleUpload}>Upload</Button>,
        ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
          <Segmented value={uploadMode} onChange={v => { setUploadMode(v as 'file' | 'folder'); setUploadFiles([]) }}
            options={[{ label: 'File', value: 'file' }, { label: 'Folder', value: 'folder' }]} />
          {uploadMode === 'file' ? (
            <Upload.Dragger
              accept=".csv,.parquet"
              maxCount={1}
              fileList={uploadFiles}
              beforeUpload={() => false}
              onChange={({ fileList }) => setUploadFiles(fileList)}
            >
              <p style={{ fontSize: 32, color: '#999', margin: 0 }}><InboxOutlined /></p>
              <p style={{ margin: '8px 0 0' }}>Click or drag a CSV or Parquet file</p>
            </Upload.Dragger>
          ) : (
            <Upload.Dragger
              directory
              multiple
              fileList={uploadFiles}
              beforeUpload={() => false}
              onChange={({ fileList }) => setUploadFiles(fileList.filter(f => {
                const name = f.name?.toLowerCase() || ''
                return name.endsWith('.csv') || name.endsWith('.parquet')
              }))}
            >
              <p style={{ fontSize: 32, color: '#999', margin: 0 }}><InboxOutlined /></p>
              <p style={{ margin: '8px 0 0' }}>Click to select a folder with CSV / Parquet files</p>
            </Upload.Dragger>
          )}
          <Field label="Name (optional)">
            <Input value={uploadName} onChange={e => setUploadName(e.target.value)} placeholder="Leave blank to use filename" />
          </Field>
          <Field label="Description (optional)">
            <Input.TextArea value={uploadDesc} onChange={e => setUploadDesc(e.target.value)} rows={2} />
          </Field>
        </div>
      </Modal>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div><div style={{ fontSize: 13, color: '#666', marginBottom: 4 }}>{label}</div>{children}</div>
}
