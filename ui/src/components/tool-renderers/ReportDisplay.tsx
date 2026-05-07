import { useEffect, useRef, useState } from 'react'
import { Button } from 'antd'
import { FileTextOutlined, EyeOutlined, PrinterOutlined, ExportOutlined, DownloadOutlined } from '@ant-design/icons'
import { FileViewerModal, rewriteRelativeUrls } from '../FilePreview'
import { API } from '../../api'

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
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [viewerFile, setViewerFile] = useState<{ name: string; path: string } | null>(null)
  const htmlPath = data.html_path || data.path
  const name = htmlPath?.split('/').pop() || 'report.html'
  const dirPath = htmlPath ? htmlPath.substring(0, htmlPath.lastIndexOf('/')) : undefined

  useEffect(() => {
    if (!htmlPath) return

    const url = `${API}/workspace/files?path=${encodeURIComponent(htmlPath)}`
    fetch(url)
      .then(r => r.ok ? r.text() : Promise.reject('Not found'))
      .then(html => {
        const resolved = dirPath ? rewriteRelativeUrls(html, dirPath) : html
        // Inject @page rule to suppress browser print headers/footers by default
        const printStyle = '<style>@page { margin: 1cm; }</style>'
        const withPrintStyle = resolved.includes('</head>')
          ? resolved.replace('</head>', printStyle + '</head>')
          : printStyle + resolved
        const blob = new Blob([withPrintStyle], { type: 'text/html' })
        setBlobUrl(URL.createObjectURL(blob))
      })
      .catch(() => setBlobUrl(null))

    return () => setBlobUrl(prev => { if (prev) URL.revokeObjectURL(prev); return null })
  }, [htmlPath])

  const handleView = () => {
    if (!htmlPath) return
    if (onFileClick) onFileClick(htmlPath)
    else setViewerFile({ name, path: htmlPath })
  }

  const handlePrint = () => {
    iframeRef.current?.contentWindow?.print()
  }

  const handleOpenNewTab = () => {
    if (!htmlPath) return
    window.open(`${API}/workspace/files?path=${encodeURIComponent(htmlPath)}`, '_blank')
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
      {blobUrl && (
        <iframe
          ref={iframeRef}
          src={blobUrl}
          style={{ width: '100%', minHeight: 500, border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff' }}
        />
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
