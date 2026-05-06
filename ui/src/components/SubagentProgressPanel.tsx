import { LoadingOutlined, CheckCircleOutlined, ExclamationCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import type { SubagentProgress } from '../hooks/useAGUI'

interface Props {
  progress: SubagentProgress
  maxTurns?: number
}

export default function SubagentProgressPanel({ progress, maxTurns }: Props) {
  const isRunning = progress.status === 'running'
  const statusColor = isRunning ? '#1677ff' : progress.status === 'completed' ? '#52c41a' : '#faad14'

  // Group tool calls by turn
  const turnGroups = new Map<number, typeof progress.toolCalls>()
  for (const tc of progress.toolCalls) {
    const turn = tc.turn || 1
    if (!turnGroups.has(turn)) turnGroups.set(turn, [])
    turnGroups.get(turn)!.push(tc)
  }

  const streamingText = progress.textChunks.join('')

  return (
    <div style={{ padding: '8px 0' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        {isRunning
          ? <LoadingOutlined style={{ color: statusColor, fontSize: 13 }} spin />
          : <CheckCircleOutlined style={{ color: statusColor, fontSize: 13 }} />
        }
        <span style={{ fontWeight: 500, fontSize: 13 }}>{progress.name}</span>
        <span style={{
          fontSize: 11, padding: '1px 6px', borderRadius: 4,
          background: '#f0f0f0', color: '#666',
        }}>
          {progress.agentType}
        </span>
        {maxTurns && (
          <span style={{ fontSize: 12, color: '#999', marginLeft: 'auto' }}>
            Turn {progress.currentTurn} / {maxTurns}
          </span>
        )}
      </div>

      {/* Task */}
      <div style={{ fontSize: 12, color: '#666', marginBottom: 8, fontStyle: 'italic' }}>
        {progress.task}
      </div>

      {/* Turn log */}
      {turnGroups.size > 0 && (
        <div style={{
          borderLeft: '2px solid #e8e8e8',
          paddingLeft: 12,
          marginLeft: 6,
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
        }}>
          {Array.from(turnGroups.entries()).map(([turn, tcs]) => (
            <div key={turn}>
              <div style={{ fontSize: 11, color: '#999', fontWeight: 500, marginBottom: 3 }}>
                Turn {turn}
              </div>
              {tcs.map((tc, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, paddingLeft: 8 }}>
                  <ToolCallStatusIcon status={tc.status} />
                  <span style={{ color: '#333', fontFamily: 'monospace', fontSize: 11 }}>{tc.toolName}</span>
                  {tc.toolInput && Object.keys(tc.toolInput).length > 0 && (
                    <span style={{ color: '#999', fontSize: 11 }}>
                      — {summarizeInput(tc.toolInput)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Streaming text */}
      {streamingText && (
        <div style={{
          marginTop: 8,
          padding: '6px 10px',
          background: '#f9f9f9',
          borderRadius: 6,
          fontSize: 12,
          color: '#444',
          whiteSpace: 'pre-wrap',
          maxHeight: 120,
          overflow: 'auto',
        }}>
          {streamingText}
          {isRunning && <span style={{ color: '#1677ff' }}>▊</span>}
        </div>
      )}

      {/* Final status */}
      {!isRunning && (
        <div style={{ marginTop: 6, fontSize: 11, color: '#999' }}>
          {progress.status === 'completed' && `Completed in ${progress.currentTurn} turn${progress.currentTurn !== 1 ? 's' : ''}`}
          {progress.status === 'max_turns_reached' && `Reached max turns (${progress.currentTurn})`}
          {progress.status === 'error' && 'Subagent encountered an error'}
        </div>
      )}
    </div>
  )
}

function ToolCallStatusIcon({ status }: { status: string }) {
  if (status === 'calling') return <LoadingOutlined style={{ fontSize: 10, color: '#1677ff' }} spin />
  if (status === 'ok') return <CheckCircleOutlined style={{ fontSize: 10, color: '#52c41a' }} />
  if (status === 'error') return <ExclamationCircleOutlined style={{ fontSize: 10, color: '#ff4d4f' }} />
  return <ClockCircleOutlined style={{ fontSize: 10, color: '#999' }} />
}

function summarizeInput(input: Record<string, any>): string {
  const vals = Object.values(input)
  if (vals.length === 0) return ''
  const first = vals[0]
  if (typeof first === 'string') {
    return first.length > 50 ? `"${first.slice(0, 50)}..."` : `"${first}"`
  }
  return JSON.stringify(first).slice(0, 50)
}
