import { Tag } from 'antd'

export interface DecisionAnswer {
  id: string
  kind?: 'choice' | 'score' | 'boolean' | null
  answer: string | number | boolean
  confidence: number
  probabilities?: Record<string, number> | null
  calibrated?: boolean
  below_min_confidence?: boolean
}

export interface DecisionData {
  success?: boolean
  backend?: string
  model?: string | null
  fallback_reason?: string | null
  min_confidence?: number
  answers?: DecisionAnswer[]
  error?: { code?: string; message?: string }
}

const MAX_BARS = 4

function percent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function formatAnswer(answer: DecisionAnswer): string {
  if (typeof answer.answer === 'boolean') return answer.answer ? 'Yes' : 'No'
  if (typeof answer.answer === 'number') return answer.kind === 'score' ? `Level ${answer.answer.toFixed(1)}` : String(answer.answer)
  return answer.answer
}

/** Compact card for a `decide` tool result: one row per question. */
export default function DecisionCard({ data }: { data: DecisionData }) {
  if (data.success === false) {
    return <div style={{ fontSize: 12, color: '#b42318' }}>Decision failed: {data.error?.message || data.error?.code || 'unknown error'}</div>
  }
  const answers = data.answers || []
  return (
    <div style={{ border: '1px solid #e8e8e8', borderRadius: 8, padding: '8px 10px', background: '#fcfcfc', fontSize: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 6, color: '#667085' }}>
        <span>Decision</span>
        {data.backend && <Tag style={{ marginInlineEnd: 0 }}>{data.backend === 'typesafe' ? 'TypeSafe Jev' : data.backend === 'llm' ? 'Utility LLM' : data.backend}</Tag>}
        {data.model && <span style={{ color: '#98a2b3' }}>{data.model}</span>}
      </div>
      {data.fallback_reason && (
        <div style={{ color: '#ad6800', marginBottom: 6 }}>Fallback: {data.fallback_reason}</div>
      )}
      {answers.map(answer => {
        const bars = Object.entries(answer.probabilities || {})
          .sort((a, b) => b[1] - a[1])
          .slice(0, MAX_BARS)
        return (
          <div key={answer.id} style={{ padding: '4px 0', borderTop: '1px solid #f0f0f0' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ color: '#667085' }}>{answer.id}</span>
              <b>{formatAnswer(answer)}</b>
              <span style={{ color: answer.below_min_confidence ? '#ad6800' : '#667085' }}>
                {percent(answer.confidence)} {answer.calibrated === false ? 'self-reported' : 'confidence'}
              </span>
            </div>
            {bars.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(60px, max-content) 1fr 36px', gap: '2px 8px', alignItems: 'center', marginTop: 3 }}>
                {bars.map(([label, value]) => (
                  <div key={label} style={{ display: 'contents' }}>
                    <span style={{ color: '#667085', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
                    <div style={{ height: 6, background: '#f0f0f0', borderRadius: 3 }}>
                      <div style={{ width: percent(Math.min(Math.max(value, 0), 1)), height: '100%', background: '#2468e5', borderRadius: 3 }} />
                    </div>
                    <span style={{ color: '#98a2b3', textAlign: 'right' }}>{percent(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
