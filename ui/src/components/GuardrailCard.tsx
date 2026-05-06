import { useState } from 'react'
import {
  SafetyOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import type { GuardrailState } from '../hooks/useAGUI'
import { API } from '../api'

interface Props {
  guardrail: GuardrailState
  threadId: string
}

const SEVERITY_COLORS: Record<string, { border: string; bg: string; icon: string }> = {
  info: { border: '#91caff', bg: '#f0f5ff', icon: '#1677ff' },
  warning: { border: '#ffd591', bg: '#fffbe6', icon: '#faad14' },
  danger: { border: '#ffa39e', bg: '#fff2f0', icon: '#ff4d4f' },
}

export default function GuardrailCard({ guardrail, threadId }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const colors = SEVERITY_COLORS[guardrail.severity] || SEVERITY_COLORS.warning

  const statusLabel =
    guardrail.status === 'pending' ? 'Awaiting your decision' :
    guardrail.status === 'approved' ? 'Approved' :
    guardrail.status === 'denied' ? 'Denied' :
    guardrail.status === 'auto_replied' ? 'Auto-blocked' :
    guardrail.status === 'post_intervention' ? 'Redacted' :
    guardrail.status

  const statusIcon =
    guardrail.status === 'pending' ? <LoadingOutlined style={{ color: colors.icon, fontSize: 13 }} spin /> :
    guardrail.status === 'approved' ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} /> :
    guardrail.status === 'denied' ? <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} /> :
    guardrail.status === 'post_intervention' ? <WarningOutlined style={{ color: colors.icon, fontSize: 13 }} /> :
    <InfoCircleOutlined style={{ color: colors.icon, fontSize: 13 }} />

  const handleDecision = async (approved: boolean) => {
    if (!guardrail.approvalId) return
    setSubmitting(true)
    try {
      await fetch(`${API}/agent/guardrail/${threadId}/${guardrail.approvalId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved }),
      })
    } catch {
      /* ignore — the loop will time out and auto-deny */
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div style={{
      margin: '6px 0',
      borderRadius: 8,
      border: `1px solid ${colors.border}`,
      borderLeft: `4px solid ${colors.border}`,
      background: colors.bg,
      overflow: 'hidden',
      fontSize: 13,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
      }}>
        <SafetyOutlined style={{ color: colors.icon, fontSize: 14 }} />
        {statusIcon}
        <span style={{ fontWeight: 500, color: '#333' }}>
          Guardrail: {guardrail.guardrailId.replace(/_/g, ' ')}
        </span>
        <span style={{
          fontSize: 11,
          padding: '1px 6px',
          borderRadius: 4,
          background: 'rgba(0,0,0,0.06)',
          color: '#666',
          marginLeft: 'auto',
        }}>
          {statusLabel}
        </span>
      </div>

      {/* Message */}
      <div style={{
        padding: '4px 12px 10px 12px',
        color: '#555',
        lineHeight: 1.5,
      }}>
        {guardrail.message}
      </div>

      {/* Approve / Deny buttons for user_approval mode */}
      {guardrail.mode === 'user_approval' && guardrail.status === 'pending' && (
        <div style={{
          display: 'flex',
          gap: 8,
          padding: '0 12px 10px 12px',
        }}>
          <button
            disabled={submitting}
            onClick={() => handleDecision(true)}
            style={{
              padding: '4px 16px',
              borderRadius: 6,
              border: '1px solid #52c41a',
              background: '#f6ffed',
              color: '#389e0d',
              cursor: submitting ? 'not-allowed' : 'pointer',
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            Approve
          </button>
          <button
            disabled={submitting}
            onClick={() => handleDecision(false)}
            style={{
              padding: '4px 16px',
              borderRadius: 6,
              border: '1px solid #ff4d4f',
              background: '#fff2f0',
              color: '#cf1322',
              cursor: submitting ? 'not-allowed' : 'pointer',
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            Deny
          </button>
        </div>
      )}
    </div>
  )
}
