import { Button } from 'antd'
import { FileTextOutlined, EyeOutlined, PrinterOutlined, ExportOutlined, DownloadOutlined } from '@ant-design/icons'
import { API } from '../../api'
import { reportDocumentUrl, reportPreviewUrl } from '../reportPreview'

interface ReportData {
  html_path?: string
  docx_path?: string
  size?: number
  created?: boolean
  // legacy fields from old PDF-based tool
  path?: string
  format?: string
}

export default function ReportDisplay({ data, onFileClick }: {
  data: ReportData
  onFileClick?: (path: string) => void
}) {
  const htmlPath = data.html_path || data.path
  const name = htmlPath?.split('/').pop() || 'report.html'
  const previewUrl = htmlPath ? reportPreviewUrl(htmlPath) : ''
  const documentUrl = htmlPath ? reportDocumentUrl(htmlPath, data.size !== undefined ? String(data.size) : undefined) : ''

  const handleView = () => {
    if (!htmlPath) return
    if (onFileClick) onFileClick(htmlPath)
    else handleOpenNewTab()
  }

  const handlePrint = () => {
    if (!htmlPath) return
    window.open(reportPreviewUrl(htmlPath, { print: true }), '_blank')
  }

  const handleOpenNewTab = () => {
    if (!htmlPath) return
    window.open(previewUrl, '_blank')
  }

  const handleDownloadDocx = async () => {
    if (!data.docx_path) return
    const url = `${API}/workspace/files?path=${encodeURIComponent(data.docx_path)}`
    const res = await fetch(url)
    const blob = await res.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = name.replace(/\.html?$/, '.docx')
    a.click()
    URL.revokeObjectURL(blobUrl)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <FileTextOutlined style={{ color: '#1677ff', fontSize: 14 }} />
        <span style={{ fontWeight: 500 }}>Report: {name}</span>
        {data.size !== undefined && (
          <span style={{ color: '#999', fontSize: 11 }}>({formatSize(data.size)})</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <Button size="small" icon={<EyeOutlined />} onClick={handleView}>View</Button>
          <Button size="small" icon={<PrinterOutlined />} onClick={handlePrint}>Print</Button>
          <Button size="small" icon={<ExportOutlined />} onClick={handleOpenNewTab}>New Tab</Button>
          {data.docx_path && (
            <Button size="small" icon={<DownloadOutlined />} onClick={handleDownloadDocx}>Word</Button>
          )}
        </div>
      </div>
      {documentUrl && (
        <iframe
          src={documentUrl}
          sandbox="allow-scripts allow-forms allow-popups allow-modals"
          style={{ width: '100%', minHeight: 500, border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff' }}
        />
      )}
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}
