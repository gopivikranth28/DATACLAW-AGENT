import { useState, useCallback, useEffect, useRef } from 'react'
import { Subscription } from 'rxjs'
import {
  runHttpRequest,
  transformHttpEventStream,
  transformChunks,
  EventType,
  type BaseEvent,
  type TextMessageStartEvent,
  type TextMessageContentEvent,
  type ToolCallStartEvent,
  type ToolCallArgsEvent,
  type ToolCallResultEvent,
  type RunErrorEvent,
  type MessagesSnapshotEvent,
  type CustomEvent as AGUICustomEvent,
  type StepStartedEvent,
  type Message,
} from '@ag-ui/client'
import { API } from '../api'

export interface AGUIMessage {
  id: string
  role: 'user' | 'assistant' | 'compaction' | 'run_notice'
  content: string
  order: number
  compactedCount?: number
  keptCount?: number
  stopReason?: string
  maxTurns?: number
  sentFromQueue?: boolean
  queuedAt?: number
}

export interface SubagentToolCallInfo {
  toolName: string
  toolInput: Record<string, any>
  status: 'calling' | 'ok' | 'error'
  turn: number
}

export interface SubagentProgress {
  name: string
  agentType: string
  task: string
  status: 'running' | 'completed' | 'max_turns_reached' | 'error'
  currentTurn: number
  toolCalls: SubagentToolCallInfo[]
  textChunks: string[]
  conversationId: string
}

export interface ToolCallState {
  id: string
  name: string
  args: string
  result: string | null
  status: 'calling' | 'complete' | 'error'
  order: number
  startedAt?: number
  finishedAt?: number
  subagent?: SubagentProgress | null
  conversationId?: string
  progress?: ToolProgress
}

export interface ToolProgress {
  phase: string
  label: string
  activity?: 'waiting' | 'receiving' | 'received' | string
  attempt?: number
  maxAttempts?: number
  elapsedMs?: number
  outputChars?: number
  lastOutputAt?: string
  emittedAt?: string
  heartbeat?: boolean
  timeoutSeconds?: number
  startedAt?: string
}

export interface RunHealth {
  running: boolean
  status: 'running' | 'finished' | 'error' | 'unknown'
  healthy: boolean
  task_status: 'running' | 'done' | 'cancelled' | 'unknown'
  run_id?: string
  cursor?: number
  started_at?: string
  last_event_at?: string
  last_progress_at?: string | null
  last_output_at?: string | null
  active_tool?: Record<string, unknown> | null
  server_time?: string
  reachable: boolean
  checkedAt: number
}

export interface GuardrailState {
  id: string
  guardrailId: string
  toolCallId: string
  message: string
  severity: 'info' | 'warning' | 'danger'
  mode: 'auto_reply' | 'user_approval'
  status: 'pending' | 'approved' | 'denied' | 'auto_replied' | 'post_intervention'
  approvalId?: string
  order: number
}

export type TimelineItem =
  | { type: 'message'; item: AGUIMessage }
  | { type: 'toolCall'; item: ToolCallState }
  | { type: 'guardrail'; item: GuardrailState }

interface AGUIState {
  messages: AGUIMessage[]
  toolCalls: ToolCallState[]
  guardrails: GuardrailState[]
  isRunning: boolean
  isStopping: boolean
  error: string | null
  reconnecting: boolean
  runHealth: RunHealth | null
}

/**
 * Convert AG-UI Message[] from a MessagesSnapshot into our UI types.
 */
function contentToString(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map((p: any) => (typeof p?.text === 'string' ? p.text : ''))
      .join('')
  }
  return ''
}

function snapshotToState(messages: Message[]): { msgs: AGUIMessage[]; tcs: ToolCallState[] } {
  const msgs: AGUIMessage[] = []
  const tcs: ToolCallState[] = []
  let order = 0

  for (const m of messages) {
    if (m.role === 'user') {
      order++
      msgs.push({ id: m.id, role: 'user', content: contentToString(m.content), order })
    } else if (m.role === 'assistant') {
      // Tool calls come BEFORE the assistant text in the timeline
      // (the agent called tools, got results, then wrote the response)
      if ('toolCalls' in m && Array.isArray(m.toolCalls)) {
        for (const tc of m.toolCalls) {
          order++
          const tcState: ToolCallState = {
            id: tc.id,
            // Persisted streams from older providers can omit this field. Keep
            // the event valid, but never leak an `unknown` card into the UI.
            name: tc.function?.name || '',
            args: tc.function?.arguments || '{}',
            result: null,
            status: 'calling',
            order,
          }
          if (tcState.name === 'delegate_to_subagent') {
            try {
              const args = JSON.parse(tcState.args)
              if (args.conversation_id) tcState.conversationId = args.conversation_id
            } catch {}
          }
          tcs.push(tcState)
        }
      }
      order++
      msgs.push({ id: m.id, role: 'assistant', content: contentToString(m.content), order })
    } else if (m.role === 'system' && typeof m.content === 'string' && m.content.startsWith('[RUN_NOTICE:')) {
      const match = m.content.match(/^\[RUN_NOTICE:([^:\]]+):(\d+)\]\n?([\s\S]*)$/)
      order++
      msgs.push({
        id: m.id,
        role: 'run_notice',
        content: match ? match[3] : m.content,
        order,
        stopReason: match ? match[1] : 'unknown',
        maxTurns: match ? parseInt(match[2], 10) : undefined,
      })
    } else if (m.role === 'system' && typeof m.content === 'string' && m.content.startsWith('[COMPACTION:')) {
      // Parse compaction metadata from content prefix: [COMPACTION:count:kept]\nsummary
      const match = m.content.match(/^\[COMPACTION:(\d+)(?::(\d+))?\]\n?([\s\S]*)$/)
      const count = match ? parseInt(match[1], 10) : 0
      const kept = match && match[2] ? parseInt(match[2], 10) : 0
      const summary = match ? match[3] : m.content
      order++
      msgs.push({
        id: m.id,
        role: 'compaction',
        content: summary,
        order,
        compactedCount: count,
        keptCount: kept,
      })
    } else if (m.role === 'tool' && 'toolCallId' in m) {
      const existing = tcs.find(tc => tc.id === m.toolCallId)
      if (existing) {
        existing.result = contentToString(m.content)
        existing.status = 'complete'
        // Extract conversationId from result
        if (existing.name === 'delegate_to_subagent' && existing.result) {
          try {
            const parsed = JSON.parse(existing.result)
            if (parsed.conversation_id) existing.conversationId = parsed.conversation_id
          } catch {}
        }
      }
    }
  }

  return { msgs, tcs }
}

/**
 * Find the active delegate_to_subagent tool call (status='calling').
 */
function findActiveDelegateIdx(toolCalls: ToolCallState[]): number {
  return toolCalls.findIndex(tc => tc.name === 'delegate_to_subagent' && tc.status === 'calling')
}

export function useAGUI(options?: { onRunFinished?: () => void }) {
  const [state, setState] = useState<AGUIState>({
    messages: [],
    toolCalls: [],
    guardrails: [],
    isRunning: false,
    isStopping: false,
    error: null,
    reconnecting: false,
    runHealth: null,
  })
  const orderRef = useRef(0)
  const subRef = useRef<Subscription | null>(null)
  const threadIdRef = useRef<string | null>(null)
  // Skip replacing messages on the next snapshot (we already have the optimistic user message)
  // but still update orderRef so subsequent events get correct ordering
  const skipSnapshotRef = useRef(false)

  const processEvent = useCallback((event: BaseEvent) => {
    switch (event.type) {
      case EventType.MESSAGES_SNAPSHOT: {
        const e = event as MessagesSnapshotEvent
        const { msgs, tcs } = snapshotToState(e.messages)
        const maxOrder = Math.max(0, ...msgs.map(m => m.order), ...tcs.map(tc => tc.order))

        if (skipSnapshotRef.current) {
          skipSnapshotRef.current = false
          // Don't replace messages (avoids duplicating the optimistic user message),
          // but update orderRef so subsequent events (text, tool calls) get correct ordering
          orderRef.current = Math.max(orderRef.current, maxOrder)
          break
        }

        orderRef.current = maxOrder
        setState(prev => ({ ...prev, messages: msgs, toolCalls: tcs }))
        break
      }

      case EventType.RUN_STARTED:
        setState(prev => prev.reconnecting ? { ...prev, reconnecting: false } : prev)
        break

      case EventType.TEXT_MESSAGE_START: {
        const e = event as TextMessageStartEvent
        orderRef.current++
        const order = orderRef.current
        setState(prev => {
          if (prev.messages.some(m => m.id === e.messageId)) return prev
          return {
            ...prev,
            isRunning: true,
            messages: [...prev.messages, {
              id: e.messageId,
              role: 'assistant',
              content: '',
              order,
            }],
          }
        })
        break
      }

      case EventType.TEXT_MESSAGE_CONTENT: {
        const e = event as TextMessageContentEvent
        setState(prev => ({
          ...prev,
          messages: prev.messages.map(m =>
            m.id === e.messageId ? { ...m, content: m.content + e.delta } : m
          ),
        }))
        break
      }

      case EventType.TEXT_MESSAGE_END:
        break

      case EventType.TOOL_CALL_START: {
        const e = event as ToolCallStartEvent
        orderRef.current++
        const order = orderRef.current
        setState(prev => {
          if (prev.toolCalls.some(tc => tc.id === e.toolCallId)) return prev
          return {
            ...prev,
            isRunning: true,
            toolCalls: [...prev.toolCalls, {
            id: e.toolCallId,
            name: e.toolCallName || '',
            args: '', result: null, status: 'calling',
            order,
            startedAt: Date.now(),
            }],
          }
        })
        break
      }

      case EventType.TOOL_CALL_ARGS: {
        const e = event as ToolCallArgsEvent
        setState(prev => ({
          ...prev,
          toolCalls: prev.toolCalls.map(tc =>
            tc.id === e.toolCallId ? { ...tc, args: tc.args + e.delta } : tc
          ),
        }))
        break
      }

      case EventType.TOOL_CALL_END:
        break

      case EventType.TOOL_CALL_RESULT: {
        const e = event as ToolCallResultEvent
        setState(prev => ({
          ...prev,
          toolCalls: prev.toolCalls.map(tc => {
            if (tc.id !== e.toolCallId) return tc
            const updated: ToolCallState = { ...tc, result: e.content, status: 'complete', finishedAt: Date.now() }
            // Extract conversationId from delegate result
            if (updated.name === 'delegate_to_subagent' && e.content) {
              try {
                const parsed = JSON.parse(e.content)
                if (parsed.conversation_id) updated.conversationId = parsed.conversation_id
              } catch {}
            }
            return updated
          }),
        }))
        break
      }

      case EventType.RUN_FINISHED:
        setState(prev => {
          // Only fire onRunFinished if there are assistant messages (agent actually responded)
          const hasAssistantResponse = prev.messages.some(m => m.role === 'assistant' && m.content.length > 0)
          if (hasAssistantResponse) {
            // Defer to next tick so state has settled before auto-continue triggers
            setTimeout(() => options?.onRunFinished?.(), 0)
          }
          return { ...prev, isRunning: false, isStopping: false, reconnecting: false, runHealth: null }
        })
        break

      case EventType.RUN_ERROR: {
        const e = event as RunErrorEvent
        setState(prev => ({ ...prev, isRunning: false, isStopping: false, reconnecting: false, runHealth: null, error: e.message || 'Unknown error' }))
        break
      }

      // ── Custom events (compaction, subagent progress) ───────────────
      case EventType.CUSTOM: {
        const e = event as AGUICustomEvent
        const name = (e as any).name as string | undefined
        const value = (e as any).value as any
        if (!name) break

        if (name === 'tool:progress') {
          const toolCallId = String(value?.toolCallId || '')
          if (!toolCallId) break
          const progress: ToolProgress = {
            phase: String(value?.phase || 'working'),
            label: String(value?.label || 'Working'),
            activity: value?.activity,
            attempt: typeof value?.attempt === 'number' ? value.attempt : undefined,
            maxAttempts: typeof value?.maxAttempts === 'number' ? value.maxAttempts : undefined,
            elapsedMs: typeof value?.elapsedMs === 'number' ? value.elapsedMs : undefined,
            outputChars: typeof value?.outputChars === 'number' ? value.outputChars : undefined,
            lastOutputAt: value?.lastOutputAt,
            emittedAt: value?.emittedAt,
            heartbeat: Boolean(value?.heartbeat),
            timeoutSeconds: typeof value?.timeoutSeconds === 'number' ? value.timeoutSeconds : undefined,
            startedAt: value?.startedAt,
          }
          setState(prev => ({
            ...prev,
            toolCalls: prev.toolCalls.map(tc => {
              if (tc.id !== toolCallId) return tc
              const parsedStart = progress.startedAt ? Date.parse(progress.startedAt) : NaN
              return {
                ...tc,
                startedAt: Number.isFinite(parsedStart) ? parsedStart : tc.startedAt,
                progress,
              }
            }),
          }))
          break
        }

        if (name === 'agent:max_turns_reached') {
          const messageId = value?.messageId || `run-notice-${Date.now()}`
          setState(prev => {
            if (prev.messages.some(message => message.id === messageId)) return prev
            orderRef.current++
            return {
              ...prev,
              messages: [...prev.messages, {
                id: messageId,
                role: 'run_notice' as const,
                content: value?.message || 'The configured agent-turn limit was reached before the task finished.',
                order: orderRef.current,
                stopReason: value?.reason || 'max_turns',
                maxTurns: typeof value?.maxTurns === 'number' ? value.maxTurns : undefined,
              }],
            }
          })
          break
        }

        // Handle compaction events
        if (name === 'compaction') {
          orderRef.current++
          setState(prev => ({
            ...prev,
            messages: [...prev.messages, {
              id: value?.messageId || `compaction-${Date.now()}`,
              role: 'compaction' as const,
              content: value?.summary || '',
              order: orderRef.current,
              compactedCount: value?.compactedCount || 0,
              keptCount: value?.keptCount || 0,
            }],
          }))
          break
        }

        // Handle guardrail events
        if (name === 'guardrail:auto_reply' || name === 'guardrail:post_intervention') {
          orderRef.current++
          const guardrail: GuardrailState = {
            id: `guardrail-${value?.toolCallId || Date.now()}`,
            guardrailId: value?.guardrailId || '',
            toolCallId: value?.toolCallId || '',
            message: value?.message || '',
            severity: value?.severity || 'warning',
            mode: 'auto_reply',
            status: name === 'guardrail:post_intervention' ? 'post_intervention' : 'auto_replied',
            order: orderRef.current,
          }
          setState(prev => ({ ...prev, guardrails: [...prev.guardrails, guardrail] }))
          break
        }

        if (name === 'guardrail:approval_required') {
          orderRef.current++
          const guardrail: GuardrailState = {
            id: `guardrail-${value?.toolCallId || Date.now()}`,
            guardrailId: value?.guardrailId || '',
            toolCallId: value?.toolCallId || '',
            message: value?.message || '',
            severity: value?.severity || 'warning',
            mode: 'user_approval',
            status: 'pending',
            approvalId: value?.approvalId || '',
            order: orderRef.current,
          }
          setState(prev => ({ ...prev, guardrails: [...prev.guardrails, guardrail] }))
          break
        }

        if (name === 'guardrail:approved' || name === 'guardrail:denied') {
          const status = name === 'guardrail:approved' ? 'approved' : 'denied'
          setState(prev => ({
            ...prev,
            guardrails: prev.guardrails.map(g =>
              g.approvalId === value?.approvalId ? { ...g, status } : g
            ),
          }))
          break
        }

        if (name === 'artifact_published') {
          const result = JSON.stringify({
            success: true,
            artifact_id: value?.artifact_id,
            version: value?.version,
            url: value?.url,
            session_id: value?.session_id,
            title: value?.title,
            description: value?.description,
          })
          setState(prev => {
            const alreadyRendered = prev.toolCalls.some(tc => {
              if (tc.name !== 'publish_artifact' || !tc.result) return false
              try {
                const parsed = JSON.parse(tc.result)
                return parsed?.artifact_id === value?.artifact_id && parsed?.version === value?.version
              } catch {
                return false
              }
            })
            if (alreadyRendered) return prev

            const activeIdx = prev.toolCalls
              .map((tc, idx) => ({ tc, idx }))
              .reverse()
              .find(({ tc }) => tc.name === 'publish_artifact' && tc.status === 'calling')?.idx

            if (activeIdx !== undefined) {
              const updated = [...prev.toolCalls]
              updated[activeIdx] = { ...updated[activeIdx], result, status: 'complete' }
              return { ...prev, toolCalls: updated }
            }

            orderRef.current++
            return {
              ...prev,
              toolCalls: [...prev.toolCalls, {
                id: `artifact-event-${value?.artifact_id || Date.now()}-${value?.version || 'latest'}`,
                name: 'publish_artifact',
                args: '{}',
                result,
                status: 'complete',
                order: orderRef.current,
              }],
            }
          })
          break
        }

        if (!name.startsWith('subagent:')) break

        setState(prev => {
          const idx = findActiveDelegateIdx(prev.toolCalls)
          if (idx === -1) return prev

          const tc = prev.toolCalls[idx]
          const updated = [...prev.toolCalls]

          switch (name) {
            case 'subagent:started':
              updated[idx] = {
                ...tc,
                subagent: {
                  name: value.name,
                  agentType: value.agent_type,
                  task: value.task,
                  status: 'running',
                  currentTurn: 0,
                  toolCalls: [],
                  textChunks: [],
                  conversationId: value.conversation_id || '',
                },
              }
              break

            case 'subagent:tool_call':
              if (tc.subagent) {
                updated[idx] = {
                  ...tc,
                  subagent: {
                    ...tc.subagent,
                    toolCalls: [...tc.subagent.toolCalls, {
                      toolName: value.tool_name,
                      toolInput: value.tool_input || {},
                      status: 'calling',
                      turn: tc.subagent.currentTurn,
                    }],
                  },
                }
              }
              break

            case 'subagent:tool_result':
              if (tc.subagent) {
                const tcs = [...tc.subagent.toolCalls]
                // Update the last tool call matching this tool_name
                for (let i = tcs.length - 1; i >= 0; i--) {
                  if (tcs[i].toolName === value.tool_name && tcs[i].status === 'calling') {
                    tcs[i] = { ...tcs[i], status: value.status === 'error' ? 'error' : 'ok' }
                    break
                  }
                }
                updated[idx] = { ...tc, subagent: { ...tc.subagent, toolCalls: tcs } }
              }
              break

            case 'subagent:text_delta':
              if (tc.subagent) {
                updated[idx] = {
                  ...tc,
                  subagent: {
                    ...tc.subagent,
                    textChunks: [...tc.subagent.textChunks, value.text],
                  },
                }
              }
              break

            case 'subagent:finished':
              if (tc.subagent) {
                updated[idx] = {
                  ...tc,
                  subagent: {
                    ...tc.subagent,
                    status: value.status,
                    conversationId: value.conversation_id || tc.subagent.conversationId,
                  },
                  conversationId: value.conversation_id || tc.conversationId,
                }
              }
              break
          }

          return { ...prev, toolCalls: updated }
        })
        break
      }

      case EventType.STEP_STARTED: {
        const e = event as StepStartedEvent
        const stepName = (e as any).stepName as string | undefined
        if (!stepName) break
        const match = stepName.match(/^subagent:turn:(\d+)$/)
        if (!match) break
        const turnNum = parseInt(match[1], 10)

        setState(prev => {
          const idx = findActiveDelegateIdx(prev.toolCalls)
          if (idx === -1 || !prev.toolCalls[idx].subagent) return prev
          const tc = prev.toolCalls[idx]
          const updated = [...prev.toolCalls]
          updated[idx] = {
            ...tc,
            subagent: { ...tc.subagent!, currentTurn: turnNum },
          }
          return { ...prev, toolCalls: updated }
        })
        break
      }

      case EventType.STEP_FINISHED:
      case EventType.STATE_SNAPSHOT:
      case EventType.STATE_DELTA:
        break
    }
  }, [])

  const connectToAgent = useCallback((threadId: string, messages: Array<{ role: string; content: string }>) => {
    threadIdRef.current = threadId
    subRef.current?.unsubscribe()

    const http$ = runHttpRequest(`${API}/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thread_id: threadId, messages }),
    })
    const events$ = transformHttpEventStream(http$).pipe(
      transformChunks(),
    )

    subRef.current = events$.subscribe({
      next: processEvent,
      error: (err: any) => {
        setState(prev => ({ ...prev, isRunning: false, isStopping: false, reconnecting: false, error: err.message || 'Connection failed' }))
      },
      complete: () => {
        setState(prev => prev.isRunning ? { ...prev, isRunning: false, isStopping: false } : prev)
      },
    })
  }, [processEvent])

  const sendMessage = useCallback((
    threadId: string,
    history: Array<{ role: string; content: string }>,
    userText: string,
    options?: { sentFromQueue?: boolean; queuedAt?: number },
  ) => {
    orderRef.current++
    const userMsg: AGUIMessage = {
      id: crypto.randomUUID(), role: 'user', content: userText, order: orderRef.current,
      sentFromQueue: options?.sentFromQueue,
      queuedAt: options?.queuedAt,
    }

    skipSnapshotRef.current = true
    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMsg],
      isRunning: true,
      isStopping: false,
      error: null,
      reconnecting: false,
      runHealth: null,
    }))

    connectToAgent(threadId, [...history, { role: 'user', content: userText }])
  }, [connectToAgent])

  const checkAndReconnect = useCallback(async (threadId: string) => {
    setState(prev => ({ ...prev, reconnecting: true, isRunning: true, isStopping: false }))
    connectToAgent(threadId, [])
    return true
  }, [connectToAgent])

  const cancelRun = useCallback(async (threadId: string) => {
    setState(prev => ({ ...prev, isStopping: true, error: null }))
    try {
      const response = await fetch(`${API}/agent/cancel/${threadId}`, { method: 'POST' })
      if (!response.ok) throw new Error('The running task could not be stopped')
    } catch (error) {
      setState(prev => ({
        ...prev,
        isStopping: false,
        error: error instanceof Error ? error.message : 'The running task could not be stopped',
      }))
    }
  }, [])

  useEffect(() => {
    if (!state.isRunning || !threadIdRef.current) return
    let disposed = false

    const poll = async () => {
      const threadId = threadIdRef.current
      if (!threadId) return
      try {
        const response = await fetch(`${API}/agent/status/${threadId}`)
        if (!response.ok) throw new Error(`status ${response.status}`)
        const payload = await response.json()
        if (disposed) return
        setState(prev => ({
          ...prev,
          runHealth: { ...payload, reachable: true, checkedAt: Date.now() },
        }))
      } catch {
        if (disposed) return
        setState(prev => ({
          ...prev,
          runHealth: {
            running: prev.isRunning,
            status: 'unknown',
            healthy: false,
            task_status: 'unknown',
            reachable: false,
            checkedAt: Date.now(),
          },
        }))
      }
    }

    const initialTimer = window.setTimeout(poll, 750)
    const timer = window.setInterval(poll, 5000)
    return () => {
      disposed = true
      window.clearTimeout(initialTimer)
      window.clearInterval(timer)
    }
  }, [state.isRunning])

  const reset = useCallback(() => {
    subRef.current?.unsubscribe()
    orderRef.current = 0
    skipSnapshotRef.current = false
    threadIdRef.current = null
    setState({ messages: [], toolCalls: [], guardrails: [], isRunning: false, isStopping: false, error: null, reconnecting: false, runHealth: null })
  }, [])

  const setMessages = useCallback((messages: AGUIMessage[]) => {
    setState(prev => ({ ...prev, messages }))
  }, [])

  const setToolCalls = useCallback((toolCalls: ToolCallState[]) => {
    setState(prev => ({ ...prev, toolCalls }))
  }, [])

  const setInitialOrder = useCallback((order: number) => {
    orderRef.current = order
  }, [])

  // Build merged timeline sorted by order
  const timeline: TimelineItem[] = [
    ...state.messages.map(m => ({ type: 'message' as const, item: m })),
    ...state.toolCalls.map(tc => ({ type: 'toolCall' as const, item: tc })),
    ...state.guardrails.map(g => ({ type: 'guardrail' as const, item: g })),
  ].sort((a, b) => a.item.order - b.item.order)

  return {
    ...state,
    timeline,
    sendMessage,
    cancelRun,
    checkAndReconnect,
    reset,
    setMessages,
    setToolCalls,
    setInitialOrder,
  }
}
