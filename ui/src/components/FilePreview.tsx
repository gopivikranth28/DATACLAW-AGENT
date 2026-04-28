import { useState, useEffect } from 'react'
import type React from 'react'
import { Button, Empty, Modal, Spin, Table, Tag, Typography } from 'antd'
import { FileTextOutlined, TableOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { IpynbRenderer as IpynbView } from 'react-ipynb-renderer'
import 'react-ipynb-renderer/dist/styles/default.css'
import { API } from '../api'

const { Text } = Typography

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico'])

function isImageFile(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  return IMAGE_EXTENSIONS.has(ext)
}

export function FileViewerModal({ file, onClose }: {
  file: { name: string; path: string } | null
  onClose: () => void
}) {
  const [content, setContent] = useState<string | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!file) return
    setLoading(true)
    setContent(null)
    setImageUrl(null)

    const url = `${API}/workspace/files?path=${encodeURIComponent(file.path)}`

    if (isImageFile(file.name)) {
      fetch(url)
        .then(r => r.ok ? r.blob() : Promise.reject('Not found'))
        .then(blob => setImageUrl(URL.createObjectURL(blob)))
        .catch(() => setContent('Error loading image'))
        .finally(() => setLoading(false))
    } else {
      fetch(url)
        .then(r => r.ok ? r.text() : Promise.reject('Not found'))
        .then(setContent)
        .catch(() => setContent('Error loading file'))
        .finally(() => setLoading(false))
    }

    return () => {
      // Clean up blob URL on unmount
      setImageUrl(prev => { if (prev) URL.revokeObjectURL(prev); return null })
    }
  }, [file?.path])

  return (
    <Modal
      title={file ? <><FileIcon name={file.name} /> {file.name}</> : 'File'}
      open={!!file}
      onCancel={onClose}
      footer={null}
      width={file?.name.endsWith('.svg') ? 800 : 960}
      styles={{ body: { maxHeight: '70vh', overflow: 'auto' } }}
    >
      {loading || (!content && !imageUrl) || !file ? <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
        : imageUrl ? <div style={{ textAlign: 'center', padding: 16 }}><img src={imageUrl} alt={file.name} style={{ maxWidth: '100%', borderRadius: 8 }} /></div>
        : <FileRenderer name={file.name} content={content!} />}
    </Modal>
  )
}

function isMarimo(content: string) {
  return content.includes('marimo.App') || content.includes('import marimo')
}

export function FileRenderer({ name, content }: { name: string; content: string }) {
  const ext = name.split('.').pop()?.toLowerCase()
  switch (ext) {
    case 'md':    return <MarkdownRenderer content={content} />
    case 'csv':   return <CsvRenderer content={content} />
    case 'svg':   return <SvgRenderer content={content} />
    case 'ipynb': return <IpynbFileRenderer content={content} />
    case 'py':    return isMarimo(content) ? <MarimoRenderer content={content} name={name} /> : <PythonRenderer content={content} />
    case 'json':  return <pre style={CODE_STYLE}>{tryPrettyJson(content)}</pre>
    default:      return <pre style={CODE_STYLE}>{content}</pre>
  }
}

function CsvRenderer({ content }: { content: string }) {
  const lines = content.trim().split('\n').filter(l => l.trim())
  if (lines.length === 0) return <Empty description="Empty CSV" />

  const headers = parseCsvLine(lines[0])
  const rows = lines.slice(1).map((line, i) => {
    const values = parseCsvLine(line)
    const row: Record<string, string | number> = { _key: i }
    headers.forEach((h, j) => { row[h] = values[j] ?? '' })
    return row
  })

  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 11, color: '#888' }}>
        {rows.length} rows &middot; {headers.length} columns
      </div>
      <Table
        dataSource={rows} rowKey="_key" size="small"
        scroll={{ x: 'max-content' }}
        pagination={rows.length > 20 ? { pageSize: 20, size: 'small' } : false}
        columns={headers.map(h => ({
          title: <span style={{ fontSize: 11, fontWeight: 700 }}>{h}</span>,
          dataIndex: h, key: h, ellipsis: true,
          render: (v: unknown) => <CellValue value={v} />,
        }))}
      />
    </div>
  )
}

function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let current = '', inQuotes = false
  for (const ch of line) {
    if (ch === '"') { inQuotes = !inQuotes; continue }
    if (ch === ',' && !inQuotes) { result.push(current.trim()); current = ''; continue }
    current += ch
  }
  result.push(current.trim())
  return result
}

function SvgRenderer({ content }: { content: string }) {
  return (
    <div style={{ textAlign: 'center', padding: 16, background: '#fafafa', borderRadius: 8 }}>
      <div dangerouslySetInnerHTML={{ __html: content }} style={{ maxWidth: 700, margin: '0 auto' }} />
    </div>
  )
}

function IpynbFileRenderer({ content }: { content: string }) {
  const [showCode, setShowCode] = useState(false)

  let ipynb: { cells: Record<string, unknown>[] } | null = null
  try { ipynb = JSON.parse(content) } catch {
    return <pre style={CODE_STYLE}>Failed to parse notebook</pre>
  }

  const cellCount = ipynb?.cells?.length ?? 0
  const filtered = showCode ? ipynb! : {
    ...ipynb!,
    cells: ipynb!.cells.map(c => c.cell_type === 'code' ? { ...c, source: [] } : c),
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
        padding: '8px 14px', background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 8 }}>
        <span style={{ fontSize: 16 }}>&#x1F4D3;</span>
        <div style={{ flex: 1, fontSize: 12, color: '#9a3412' }}>
          <strong>Jupyter Notebook</strong> &mdash; {cellCount} cells
        </div>
        <Button size="small" type={showCode ? 'primary' : 'default'}
          onClick={() => setShowCode(v => !v)}>
          {showCode ? 'Hide Code' : 'Show Code'}
        </Button>
      </div>
      <IpynbView ipynb={filtered} syntaxTheme="vscDarkPlus" language="python" />
    </div>
  )
}

function PythonRenderer({ content }: { content: string }) {
  return (
    <div style={{ position: 'relative' }}>
      <div style={{ position: 'absolute', top: 8, right: 12, fontSize: 10, color: '#888',
        background: '#2a2a3e', padding: '2px 8px', borderRadius: 4 }}>python</div>
      <pre style={{ ...CODE_STYLE, paddingTop: 28 }}>{content}</pre>
    </div>
  )
}

interface MarimoCell { code: string; output: React.ReactNode | null }

function parseMarimoCells(content: string): MarimoCell[] {
  const cells: MarimoCell[] = []
  const cellPattern = /@app\.cell[\s\S]*?\ndef [^(]+\([^)]*\):\n([\s\S]*?)(?=\n@app\.cell|\nif __name__|$)/g
  let match
  while ((match = cellPattern.exec(content)) !== null) {
    const body = match[1]
    const lines = body.split('\n')
    const indent = lines.find(l => l.trim())?.match(/^(\s*)/)?.[1].length ?? 4
    const code = lines.map(l => l.slice(indent)).join('\n').trim()
    const output = parseCellOutput(code)
    cells.push({ code, output })
  }
  return cells
}

function parseCellOutput(code: string): React.ReactNode | null {
  const mdMatch = code.match(/mo\.md\(\s*(?:"""([\s\S]*?)"""|"([^"]*)"|([\s\S]*?))\s*\)/)
  if (mdMatch) {
    const raw = mdMatch[1] ?? mdMatch[2] ?? ''
    const lines = raw.split('\n')
    const minIndent = lines.filter(l => l.trim()).reduce((min, l) => {
      const m = l.match(/^(\s*)/)
      return m ? Math.min(min, m[1].length) : min
    }, Infinity)
    const md = lines.map(l => l.slice(Math.min(minIndent, l.length))).join('\n').trim()
    return <MarkdownRenderer content={md} />
  }

  const tableMatch = code.match(/mo\.ui\.table\(\s*(\[[\s\S]*?\])\s*(?:,\s*label\s*=\s*"([^"]*)")?\s*\)/)
  if (tableMatch) {
    try {
      const jsonStr = tableMatch[1].replace(/'/g, '"').replace(/True/g, 'true').replace(/False/g, 'false').replace(/None/g, 'null')
      const data = JSON.parse(jsonStr) as Record<string, unknown>[]
      const label = tableMatch[2]
      const cols = Object.keys(data[0] || {})
      return (
        <div>
          {label && <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 8, color: '#555' }}>{label}</div>}
          <Table
            dataSource={data.map((r, i) => ({ ...r, _key: i }))} rowKey="_key"
            size="small" pagination={false} scroll={{ x: 'max-content' }}
            columns={cols.map(col => ({
              title: <span style={{ fontSize: 11, fontWeight: 700 }}>{col}</span>,
              dataIndex: col, key: col,
              render: (v: unknown) => <CellValue value={v} />,
            }))}
          />
        </div>
      )
    } catch { /* fall through */ }
  }

  const calloutMatch = code.match(/mo\.callout\(\s*([\s\S]*?)\s*,\s*kind\s*=\s*"(\w+)"/)
  if (calloutMatch) {
    const innerMd = calloutMatch[1].match(/mo\.md\(\s*(?:"""([\s\S]*?)"""|"([^"]*)")\s*\)/)
    const kind = calloutMatch[2]
    const text = (innerMd?.[1] ?? innerMd?.[2] ?? '').trim()
    const cleaned = text.replace(/"\s*\n\s*"/g, '')
    const colors: Record<string, { bg: string; border: string; fg: string }> = {
      success: { bg: '#f0fdf4', border: '#bbf7d0', fg: '#15803d' },
      warn: { bg: '#fffbeb', border: '#fde68a', fg: '#92400e' },
      danger: { bg: '#fef2f2', border: '#fecaca', fg: '#991b1b' },
      info: { bg: '#eff6ff', border: '#bfdbfe', fg: '#1e40af' },
    }
    const c = colors[kind] || colors.info
    return (
      <div style={{ padding: '12px 16px', background: c.bg, border: `1px solid ${c.border}`,
        borderRadius: 8, fontSize: 13, color: c.fg, lineHeight: 1.6 }}>
        <MarkdownRenderer content={cleaned} />
      </div>
    )
  }

  return null
}

function MarimoRenderer({ content, name }: { content: string; name: string }) {
  const [mode, setMode] = useState<'outputs' | 'code'>('outputs')
  const cells = parseMarimoCells(content)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
        padding: '8px 14px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8 }}>
        <span style={{ fontSize: 16 }}>&#x1F34B;</span>
        <div style={{ flex: 1, fontSize: 12, color: '#15803d' }}>
          <strong>Marimo Notebook</strong> &mdash; open interactively with{' '}
          <code style={{ background: '#dcfce7', padding: '1px 5px', borderRadius: 3 }}>marimo edit {name}</code>
        </div>
        <Button.Group size="small">
          <Button type={mode === 'outputs' ? 'primary' : 'default'} onClick={() => setMode('outputs')}>Outputs</Button>
          <Button type={mode === 'code' ? 'primary' : 'default'} onClick={() => setMode('code')}>Code</Button>
        </Button.Group>
      </div>

      {mode === 'outputs' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {cells.map((cell, i) => (
            cell.output ? (
              <div key={i}>{cell.output}</div>
            ) : (
              <div key={i} style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', top: 6, right: 10, fontSize: 10, color: '#888',
                  background: '#2a2a3e', padding: '1px 6px', borderRadius: 3 }}>cell {i + 1}</div>
                <pre style={{ ...CODE_STYLE, paddingTop: 24, fontSize: 11 }}>{cell.code}</pre>
              </div>
            )
          ))}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {cells.map((cell, i) => (
            <div key={i} style={{ position: 'relative' }}>
              <div style={{ position: 'absolute', top: 6, right: 10, fontSize: 10, color: '#888',
                background: '#2a2a3e', padding: '1px 6px', borderRadius: 3 }}>cell {i + 1}</div>
              <pre style={{ ...CODE_STYLE, paddingTop: 24, fontSize: 11 }}>{cell.code}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div style={{ fontSize: 13, lineHeight: 1.7, overflowX: 'hidden', minWidth: 0 }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        table: ({ children }) => <div style={{ overflowX: 'auto', margin: '12px 0' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>{children}</table></div>,
        th: ({ children }) => <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '2px solid #e8e8e8', background: '#fafafa', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>{children}</th>,
        td: ({ children }) => <td style={{ padding: '6px 12px', borderBottom: '1px solid #f0f0f0' }}>{children}</td>,
        h2: ({ children }) => <h2 style={{ fontSize: 16, fontWeight: 700, margin: '14px 0 6px', color: '#1677ff' }}>{children}</h2>,
        h3: ({ children }) => <h3 style={{ fontSize: 14, fontWeight: 700, margin: '12px 0 4px' }}>{children}</h3>,
        code: ({ children, className }) => className
          ? <pre style={{ background: '#f6f8fa', padding: 12, borderRadius: 6, overflow: 'auto', fontSize: 12 }}><code>{children}</code></pre>
          : <code style={{ background: '#f0f0f0', padding: '1px 4px', borderRadius: 3, fontSize: '0.9em' }}>{children}</code>,
      }}>{content}</ReactMarkdown>
    </div>
  )
}

const CODE_STYLE: React.CSSProperties = {
  background: '#1e1e2e', color: '#cdd6f4', padding: 16, borderRadius: 8,
  overflow: 'auto', fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap',
}

export function CellValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <Text type="secondary" italic>null</Text>
  if (typeof value === 'boolean') return <Tag color={value ? 'green' : 'red'}>{String(value)}</Tag>
  if (typeof value === 'number') return <span style={{ fontFamily: 'monospace' }}>{value.toLocaleString()}</span>
  return <>{String(value)}</>
}

export function FileIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase()
  const style = { marginRight: 2 }
  if (ext === 'csv') return <TableOutlined style={{ ...style, color: '#52c41a' }} />
  if (ext === 'svg' || ext === 'png' || ext === 'jpg') return <span style={style}>&#x1F4CA;</span>
  if (ext === 'ipynb') return <span style={style}>&#x1F4D3;</span>
  if (ext === 'py') return <span style={style}>&#x1F40D;</span>
  return <FileTextOutlined style={{ ...style, color: '#888' }} />
}

function tryPrettyJson(s: string): string {
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}
