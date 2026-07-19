import { useState, useEffect } from 'react'
import { LoadingOutlined, CheckCircleOutlined, ExclamationCircleOutlined, RightOutlined, TeamOutlined, CodeOutlined } from '@ant-design/icons'
import type { ToolCallState } from '../hooks/useAGUI'
import ToolResultRenderer, { hasCustomRenderer, shouldAutoExpand, shouldRenderWhileCalling } from './tool-renderers/ToolResultRenderer'
import SubagentProgressPanel from './SubagentProgressPanel'
import { hasToolError, toolBaseName } from './reportPublishState'

interface Props {
  toolCall: ToolCallState
  onFileClick?: (path: string) => void
  sessionId?: string | null
}

export default function ToolCallCard({ toolCall, onFileClick, sessionId }: Props) {
  const isDelegate = toolCall.name === 'delegate_to_subagent'
  const hasSubagent = isDelegate && !!toolCall.subagent
  const failed = toolCall.status === 'error' || hasToolError(toolCall.result)
  const canRenderWhileCalling = shouldRenderWhileCalling(toolCall.name)
  const autoExpand = hasSubagent || (shouldAutoExpand(toolCall.name) && (
    (toolCall.status === 'complete' && toolCall.result !== null) || canRenderWhileCalling
  ))
  const [expanded, setExpanded] = useState(autoExpand)

  // Auto-expand when a tool that should be expanded completes
  useEffect(() => {
    if (autoExpand) setExpanded(true)
  }, [autoExpand])

  const statusIcon = toolCall.status === 'calling'
    ? <LoadingOutlined style={{ color: '#1677ff', fontSize: 13 }} spin />
    : failed
      ? <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: 13 }} />
      : <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 13 }} />

  const hasRichRenderer = hasCustomRenderer(toolCall.name)

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
        <span style={{ fontWeight: 500, color: '#333' }}>
          {isDelegate
            ? <>{hasSubagent ? toolCall.subagent!.name : (safeParseField(toolCall.args, 'subagent_name') || 'unknown')} <span style={{ fontWeight: 400, color: '#999', fontSize: 12 }}>(<TeamOutlined style={{ fontSize: 11 }} /> subagent)</span></>
            : toolLabel(toolCall.name)}
        </span>
        {hasSubagent && (
          <span style={{ fontSize: 11, padding: '1px 6px', borderRadius: 4, background: '#f0f0f0', color: '#666' }}>
            {toolCall.subagent!.agentType}
          </span>
        )}
        {toolCall.status === 'calling' && !hasSubagent && (
          <span style={{ color: '#999', fontSize: 12, marginLeft: 'auto' }}>running...</span>
        )}
      </div>

      {/* Expanded details — use display:none instead of unmount to preserve child state */}
      <div style={{ display: expanded ? 'block' : 'none' }}>
        <div style={{ borderTop: '1px solid #eee', padding: '10px 12px' }}>
          {/* Subagent: live progress while running, friendly result when complete */}
          {isDelegate ? (
            hasSubagent && toolCall.status === 'calling' ? (
              <SubagentProgressPanel
                progress={toolCall.subagent!}
                maxTurns={parseMaxTurns(toolCall.args)}
              />
            ) : (
              <DelegateResultView args={toolCall.args} result={toolCall.result} status={toolCall.status} />
            )
          ) : (
            <>
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
              {(toolCall.result !== null || canRenderWhileCalling) && (
                <div>
                  {!hasRichRenderer && (
                    <div style={{ fontSize: 11, color: '#888', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                      Result
                    </div>
                  )}
                  <ToolResultRenderer toolName={toolCall.name} result={toolCall.result} args={toolCall.args}
                    status={toolCall.status} onFileClick={onFileClick} sessionId={sessionId} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function toolLabel(toolName: string): string {
  const labels: Record<string, string> = {
    report_add_section: 'Report update',
    report_design_report: 'Design report',
    build_report: 'Report',
    report_publish: 'Publish report',
    propose_plan: 'Plan proposal',
    update_plan: 'Plan update',
  }
  const normalized = toolBaseName(toolName)
  return labels[normalized] || normalized
}

/** Friendly display for a completed delegate_to_subagent call.
 *  Renders the full subagent conversation from metadata.messages,
 *  with a toggle to show raw JSON. */
function DelegateResultView({ args, result, status }: { args: string; result: string | null; status: string }) {
  const [showRaw, setShowRaw] = useState(false)
  const conversation = parseConversation(result)
  const turnsUsed = safeParseField(result, 'turns_used')

  // Fallback: if no conversation could be parsed, show task + result text
  if (conversation.length === 0 && status !== 'calling') {
    const task = safeParseField(args, 'task')
    const resultText = safeParseField(result, 'result')
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {showRaw ? (
          <RawJsonView args={args} result={result} />
        ) : (
          <>
            {task && <UserBubble text={task} />}
            {resultText && <AssistantBubble text={resultText} />}
          </>
        )}
        {(args || result) && <RawJsonToggle showRaw={showRaw} setShowRaw={setShowRaw} args={args} result={result} />}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {status === 'calling' && conversation.length === 0 ? (
        <div style={{ fontSize: 11, color: '#999' }}>
          <LoadingOutlined spin style={{ fontSize: 10, marginRight: 4 }} />
          Working...
        </div>
      ) : (
        <>
          {showRaw ? (
            <RawJsonView args={args} result={result} />
          ) : (
            conversation.map((entry, i) => (
              <ConversationEntry key={i} entry={entry} />
            ))
          )}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            {turnsUsed && status === 'complete' && (
              <div style={{ fontSize: 11, color: '#bbb' }}>
                {turnsUsed} turn{turnsUsed !== '1' ? 's' : ''}
              </div>
            )}
            <RawJsonToggle showRaw={showRaw} setShowRaw={setShowRaw} args={args} result={result} />
          </div>
        </>
      )}
    </div>
  )
}

function RawJsonToggle({ showRaw, setShowRaw }: { showRaw: boolean; setShowRaw: (v: boolean) => void; args: string; result: string | null }) {
  return (
    <div
      onClick={() => setShowRaw(!showRaw)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 11, color: showRaw ? '#1677ff' : '#bbb', cursor: 'pointer',
        userSelect: 'none', marginLeft: 'auto',
      }}
    >
      <CodeOutlined style={{ fontSize: 11 }} />
      {showRaw ? 'Hide JSON' : 'JSON'}
    </div>
  )
}

function RawJsonView({ args, result }: { args: string; result: string | null }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {args && (
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Arguments</div>
          <pre style={{
            background: '#f5f5f5', padding: '8px 10px', borderRadius: 6,
            fontSize: 11, overflowX: 'auto', whiteSpace: 'pre-wrap',
            wordBreak: 'break-word', margin: 0, maxHeight: 200, overflow: 'auto',
          }}>{formatJSON(args)}</pre>
        </div>
      )}
      {result && (
        <div>
          <div style={{ fontSize: 11, color: '#888', marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Result</div>
          <pre style={{
            background: '#f5f5f5', padding: '8px 10px', borderRadius: 6,
            fontSize: 11, overflowX: 'auto', whiteSpace: 'pre-wrap',
            wordBreak: 'break-word', margin: 0, maxHeight: 300, overflow: 'auto',
          }}>{formatJSON(result)}</pre>
        </div>
      )}
    </div>
  )
}

interface ConvEntry {
  type: 'user' | 'assistant' | 'tool_call'
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
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, paddingLeft: 8 }}>
          {entry.isError
            ? <ExclamationCircleOutlined style={{ fontSize: 9, color: '#ff4d4f' }} />
            : <CheckCircleOutlined style={{ fontSize: 9, color: '#52c41a' }} />
          }
          <span style={{ fontFamily: 'monospace', color: '#555' }}>{entry.toolName}</span>
          {entry.toolInput && Object.keys(entry.toolInput).length > 0 && (
            <span style={{ color: '#aaa' }}>— {summarizeToolInput(entry.toolInput)}</span>
          )}
        </div>
      )
    default:
      return null
  }
}

function UserBubble({ text }: { text: string }) {
  return (
    <div style={{
      background: '#e8eeff', borderRadius: '12px 12px 12px 4px',
      padding: '6px 10px', fontSize: 12, color: '#333', maxWidth: '85%',
    }}>
      {text}
    </div>
  )
}

function AssistantBubble({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div style={{
      background: '#f5f5f5', borderRadius: '12px 12px 4px 12px',
      padding: '6px 10px', fontSize: 12, color: '#444',
      maxWidth: '85%', marginLeft: 'auto', whiteSpace: 'pre-wrap',
    }}>
      {text}
      {streaming && <span style={{ color: '#1677ff' }}>▊</span>}
    </div>
  )
}

/** Parse the full conversation from metadata.messages into display entries. */
function parseConversation(resultStr: string | null): ConvEntry[] {
  if (!resultStr) return []
  try {
    const parsed = JSON.parse(resultStr)
    const messages: any[] = parsed.metadata?.messages || []
    const entries: ConvEntry[] = []

    // Build set of errored tool call IDs
    const errorCallIds = new Set<string>()
    for (const msg of messages) {
      if (!Array.isArray(msg.content)) continue
      for (const part of msg.content) {
        if (part.type === 'tool_result' && part.is_error) errorCallIds.add(part.call_id)
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
              isError: errorCallIds.has(part.id),
            })
          } else if (part.type === 'text' && part.text) {
            entries.push({ type: 'assistant', text: part.text })
          }
        }
      }
    }
    return entries
  } catch {
    return []
  }
}

function safeParseField(jsonStr: string | null, field: string): string | null {
  if (!jsonStr) return null
  try {
    const val = JSON.parse(jsonStr)[field]
    return val != null ? String(val) : null
  } catch {
    return null
  }
}

function summarizeToolInput(input: Record<string, any>): string {
  const first = Object.values(input)[0]
  if (typeof first === 'string') {
    return first.length > 40 ? `"${first.slice(0, 40)}..."` : `"${first}"`
  }
  return JSON.stringify(first).slice(0, 40)
}

function parseMaxTurns(argsStr: string): number | undefined {
  try {
    const args = JSON.parse(argsStr)
    return args.max_turns || undefined
  } catch {
    return undefined
  }
}

function formatJSON(str: string): string {
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}
