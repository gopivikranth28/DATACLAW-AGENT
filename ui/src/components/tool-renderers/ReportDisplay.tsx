import { Alert, Button, Tag } from 'antd'
import { FileTextOutlined, EyeOutlined, PrinterOutlined, ExportOutlined, DownloadOutlined } from '@ant-design/icons'
import { API } from '../../api'
import { reportDocumentUrl, reportPreviewUrl } from '../reportPreview'

interface ReportData {
  html_path?: string
  docx_path?: string
  size?: number
  created?: boolean
  publication_status?: 'draft' | 'designed' | 'published'
  publish_required?: boolean
  design_review?: DesignReview
  analytical_review?: AnalyticalReview
  // legacy fields from old PDF-based tool
  path?: string
  format?: string
}

interface AnalyticalReviewFinding {
  id?: string
  severity?: 'required' | 'warning' | 'info' | string
  claim?: string
  recommendation?: string
  review_finding_id?: string
  lifecycle_status?: 'open' | 'resolved' | 'accepted_with_rationale' | 'dismissed_as_not_applicable' | string
}

interface AnalyticalReview {
  status?: 'pass' | 'attention_required' | string
  findings?: AnalyticalReviewFinding[]
}

interface DesignReviewFinding {
  id?: string
  severity?: 'warning' | 'info' | string
  claim?: string
  recommendation?: string
  sections?: string[]
}

interface DesignReview {
  status?: 'pass' | 'attention_required' | string
  findings?: DesignReviewFinding[]
  passes?: number
}

export default function ReportDisplay({ data, onFileClick }: {
  data: ReportData
  onFileClick?: (path: string) => void
}) {
  const htmlPath = data.html_path || data.path
  const name = htmlPath?.split('/').pop() || 'report.html'
  const previewUrl = htmlPath ? reportPreviewUrl(htmlPath) : ''
  const documentUrl = htmlPath ? reportDocumentUrl(htmlPath, data.size !== undefined ? String(data.size) : undefined) : ''
  const publication = publicationLabel(data)
  const reviewFindings = data.analytical_review?.findings || []
  const acceptedFindings = reviewFindings.filter(finding => finding.lifecycle_status === 'accepted_with_rationale')
  const requiredFindings = reviewFindings.filter(
    finding => finding.severity === 'required' && finding.lifecycle_status !== 'accepted_with_rationale',
  )
  const warningFindings = reviewFindings.filter(finding => finding.severity === 'warning')
  const designFindings = data.design_review?.findings || []
  const designWarnings = designFindings.filter(finding => finding.severity === 'warning')

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
        {publication && <Tag color={publication.color}>{publication.label}</Tag>}
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
      {reviewFindings.length > 0 && (
        <Alert
          showIcon
          type={requiredFindings.length > 0 ? 'error' : 'warning'}
          style={{ marginBottom: 12 }}
          message={`Analytical review: ${requiredFindings.length} required, ${warningFindings.length} warning${warningFindings.length === 1 ? '' : 's'}${acceptedFindings.length ? `, ${acceptedFindings.length} accepted risk${acceptedFindings.length === 1 ? '' : 's'}` : ''}`}
          description={
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {reviewFindings.map((finding, index) => (
                <li key={`${finding.id || 'finding'}-${index}`}>
                  {finding.claim || finding.id || 'Review finding'}
                  {finding.recommendation ? ` ${finding.recommendation}` : ''}
                  {finding.lifecycle_status === 'accepted_with_rationale' ? ' (accepted risk)' : ''}
                </li>
              ))}
            </ul>
          }
        />
      )}
      {designFindings.length > 0 && (
        <Alert
          showIcon
          type={designWarnings.length > 0 ? 'warning' : 'info'}
          style={{ marginBottom: 12 }}
          message={`Design critique: ${designWarnings.length} architecture warning${designWarnings.length === 1 ? '' : 's'}${data.design_review?.passes ? ` · ${data.design_review.passes} passes` : ''}`}
          description={
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {designFindings.map((finding, index) => (
                <li key={`${finding.id || 'design-finding'}-${index}`}>
                  {finding.claim || finding.id || 'Design finding'}
                  {finding.recommendation ? ` ${finding.recommendation}` : ''}
                </li>
              ))}
            </ul>
          }
        />
      )}
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

function publicationLabel(data: ReportData): { label: string; color: string } | null {
  if (data.publication_status === 'published') return { label: 'Published', color: 'success' }
  if (data.publication_status === 'designed') return { label: 'Designed · publish required', color: 'processing' }
  if (data.publication_status === 'draft' || data.publish_required) return { label: 'Draft · publish required', color: 'warning' }
  return null
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}
