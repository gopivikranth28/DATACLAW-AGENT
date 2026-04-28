import { useState, useCallback, useRef } from 'react'
import { API } from '../api'

export interface AGUIMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  order: number
}

export interface ToolCallState {
  id: string
  name: string
  args: string
  result: string | null
  status: 'calling' | 'complete' | 'error'
  order: number
}

export type TimelineItem =
  | { type: 'message'; item: AGUIMessage }
  | { type: 'toolCall'; item: ToolCallState }

interface AGUIState {
  messages: AGUIMessage[]
  toolCalls: ToolCallState[]
  isRunning: boolean
  error: string | null
  reconnecting: boolean
}

export function useAGUI() {
  const [state, setState] = useState<AGUIState>({
    messages: [],
    toolCalls: [],
    isRunning: false,
    error: null,
    reconnecting: false,
  })
  const abortRef = useRef<AbortController | null>(null)
  const orderRef = useRef(0)
  const cursorRef = useRef(0)
  const threadIdRef = useRef<string | null>(null)

  // Process a single SSE event and update state
  const processEvent = useCallback((event: any) => {
    switch (event.type) {
      case 'RUN_STARTED':
        break

      case 'TEXT_MESSAGE_START':
        orderRef.current++
        setState(prev => {
          if (prev.messages.some(m => m.id === event.messageId)) return prev
          return {
            ...prev,
            messages: [...prev.messages, {
              id: event.messageId,
              role: 'assistant',
              content: '',
              order: orderRef.current,
            }],
          }
        })
        break

      case 'TEXT_MESSAGE_CONTENT':
        setState(prev => ({
          ...prev,
          messages: prev.messages.map(m =>
            m.id === event.messageId ? { ...m, content: m.content + event.delta } : m
          ),
        }))
        break

      case 'TEXT_MESSAGE_END':
        break

      case 'TOOL_CALL_START':
        orderRef.current++
        setState(prev => {
          if (prev.toolCalls.some(tc => tc.id === event.toolCallId)) return prev
          return {
            ...prev,
            toolCalls: [...prev.toolCalls, {
              id: event.toolCallId,
              name: event.toolCallName,
              args: '', result: null, status: 'calling',
              order: orderRef.current,
            }],
          }
        })
        break

      case 'TOOL_CALL_ARGS':
        setState(prev => ({
          ...prev,
          toolCalls: prev.toolCalls.map(tc =>
            tc.id === event.toolCallId ? { ...tc, args: tc.args + event.delta } : tc
          ),
        }))
        break

      case 'TOOL_CALL_END':
        break

      case 'TOOL_CALL_RESULT':
        setState(prev => ({
          ...prev,
          toolCalls: prev.toolCalls.map(tc =>
            tc.id === event.toolCallId ? { ...tc, result: event.content, status: 'complete' } : tc
          ),
        }))
        break

      case 'RUN_FINISHED':
        setState(prev => ({ ...prev, isRunning: false, reconnecting: false }))
        break

      case 'RUN_ERROR':
        setState(prev => ({ ...prev, isRunning: false, reconnecting: false, error: event.message || 'Unknown error' }))
        break
    }
  }, [])

  // Read an SSE stream and process events
  const readStream = useCallback(async (res: Response, signal?: AbortSignal) => {
    const reader = res.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (signal?.aborted) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''

      for (const block of lines) {
        for (const line of block.split('\n')) {
          if (!line.startsWith('data: ')) continue
          const json_str = line.slice(6).trim()
          if (!json_str) continue

          let event: any
          try { event = JSON.parse(json_str) } catch { continue }

          // Track cursor if present
          if (event._cursor) cursorRef.current = event._cursor

          processEvent(event)
        }
      }
    }
  }, [processEvent])

  // Reconnect to an active run
  const reconnect = useCallback(async (threadId: string) => {
    setState(prev => ({ ...prev, reconnecting: true }))
    try {
      const statusRes = await fetch(`${API}/agent/status/${threadId}`)
      if (!statusRes.ok) {
        // Run is not active — finished or never started
        setState(prev => ({ ...prev, isRunning: false, reconnecting: false }))
        return false
      }
      const status = await statusRes.json()
      if (!status.running) {
        setState(prev => ({ ...prev, isRunning: false, reconnecting: false }))
        return false
      }

      // Reconnect to event stream from where we left off
      const controller = new AbortController()
      abortRef.current = controller

      const eventsRes = await fetch(`${API}/agent/events/${threadId}?after=${cursorRef.current}`, {
        signal: controller.signal,
      })
      if (!eventsRes.ok) {
        setState(prev => ({ ...prev, isRunning: false, reconnecting: false }))
        return false
      }

      setState(prev => ({ ...prev, isRunning: true, reconnecting: false, error: null }))
      await readStream(eventsRes, controller.signal)
      setState(prev => ({ ...prev, isRunning: false }))
      return true
    } catch (err: any) {
      if (err.name === 'AbortError') return false
      setState(prev => ({ ...prev, reconnecting: false }))
      // Retry after delay
      await new Promise(r => setTimeout(r, 2000))
      return reconnect(threadId)
    }
  }, [readStream])

  // Check if a run is active for the given thread and reconnect if so.
  // Sets cursor to server's current position so we only get NEW events
  // (session history is loaded separately from disk).
  const checkAndReconnect = useCallback(async (threadId: string) => {
    threadIdRef.current = threadId
    try {
      const res = await fetch(`${API}/agent/status/${threadId}`)
      if (res.ok) {
        const status = await res.json()
        if (status.running) {
          // Start tailing from current server cursor — don't replay old events
          cursorRef.current = status.cursor || 0
          setState(prev => ({ ...prev, isRunning: true }))
          await reconnect(threadId)
          return true
        }
      }
    } catch {}
    return false
  }, [reconnect])

  const sendMessage = useCallback(async (
    threadId: string,
    history: any[],
    userText: string,
  ) => {
    orderRef.current++
    cursorRef.current = 0
    threadIdRef.current = threadId
    const userMsg: AGUIMessage = { id: crypto.randomUUID(), role: 'user', content: userText, order: orderRef.current }

    setState(prev => ({
      ...prev,
      messages: [...prev.messages, userMsg],
      isRunning: true,
      error: null,
      reconnecting: false,
    }))

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch(`${API}/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          thread_id: threadId,
          messages: [...history, { role: 'user', content: userText }],
        }),
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`)

      await readStream(res, controller.signal)
      setState(prev => ({ ...prev, isRunning: false }))
    } catch (err: any) {
      if (err.name === 'AbortError') return
      // Try to reconnect — the background task may still be running
      setState(prev => ({ ...prev, error: null }))
      const reconnected = await reconnect(threadId)
      if (!reconnected) {
        setState(prev => ({ ...prev, isRunning: false, error: err.message || 'Connection failed' }))
      }
    }
  }, [readStream, reconnect])

  const cancelRun = useCallback(async (threadId: string) => {
    try {
      await fetch(`${API}/agent/cancel/${threadId}`, { method: 'POST' })
    } catch {}
    abortRef.current?.abort()
    setState(prev => ({ ...prev, isRunning: false }))
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    orderRef.current = 0
    cursorRef.current = 0
    threadIdRef.current = null
    setState({ messages: [], toolCalls: [], isRunning: false, error: null, reconnecting: false })
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
