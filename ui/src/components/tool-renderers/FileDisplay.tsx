import { useState } from 'react'
import { Button } from 'antd'
import { FileOutlined, EyeOutlined } from '@ant-design/icons'
import { FileViewerModal } from '../FilePreview'

interface WriteFileData {
  path?: string
  written?: boolean
  size?: number
}

interface ReadFileData {
  path?: string
  content?: string
  size?: number
  truncated?: boolean
}

export function FileWriteDisplay({ data, onFileClick }: { data: WriteFileData; onFileClick?: (path: string) => void }) {
  const [viewerFile, setViewerFile] = useState<{ name: string; path: string } | null>(null)
  const name = data.path?.split('/').pop() || 'file'

  const handleView = () => {
    if (!data.path) return
    if (onFileClick) {
      onFileClick(data.path)
    } else {
      setViewerFile({ name, path: data.path })
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
        <FileOutlined style={{ color: '#52c41a', fontSize: 13 }} />
        <span style={{ fontWeight: 500 }}>Created {name}</span>
        {data.size !== undefined && <span style={{ color: '#999', fontSize: 11 }}>({formatSize(data.size)})</span>}
        {data.path && (
          <Button size="small" icon={<EyeOutlined />} onClick={handleView}>View</Button>
        )}
      </div>
      {data.path && <div style={{ fontSize: 10, color: '#999', fontFamily: 'monospace', marginTop: 2 }}>{data.path}</div>}
      {!onFileClick && <FileViewerModal file={viewerFile} onClose={() => setViewerFile(null)} />}
    </div>
  )
}

export function FileReadDisplay({ data, onFileClick }: { data: ReadFileData; onFileClick?: (path: string) => void }) {
  const [viewerFile, setViewerFile] = useState<{ name: string; path: string } | null>(null)
  const name = data.path?.split('/').pop() || 'file'

  const handleView = () => {
    if (!data.path) return
    if (onFileClick) {
      onFileClick(data.path)
    } else {
      setViewerFile({ name, path: data.path })
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 4 }}>
        <FileOutlined style={{ color: '#1677ff', fontSize: 13 }} />
        <span style={{ fontWeight: 500 }}>{name}</span>
        {data.size !== undefined && <span style={{ color: '#999', fontSize: 11 }}>({formatSize(data.size)})</span>}
        {data.truncated && <span style={{ color: '#faad14', fontSize: 10 }}>(truncated)</span>}
        {data.path && (
          <Button size="small" icon={<EyeOutlined />} onClick={handleView}>View Full</Button>
        )}
      </div>
      {data.content && (
        <pre style={{
          background: '#f8f9fa', padding: 8, borderRadius: 4, fontSize: 11,
          maxHeight: 200, overflow: 'auto', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {data.content.slice(0, 2000)}{data.content.length > 2000 ? '\n...' : ''}
        </pre>
      )}
      {!onFileClick && <FileViewerModal file={viewerFile} onClose={() => setViewerFile(null)} />}
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}
