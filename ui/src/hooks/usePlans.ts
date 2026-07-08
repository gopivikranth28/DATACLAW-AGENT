import { createContext, useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import { API } from '../api'

export interface PlanStep {
  plan_step_id?: string
  id?: string
  name: string
  description?: string
  status?: string
  summary?: string
  note?: string
  outputs?: string[]
  updated_at?: string
}

export interface Plan {
  id: string
  name: string
  description?: string
  context?: string
  plan_markdown?: string
  status: string
  steps: PlanStep[]
  iteration?: number
  revision?: number
  decision?: string | null
  feedback?: string
  progress_summary?: string
  created_at?: string
  updated_at?: string
  mlflow_experiment_id?: string
  mlflow_run_ids?: string[]
}

export interface PlansContextValue {
  plans: Plan[]
  submitDecision: (planId: string, status: string, feedback?: string) => Promise<void>
  focusPlan: (planId: string) => void
}

// Carries plan state + actions to chat cards rendered deep in the timeline
// and to the composer review popover without prop drilling.
export const PlansContext = createContext<PlansContextValue | null>(null)

/**
 * Single source of truth for a session's plans. Both the chat decision cards
 * and the sidebar PlanPanel render from this one array, so a decision made
 * anywhere updates every surface in the same commit (optimistically, with
 * rollback if the POST fails). The 5s poll is a backstop — the real-time path
 * is the caller invoking refresh() when plan tool results arrive in the stream.
 */
export function usePlans(
  sessionId: string | null,
  enabled: boolean,
  onDecided?: (planId: string, status: string, feedback: string) => void,
) {
  const [plans, setPlans] = useState<Plan[]>([])
  const plansRef = useRef<Plan[]>([])
  useEffect(() => { plansRef.current = plans }, [plans])
  const onDecidedRef = useRef(onDecided)
  useEffect(() => { onDecidedRef.current = onDecided }, [onDecided])

  const refresh = useCallback(() => {
    if (!sessionId) return
    fetch(`${API}/plans?session_id=${sessionId}`)
      .then(r => r.ok ? r.json() : [])
      .then(setPlans)
      .catch(() => {})
  }, [sessionId])

  useEffect(() => {
    if (!enabled || !sessionId) { setPlans([]); return }
    refresh()
    const interval = setInterval(refresh, 5000)
    return () => clearInterval(interval)
  }, [enabled, sessionId, refresh])

  // silent: skip onDecided — used when the user's own chat message already
  // carries the decision (pending-plan composer feedback flow).
  const submitDecision = useCallback(async (planId: string, status: string, feedback: string = '', silent: boolean = false) => {
    const prev = plansRef.current
    setPlans(current => current.map(p => p.id === planId ? { ...p, status, decision: status, feedback } : p))
    try {
      const res = await fetch(`${API}/plans/${planId}/decision`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, feedback }),
      })
      if (!res.ok) throw new Error('decision failed')
      refresh()
      if (!silent) onDecidedRef.current?.(planId, status, feedback)
    } catch {
      setPlans(prev)
      message.error('Failed to submit decision')
    }
  }, [refresh])

  return { plans, refresh, submitDecision }
}
