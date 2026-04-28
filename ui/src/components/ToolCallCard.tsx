import { useState } from 'react'
import { LoadingOutlined, CheckCircleOutlined, ExclamationCircleOutlined, RightOutlined } from '@ant-design/icons'
import type { ToolCallState } from '../hooks/useAGUI'
import ToolResultRenderer, { shouldAutoExpand } from './tool-renderers/ToolResultRenderer'

interface Props {
  toolCall: ToolCallState
  onFileClick?: (path: string) => void
  onDecision?: (proposalId: string, status: string, feedback?: string) => void
}

export default function ToolCallCard({ toolCall, onFileClick, onDecision }: Props) {
  const autoExpand = shouldAutoExpand(toolCall.name) && toolCall.status === 'complete' && toolCall.result !== null
  const [expanded, setExpanded] = useState(autoExpand)

  const statusIcon = toolCall.status === 'calling'
    ? <LoadingOutlined style={{ color: '#1677ff', fontSize: 13 }} spin />
    : toolCall.status === 'complete'
    ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />
    : <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} />

  const hasRichRenderer = shouldAutoExpand(toolCall.name)

  return (
    <div style={{
      margin: '6px 0',
      borderRadius: 8,
      border: '1px solid #eee',
      background: '#fafafa',
      overflow: 'hidden',
      fontSize: 13,
    }}>
      {/* Header — always visible */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <RightOutlined style={{
          fontSize: 10,
          color: '#999',
          transition: 'transform 0.2s',
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
        }} />
        {statusIcon}
        <span style={{ fontWeight: 500, color: '#333' }}>{toolCall.name}</span>
        {toolCall.status === 'calling' && (
          <span style={{ color: '#999', fontSize: 12, marginLeft: 'auto' }}>running...</span>
        )}
      </div>

      {/* Expanded details — use display:none instead of unmount to preserve child state */}
      <div style={{ display: expanded ? 'block' : 'none' }}>
        <div style={{ borderTop: '1px solid #eee', padding: '10px 12px' }}>
          {/* Arguments — show as collapsible for rich renderers, always for generic */}
          {toolCall.args && !hasRichRenderer && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, color: '#888', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Arguments
              </div>
              <pre style={{
                background: '#f5f5f5', padding: '8px 10px', borderRadius: 6,
                fontSize: 12, overflowX: 'auto', whiteSpace: 'pre-wrap',
                wordBreak: 'break-word', margin: 0,
              }}>
                {formatJSON(toolCall.args)}
              </pre>
            </div>
          )}
          {toolCall.result !== null && (
            <div>
              {!hasRichRenderer && (
                <div style={{ fontSize: 11, color: '#888', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Result
                </div>
              )}
              <ToolResultRenderer toolName={toolCall.name} result={toolCall.result} onFileClick={onFileClick} onDecision={onDecision} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function formatJSON(str: string): string {
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}
