import { useState } from 'react'
import { Button, Tag, Input, message } from 'antd'
import { CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, StopOutlined } from '@ant-design/icons'
import { API } from '../../api'

interface Step {
  name: string
  description?: string
  status?: string
  summary?: string
  outputs?: string[]
}

interface Plan {
  id?: string
  name?: string
  description?: string
  status?: string
  steps?: Step[]
  progress_summary?: string
  mlflow_experiment_id?: string
}

interface PlanData {
  proposal_id?: string
  status?: string
  plan?: Plan
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'orange', approved: 'blue', running: 'processing',
  completed: 'green', denied: 'red', changes_requested: 'purple',
}

export default function PlanDisplay({ data, onFileClick, onDecision }: {
  data: PlanData
  onFileClick?: (path: string) => void
  onDecision?: (proposalId: string, status: string, feedback?: string) => void
}) {
  const plan = data.plan
  const proposalId = data.proposal_id
  const [currentStatus, setCurrentStatus] = useState(data.status || plan?.status || '')
  const [decided, setDecided] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')

  if (!plan) return <pre style={{ fontSize: 11 }}>{JSON.stringify(data, null, 2)}</pre>

  const submitDecision = async (status: string, feedback: string = '') => {
    if (!proposalId) return
    if (onDecision) {
      onDecision(proposalId, status, feedback)
      setCurrentStatus(status)
      setDecided(true)
      setShowFeedback(false)
      setFeedbackText('')
      return
    }
    try {
      const res = await fetch(`${API}/plans/${proposalId}/decision`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, feedback }),
      })
      if (res.ok) {
        setCurrentStatus(status)
        setDecided(true)
        setShowFeedback(false)
        setFeedbackText('')
        message.success(`Plan ${status === 'approved' ? 'approved' : status === 'denied' ? 'denied' : 'feedback sent'}`)
      } else {
        message.error('Failed to submit decision')
      }
    } catch {
      message.error('Failed to submit decision')
    }
  }

  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{plan.name}</span>
        <Tag color={STATUS_COLORS[currentStatus] || 'default'} style={{ fontSize: 10 }}>
          {currentStatus}
        </Tag>
      </div>
      {plan.description && <div style={{ color: '#555', marginBottom: 8, lineHeight: 1.5 }}>{plan.description}</div>}
      {plan.steps?.map((step, i) => (
        <div key={i} style={{ padding: '3px 0', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'flex-start', gap: 6 }}>
          <span style={{ flexShrink: 0, marginTop: 2 }}><StepIcon status={step.status} /></span>
          <div>
            <span style={{ fontWeight: 500 }}>{step.name}</span>
            {step.description && <div style={{ color: '#888', fontSize: 11 }}>{step.description}</div>}
            {step.summary && <div style={{ color: '#555', fontSize: 11, marginTop: 2 }}>{step.summary}</div>}
            {step.outputs && step.outputs.length > 0 && (
              <div style={{ marginTop: 2, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {step.outputs.map((p, j) => (
                  <span key={j} onClick={() => onFileClick?.(p)} style={{
                    cursor: onFileClick ? 'pointer' : 'default', color: '#1677ff', fontSize: 10,
                    background: '#f0f5ff', padding: '1px 6px', borderRadius: 3,
                  }}>{p.split('/').pop()}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
      {plan.progress_summary && (
        <div style={{ marginTop: 8, padding: 6, background: '#f0f5ff', borderRadius: 4, fontSize: 11 }}>{plan.progress_summary}</div>
      )}
      {plan.mlflow_experiment_id && (
        <div style={{ marginTop: 6, fontSize: 10, color: '#888' }}>
          MLflow Experiment: <span style={{ fontFamily: 'monospace' }}>{plan.mlflow_experiment_id}</span>
        </div>
      )}

      {/* Decision buttons */}
      {currentStatus === 'pending' && !decided && proposalId && (
        <div style={{ marginTop: 10 }}>
          {showFeedback ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Input.TextArea value={feedbackText} onChange={e => setFeedbackText(e.target.value)}
                rows={2} placeholder="Describe what should be changed..." style={{ fontSize: 12 }} />
              <div style={{ display: 'flex', gap: 6 }}>
                <Button size="small" type="primary" onClick={() => submitDecision('changes_requested', feedbackText)}
                  disabled={!feedbackText.trim()}>Submit Feedback</Button>
                <Button size="small" onClick={() => { setShowFeedback(false); setFeedbackText('') }}>Cancel</Button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 6 }}>
              <Button size="small" type="primary" onClick={() => submitDecision('approved')}>Approve</Button>
              <Button size="small" onClick={() => setShowFeedback(true)}>Suggest Edits</Button>
              <Button size="small" danger onClick={() => submitDecision('denied')}>Deny</Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StepIcon({ status }: { status?: string }) {
  if (status === 'completed') return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
  if (status === 'in_progress') return <ClockCircleOutlined style={{ color: '#1677ff', fontSize: 12 }} />
  if (status === 'error') return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 12 }} />
  if (status === 'blocked') return <StopOutlined style={{ color: '#faad14', fontSize: 12 }} />
  return <span style={{ width: 12, height: 12, borderRadius: '50%', border: '1px solid #d9d9d9', display: 'inline-block' }} />
}
