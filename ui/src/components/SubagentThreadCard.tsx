import { useState } from 'react'
import { RightOutlined, CheckCircleOutlined, LoadingOutlined, TeamOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import type { ToolCallState } from '../hooks/useAGUI'

interface Props {
  items: ToolCallState[]
}

export default function SubagentThreadCard({ items }: Props) {
  const [expanded, setExpanded] = useState(true)

  const firstSubagent = items.find(tc => tc.subagent)?.subagent
  const name = firstSubagent?.name || parseSubagentName(items[0]?.args)
  const isAnyRunning = items.some(tc => tc.status === 'calling')
  const exchangeCount = items.length

  // Build the full conversation from the latest completed result's metadata,
  // or from the last item's subagent progress if still running
  const latestCompleted = [...items].reverse().find(tc => tc.status === 'complete')
  const conversation = latestCompleted ? parseConversation(latestCompleted.result) : []

  // If there's a running item, append its live state
  const runningItem = items.find(tc => tc.status === 'calling')
  const liveTask = runningItem ? parseTask(runningItem.args) : null
  const liveToolCalls = runningItem?.subagent?.toolCalls || []
  const liveText = runningItem?.subagent?.textChunks?.join('') || ''
  const liveTurn = runningItem?.subagent?.currentTurn || 0

  return (
    <div style={{
      margin: '6px 0',
      borderRadius: 8,
      border: '1px solid #e0e0ff',
      background: '#fafaff',
      overflow: 'hidden',
      fontSize: 13,
    }}>
      {/* Header */}
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
          fontSize: 10, color: '#999',
          transition: 'transform 0.2s',
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
        }} />
        {isAnyRunning
          ? <LoadingOutlined style={{ color: '#1677ff', fontSize: 13 }} spin />
          : <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />
        }
        <span style={{ fontWeight: 500, color: '#333' }}>
          {name} <span style={{ fontWeight: 400, color: '#999', fontSize: 12 }}>(<TeamOutlined style={{ fontSize: 11 }} /> subagent)</span>
        </span>
        <span style={{ color: '#999', fontSize: 12, marginLeft: 'auto' }}>
          {exchangeCount} exchange{exchangeCount !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Full conversation view */}
      {expanded && (
        <div style={{ borderTop: '1px solid #e8e8ff', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Completed conversation entries */}
          {conversation.map((entry, i) => (
            <ConversationEntry key={i} entry={entry} />
          ))}

          {/* Live round (if running) */}
          {runningItem && (
            <>
              {liveTask && <UserBubble text={liveTask} />}
              {liveToolCalls.map((tc, i) => (
                <ToolCallLine key={i} name={tc.toolName} input={tc.toolInput} status={tc.status} />
              ))}
              {liveText ? (
                <AssistantBubble text={liveText} streaming />
              ) : (
                <div style={{ fontSize: 11, color: '#999', textAlign: 'right' }}>
                  <LoadingOutlined spin style={{ fontSize: 10, marginRight: 4 }} />
                  {liveTurn > 0 ? `Turn ${liveTurn}` : 'Working...'}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Conversation entry types ──────────────────────────────────────────────

interface ConvEntry {
  type: 'user' | 'assistant' | 'tool_call' | 'tool_result'
  text?: string
  toolName?: string
  toolInput?: Record<string, any>
  isError?: boolean
}

function ConversationEntry({ entry }: { entry: ConvEntry }) {
  switch (entry.type) {
    case 'user':
      return <UserBubble text={entry.text || ''} />
    case 'assistant':
      return <AssistantBubble text={entry.text || ''} />
    case 'tool_call':
      return <ToolCallLine name={entry.toolName || 'unknown'} input={entry.toolInput || {}} status={entry.isError ? 'error' : 'ok'} />
    default:
      return null
  }
}

function UserBubble({ text }: { text: string }) {
  return (
    <div style={{
      background: '#e8eeff',
      borderRadius: '12px 12px 12px 4px',
      padding: '6px 10px',
      fontSize: 12,
      color: '#333',
      maxWidth: '85%',
    }}>
      {text}
    </div>
  )
}

function AssistantBubble({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div style={{
      background: '#f5f5f5',
      borderRadius: '12px 12px 4px 12px',
      padding: '6px 10px',
      fontSize: 12,
      color: '#444',
      maxWidth: '85%',
      marginLeft: 'auto',
      whiteSpace: 'pre-wrap',
    }}>
      {text}
      {streaming && <span style={{ color: '#1677ff' }}>▊</span>}
    </div>
  )
}

function ToolCallLine({ name, input, status }: { name: string; input: Record<string, any>; status: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, paddingLeft: 8 }}>
      {status === 'calling'
        ? <LoadingOutlined style={{ fontSize: 9, color: '#1677ff' }} spin />
        : status === 'ok'
        ? <CheckCircleOutlined style={{ fontSize: 9, color: '#52c41a' }} />
        : <ExclamationCircleOutlined style={{ fontSize: 9, color: '#ff4d4f' }} />
      }
      <span style={{ fontFamily: 'monospace', color: '#555' }}>{name}</span>
      {input && Object.keys(input).length > 0 && (
        <span style={{ color: '#aaa' }}>— {summarizeInput(input)}</span>
      )}
    </div>
  )
}

// ── Parsing helpers ───────────────────────────────────────────────────────

/**
 * Parse the full conversation from a result's metadata.messages into
 * a flat list of display entries (user bubbles, tool calls, assistant bubbles).
 */
function parseConversation(resultStr: string | null): ConvEntry[] {
  if (!resultStr) return []
  try {
    const parsed = JSON.parse(resultStr)
    const messages: any[] = parsed.metadata?.messages || []
    const entries: ConvEntry[] = []

    // Build a map of tool call IDs to their error status from tool_result entries
    const toolResultErrors = new Set<string>()
    for (const msg of messages) {
      if (!Array.isArray(msg.content)) continue
      for (const part of msg.content) {
        if (part.type === 'tool_result' && part.is_error) {
          toolResultErrors.add(part.call_id)
        }
      }
    }

    for (const msg of messages) {
      if (msg.role === 'user' && typeof msg.content === 'string') {
        entries.push({ type: 'user', text: msg.content })
      } else if (msg.role === 'assistant' && typeof msg.content === 'string') {
        entries.push({ type: 'assistant', text: msg.content })
      } else if (msg.role === 'assistant' && Array.isArray(msg.content)) {
        for (const part of msg.content) {
          if (part.type === 'tool_call') {
            entries.push({
              type: 'tool_call',
              toolName: part.name,
              toolInput: part.input || {},
              isError: toolResultErrors.has(part.id),
            })
          } else if (part.type === 'text' && part.text) {
            entries.push({ type: 'assistant', text: part.text })
          }
        }
      }
      // Skip tool_result messages — they're represented by tool_call status
    }

    return entries
  } catch {
    return []
  }
}

function parseSubagentName(argsStr: string | undefined): string {
  if (!argsStr) return 'Subagent'
  try {
    return JSON.parse(argsStr).subagent_name || 'Subagent'
  } catch {
    return 'Subagent'
  }
}

function parseTask(argsStr: string): string | null {
  try {
    return JSON.parse(argsStr).task || null
  } catch {
    return null
  }
}

function summarizeInput(input: Record<string, any>): string {
  const first = Object.values(input)[0]
  if (typeof first === 'string') {
    return first.length > 40 ? `"${first.slice(0, 40)}..."` : `"${first}"`
  }
  return JSON.stringify(first).slice(0, 40)
}
