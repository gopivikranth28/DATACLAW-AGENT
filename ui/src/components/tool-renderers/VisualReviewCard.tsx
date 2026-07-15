import { Alert, Image, Tag } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { API } from '../../api'
import { toolErrorMessage } from '../reportPublishState'
import type { RuntimeSmoke } from './ReportTrustStrip'

/**
 * Renders a report_review_visuals result: the reviewer decision bound to the
 * exact screenshots it covers, shown inline so the capture → inspect →
 * approve loop is usable from chat without hunting for the review directory.
 */

interface Screenshot {
  path?: string
  kind?: 'full_page' | 'key_section' | string
  viewport?: string
  section?: string
  sha256?: string
}

interface SemanticVisual {
  status?: 'pass' | 'attention_required' | string
  findings?: { id?: string; detail?: string; section?: string }[]
}

interface VisualReviewResult {
  type?: string
  decision?: 'approved' | 'rework_required' | string
  reviewer?: string
  approved?: boolean
  capture_reused?: boolean
  review_path?: string
  runtime_smoke?: RuntimeSmoke & { screenshots?: Screenshot[]; semantic_visual?: SemanticVisual }
  error?: unknown
}

export default function VisualReviewCard({ data, status }: { data: VisualReviewResult; status?: string }) {
  const errorMessage = toolErrorMessage(data)
  if (status === 'error' || errorMessage) {
    return (
      <Alert
        showIcon
        type="error"
        message="Visual review not recorded"
        description={errorMessage || 'The review call failed; capture screenshots and record the decision again.'}
        style={{ borderRadius: 8 }}
      />
    )
  }

  const smoke = data.runtime_smoke || {}
  const screenshots = (smoke.screenshots || []).filter(shot => shot?.path)
  const ordered = [
    ...screenshots.filter(shot => shot.kind === 'full_page'),
    ...screenshots.filter(shot => shot.kind !== 'full_page'),
  ]
  const semantic = smoke.semantic_visual
  const semanticFindings = semantic?.findings?.filter(finding => finding?.detail || finding?.id) || []
  const decisionTag = data.decision === 'approved'
    ? { label: `Approved${data.reviewer ? ` · ${data.reviewer}` : ''}`, color: 'success' }
    : { label: `Rework required${data.reviewer ? ` · ${data.reviewer}` : ''}`, color: 'gold' }

  return (
    <div data-testid="visual-review-card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <EyeOutlined style={{ color: '#1677ff', fontSize: 14 }} />
        <span style={{ fontWeight: 500 }}>Visual review</span>
        <Tag color={decisionTag.color} style={{ marginInlineEnd: 0 }}>{decisionTag.label}</Tag>
        <Tag color={data.capture_reused ? 'blue' : 'default'} style={{ marginInlineEnd: 0 }}>
          {data.capture_reused ? 'Bound to inspected capture' : 'Fresh capture'}
        </Tag>
        {semantic?.status && (
          <Tag color={semantic.status === 'pass' ? 'success' : 'gold'} style={{ marginInlineEnd: 0 }}>
            {semantic.status === 'pass' ? 'Semantic review passed' : 'Semantic review: attention required'}
          </Tag>
        )}
      </div>
      {smoke.status === 'skipped' && (
        <Alert
          showIcon
          type="warning"
          style={{ marginBottom: 8 }}
          message="No browser evidence"
          description={smoke.reason || 'The browser was unavailable, so no screenshots were captured for this review.'}
        />
      )}
      {smoke.status === 'failed' && (smoke.checks?.length || 0) > 0 && (
        <Alert
          showIcon
          type="error"
          style={{ marginBottom: 8 }}
          message={`Browser checks failed (${smoke.checks!.length})`}
          description={
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {smoke.checks!.map((check, index) => (
                <li key={`${check.check || 'check'}-${index}`}>{[check.check, check.detail].filter(Boolean).join(' — ')}</li>
              ))}
            </ul>
          }
        />
      )}
      {semanticFindings.length > 0 && (
        <ul style={{ margin: '0 0 8px', paddingLeft: 18, fontSize: 12, color: '#667085' }}>
          {semanticFindings.map((finding, index) => (
            <li key={`${finding.id || 'semantic'}-${index}`}>{[finding.id, finding.detail].filter(Boolean).join(' — ')}</li>
          ))}
        </ul>
      )}
      {ordered.length > 0 && (
        <Image.PreviewGroup>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {ordered.map((shot, index) => (
              <figure key={`${shot.sha256 || shot.path}-${index}`} style={{ margin: 0, width: 168 }}>
                <Image
                  data-testid="visual-review-screenshot"
                  src={`${API}/workspace/files?path=${encodeURIComponent(shot.path!)}`}
                  alt={screenshotLabel(shot)}
                  width={168}
                  style={{ borderRadius: 6, border: '1px solid #f0f0f0', objectFit: 'cover' }}
                />
                <figcaption style={{ fontSize: 11, color: '#98a2b3', marginTop: 2 }}>{screenshotLabel(shot)}</figcaption>
              </figure>
            ))}
          </div>
        </Image.PreviewGroup>
      )}
    </div>
  )
}

function screenshotLabel(shot: Screenshot): string {
  const kind = shot.kind === 'full_page' ? 'Full page' : shot.kind === 'key_section' ? 'Key section' : 'Screenshot'
  const scope = shot.section || shot.viewport || ''
  return scope ? `${kind} · ${scope}` : kind
}
