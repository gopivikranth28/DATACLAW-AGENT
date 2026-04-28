import { useState } from 'react'
import { Button, Tag } from 'antd'
import { BookOutlined, EyeOutlined } from '@ant-design/icons'
import { FileViewerModal } from '../FilePreview'

interface NotebookData {
  name?: string
  path?: string
  num_cells?: number
}

export default function NotebookLink({ data }: { data: NotebookData }) {
  const [viewerFile, setViewerFile] = useState<{ name: string; path: string } | null>(null)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
        <BookOutlined style={{ color: '#1677ff', fontSize: 14 }} />
        <span style={{ fontWeight: 500 }}>{data.name || 'Notebook'}</span>
        {data.num_cells !== undefined && (
          <Tag style={{ fontSize: 10 }}>{data.num_cells} cells</Tag>
        )}
        {data.path && (
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => setViewerFile({ name: `${data.name || 'notebook'}.ipynb`, path: data.path! })}
          >
            View Notebook
          </Button>
        )}
      </div>
      {data.path && (
        <div style={{ fontSize: 10, color: '#999', fontFamily: 'monospace', marginTop: 4 }}>{data.path}</div>
      )}
      <FileViewerModal file={viewerFile} onClose={() => setViewerFile(null)} />
    </div>
  )
}
