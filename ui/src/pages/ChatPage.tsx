import { useState, useEffect, useRef, useCallback, useMemo, type ReactNode } from 'react'
import { Button, Card, Input, Empty, Alert, Modal, Switch, Tag, Tooltip } from 'antd'
import {
  PlusOutlined, SendOutlined, SettingOutlined,
  FolderOutlined, FolderOpenOutlined, ExperimentOutlined, StopOutlined, ReloadOutlined,
  EditOutlined, SafetyOutlined,
  ExportOutlined, PauseOutlined, PlayCircleOutlined, CloseOutlined, ArrowUpOutlined, RightOutlined,
  ArrowLeftOutlined, MessageOutlined, FileTextOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { API } from '../api'
import { useAGUI } from '../hooks/useAGUI'
import type { AGUIMessage, ToolCallState } from '../hooks/useAGUI'
import MarkdownContent from '../components/MarkdownContent'
import { groupTranscript, TurnActivity } from '../components/ChatActivity'
import { toolBaseName } from '../components/reportPublishState'
import PlanPanel from '../components/PlanPanel'
import ArtifactPanel from '../components/ArtifactPanel'
import { usePlans, PlansContext } from '../hooks/usePlans'
import { FileViewerModal } from '../components/FilePreview'
import FileIcon from '../components/FileIcon'
import AppView, {
  collectAppItems,
  itemsFromVisualArtifacts,
  mergeAppItems,
  type AppLayout,
  type VisualArtifact,
} from '../components/AppView'

interface Session { id: string; title: string; createdAt: string; projectId?: string | null; project_id?: string | null }
interface QueuedMessage { id: string; text: string; ts: number }
interface PersistedToolTiming { startedAt?: number; finishedAt?: number }
interface ReportCounts { published: number; scratch: number }
type FileSort = 'name' | 'size'

function isSuccessfulArtifactPublish(call: ToolCallState): boolean {
  if (toolBaseName(call.name) !== 'publish_artifact' || call.status !== 'complete' || !call.result) return false
  try {
    const result = typeof call.result === 'string' ? JSON.parse(call.result) : call.result
    return Boolean(result?.success && result?.artifact_id && result?.version)
  } catch {
    return false
  }
}

// A chat is a reading surface, not an edge-to-edge document.  The outer
// workspace retains generous gutters; this shared inner canvas keeps prose,
// work logs, evidence, and the composer aligned at a readable measure.
const CHAT_SURFACE_MAX_WIDTH = 1000

function timestampMilliseconds(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value < 1_000_000_000_000 ? value * 1000 : value
  }
  if (typeof value !== 'string') return undefined
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? undefined : parsed
}

function persistedToolTimings(messages: unknown): Record<string, PersistedToolTiming> {
  if (!Array.isArray(messages)) return {}
  const timings: Record<string, PersistedToolTiming> = {}
  for (const message of messages) {
    if (!message || typeof message !== 'object') continue
    const record = message as Record<string, unknown>
    if (record.role !== 'tool_call') continue
    const id = typeof record.toolCallId === 'string'
      ? record.toolCallId
      : typeof record.messageId === 'string'
        ? record.messageId
        : ''
    if (!id) continue
    // Legacy sessions only recorded the append time. It is the end of the
    // step—not its start—but still gives a truthful completion sequence rather
    // than a blank log or a made-up +0:00 for every row.
    const startedAt = timestampMilliseconds(record.startedAt)
    const finishedAt = timestampMilliseconds(record.finishedAt ?? record.timestamp)
    if (startedAt === undefined && finishedAt === undefined) continue
    timings[id] = { startedAt, finishedAt }
  }
  return timings
}

interface ChatPageProps {
  projectId?: string
  initialSessionId?: string | null
  initialDatasetIds?: string[] | null
  onSessionChange?: (id: string | null) => void
  onBackToSessions?: () => void
}

export default function ChatPage({ projectId, initialSessionId, initialDatasetIds, onSessionChange, onBackToSessions }: ChatPageProps = {}) {
  const [sessions, setSessions] = useState<Session[]>([])
  // Only use URL params for session persistence when standalone (no projectId)
  const isStandalone = !projectId
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSession = isStandalone ? searchParams.get('session') : null
  const [activeSessionId, _setActiveSessionId] = useState<string | null>(initialSessionId ?? urlSession ?? null)
  const [sessionBrowserOpen, setSessionBrowserOpen] = useState(() => !projectId && !initialSessionId && !urlSession)
  const [sessionProjectId, setSessionProjectId] = useState<string | null>(projectId ?? null)
  const [loadedSessionTitle, setLoadedSessionTitle] = useState('')
  const [savedToolTimings, setSavedToolTimings] = useState<Record<string, PersistedToolTiming>>({})
  const effectiveProjectId = projectId || sessionProjectId
  const [projectName, setProjectName] = useState<string | null>(null)
  const setActiveSessionId = (id: string | null) => {
    if (id !== activeSessionId) setLoadedSessionTitle('')
    _setActiveSessionId(id)
    if (id) setSessionBrowserOpen(false)
    if (!id) setSessionProjectId(projectId ?? null)
    onSessionChange?.(id)
    if (isStandalone) {
      const next = new URLSearchParams(searchParams)
      if (id) next.set('session', id)
      else next.delete('session')
      setSearchParams(next, { replace: true })
    }
  }
  const [input, setInput] = useState('')
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([])
  const [queuePaused, setQueuePaused] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const skipNextLoadRef = useRef(false)

  // Windowed rendering: only render the last N items, expand on scroll up
  const WINDOW_SIZE = 80
  const [visibleCount, setVisibleCount] = useState(WINDOW_SIZE)

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem('dataclaw_system_prompt') || '')
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState('')

  // Auto mode
  const DEFAULT_AUTO_MESSAGE = "Auto mode is turned on. Keep working to improve the result until told otherwise. If you are submitting a plan it is auto-approved. For each iteration you should continue raising plans and logging metrics to MLFlow. You should preserve outputs from each attempt in structured subdirectories."
  const [autoMode, setAutoMode] = useState(false)
  const [autoTurnsUsed, setAutoTurnsUsed] = useState(0)
  const [autoMessage, setAutoMessage] = useState(DEFAULT_AUTO_MESSAGE)
  const [maxAutoTurns, setMaxAutoTurns] = useState(10)
  const [autoMessageModalOpen, setAutoMessageModalOpen] = useState(false)
  const [autoMessageDraft, setAutoMessageDraft] = useState('')
  const [maxAutoTurnsDraft, setMaxAutoTurnsDraft] = useState(10)
  const autoModeRef = useRef(false)
  const autoTurnsRef = useRef(0)
  const maxAutoTurnsRef = useRef(10)
  const autoMessageRef = useRef(DEFAULT_AUTO_MESSAGE)
  const activeSessionIdRef = useRef<string | null>(null)
  const pendingPlanDecisionRef = useRef<{ sessionId: string; text: string } | null>(null)
  const queuedMessagesRef = useRef<QueuedMessage[]>([])
  const queuePausedRef = useRef(false)
  const commitQueueRef = useRef<(messages: QueuedMessage[], paused: boolean) => void>(() => {})
  const dispatchQueuedMessageRef = useRef<() => boolean>(() => false)

  // Plans — shared state lives in usePlans (wired after useAGUI below);
  // reviewed on the right (PlanPanel), referenced from the chat/bottom banner.
  const [hasPlansPlugin, setHasPlansPlugin] = useState(false)
  const [hasArtifactsPlugin, setHasArtifactsPlugin] = useState(false)
  const [artifactRefreshKey, setArtifactRefreshKey] = useState(0)
  // Fresh object per focusPlan() call so repeat clicks re-trigger the panel's
  // expand-and-scroll effect even for the same plan id.
  const [focusedPlan, setFocusedPlan] = useState<{ id: string } | null>(null)
  const [planReaderExpanded, setPlanReaderExpanded] = useState(false)

  // Dataset filters
  const [hasDataPlugin, setHasDataPlugin] = useState(false)
  const [allDatasets, setAllDatasets] = useState<any[]>([])
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[] | null>(initialDatasetIds !== undefined ? initialDatasetIds ?? null : null)

  // Tool filters
  const [allTools, setAllTools] = useState<any[]>([])
  const [selectedToolIds, setSelectedToolIds] = useState<string[] | null>(null)
  const [toolModalOpen, setToolModalOpen] = useState(false)

  // Skill filters
  const [allSkills, setAllSkills] = useState<any[]>([])
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[] | null>(null)
  const [skillModalOpen, setSkillModalOpen] = useState(false)

  // Subagent filters
  const [allSubagents, setAllSubagents] = useState<any[]>([])
  const [selectedSubagentIds, setSelectedSubagentIds] = useState<string[] | null>(null)
  const [subagentModalOpen, setSubagentModalOpen] = useState(false)

  // Guardrail config
  const [allGuardrails, setAllGuardrails] = useState<any[]>([])
  const [guardrailDisabled, setGuardrailDisabled] = useState<string[]>([])
  const [guardrailModalOpen, setGuardrailModalOpen] = useState(false)

  // Update dataset filter and persist to session
  const updateDatasetFilter = useCallback((ids: string[] | null) => {
    setSelectedDatasetIds(ids)
    if (activeSessionId) {
      fetch(`${API}/chat/sessions/${activeSessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ datasetIds: ids }),
      }).catch(() => {})
    }
  }, [activeSessionId])

  const updateToolFilter = useCallback((ids: string[] | null) => {
    setSelectedToolIds(ids)
    if (activeSessionId) {
      fetch(`${API}/chat/sessions/${activeSessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolIds: ids }),
      }).catch(() => {})
    }
  }, [activeSessionId])

  const updateSkillFilter = useCallback((ids: string[] | null) => {
    setSelectedSkillIds(ids)
    if (activeSessionId) {
      fetch(`${API}/chat/sessions/${activeSessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skillIds: ids }),
      }).catch(() => {})
    }
  }, [activeSessionId])

  const updateSubagentFilter = useCallback((ids: string[] | null) => {
    setSelectedSubagentIds(ids)
    if (activeSessionId) {
      fetch(`${API}/chat/sessions/${activeSessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subagentIds: ids }),
      }).catch(() => {})
    }
  }, [activeSessionId])

  const updateGuardrailConfig = useCallback((disabled: string[]) => {
    setGuardrailDisabled(disabled)
    if (activeSessionId) {
      fetch(`${API}/guardrails/config/session/${activeSessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disabled }),
      }).catch(() => {})
    }
  }, [activeSessionId])

  // Project directory (for resolving relative file paths)
  const [projectDir, setProjectDir] = useState<string | null>(null)
  useEffect(() => {
    if (!effectiveProjectId) {
      setProjectDir(null)
      setProjectName(null)
      return
    }
    fetch(`${API}/projects/${effectiveProjectId}`).then(r => r.ok ? r.json() : null)
      .then(p => {
        setProjectDir(p?.directory || null)
        setProjectName(p?.name || null)
      }).catch(() => {})
  }, [effectiveProjectId])

  const resolveFilePath = (path: string) => {
    if (path.startsWith('/')) return path
    return projectDir ? `${projectDir}/${path}` : path
  }

  const previewFile = (path: string) => {
    const resolved = resolveFilePath(path)
    setFilePreviewTarget({ name: path.split('/').pop() || path, path: resolved })
  }

  // File explorer
  const [sidebarTab, setSidebarTab] = useState<'plans' | 'files' | 'artifacts' | 'datasets' | 'experiments' | 'app' | 'scope'>('plans')

  // Compatibility scratch view curation — persisted so the legacy
  // /app/<session-id> route can still render loose visual outputs.
  const [appLayout, setAppLayout] = useState<AppLayout | null>(null)
  const [visualArtifacts, setVisualArtifacts] = useState<VisualArtifact[]>([])
  const [projectFiles, setProjectFiles] = useState<any[]>([])
  const [fileLoadError, setFileLoadError] = useState<string | null>(null)
  const [filePreviewTarget, setFilePreviewTarget] = useState<{ name: string; path: string } | null>(null)
  const [fileSort, setFileSort] = useState<FileSort>('name')
  const [foldersFirst, setFoldersFirst] = useState(true)
  const [reportCounts, setReportCounts] = useState<ReportCounts>({ published: 0, scratch: 0 })

  // MLflow runs belong to the active chat session and render in the companion panel.
  const [mlflowRuns, setMlflowRuns] = useState<any[]>([])
  const [mlflowLoading, setMlflowLoading] = useState(false)

  // Resizable sidebar
  const [sidebarWidth, setSidebarWidth] = useState(440)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true)
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth)
  const resizingRef = useRef(false)

  useEffect(() => {
    const update = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  // Keep auto mode refs in sync
  useEffect(() => { autoModeRef.current = autoMode }, [autoMode])
  useEffect(() => { autoTurnsRef.current = autoTurnsUsed }, [autoTurnsUsed])
  useEffect(() => { autoMessageRef.current = autoMessage }, [autoMessage])
  useEffect(() => { maxAutoTurnsRef.current = maxAutoTurns }, [maxAutoTurns])
  useEffect(() => { activeSessionIdRef.current = activeSessionId }, [activeSessionId])
  useEffect(() => { queuedMessagesRef.current = queuedMessages }, [queuedMessages])
  useEffect(() => { queuePausedRef.current = queuePaused }, [queuePaused])

  const commitQueue = useCallback((next: QueuedMessage[], paused: boolean) => {
    queuedMessagesRef.current = next
    queuePausedRef.current = paused
    setQueuedMessages(next)
    setQueuePaused(paused)
    const sessionId = activeSessionIdRef.current
    if (sessionId) {
      fetch(`${API}/chat/sessions/${sessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queuedMessages: next, queuePaused: paused }),
      }).catch(() => {})
    }
  }, [])
  useEffect(() => { commitQueueRef.current = commitQueue }, [commitQueue])

  // Stable ref for sendMessage so onRunFinished doesn't go stale
  const sendMessageRef = useRef<typeof sendMessage>(null as any)
  const autoContinuePendingRef = useRef(false)

  const dispatchQueuedMessage = useCallback(() => {
    const sessionId = activeSessionIdRef.current
    const [next, ...rest] = queuedMessagesRef.current
    if (!sessionId || !next || queuePausedRef.current) return false
    commitQueue(rest, false)
    setTimeout(() => sendMessageRef.current(sessionId, [], next.text, { sentFromQueue: true, queuedAt: next.ts }), 0)
    return true
  }, [commitQueue])
  useEffect(() => { dispatchQueuedMessageRef.current = dispatchQueuedMessage }, [dispatchQueuedMessage])

  const onRunFinished = useCallback(() => {
    // The queue is user-authored work and always preempts an auto continuation.
    if (queuedMessagesRef.current.length > 0 && !queuePausedRef.current) {
      dispatchQueuedMessageRef.current()
      return
    }
    if (!autoModeRef.current) return
    if (autoContinuePendingRef.current) return // prevent re-entrant triggers
    if (autoTurnsRef.current >= maxAutoTurnsRef.current) {
      setAutoMode(false)
      return
    }
    autoContinuePendingRef.current = true
    setTimeout(() => {
      autoContinuePendingRef.current = false
      const sessionId = activeSessionIdRef.current
      // Re-check auto mode — user may have toggled it off during the delay
      if (!sessionId || !autoModeRef.current) return
      setAutoTurnsUsed(prev => prev + 1)
      // We pass empty history — the backend loads full history from session storage
      sendMessageRef.current(sessionId, [], autoMessageRef.current)
    }, 2000)
  }, [])

  const { messages, toolCalls, timeline, isRunning, reconnecting, error, sendMessage, cancelRun, checkAndReconnect, reset, setToolCalls } = useAGUI({ onRunFinished })
  sendMessageRef.current = sendMessage

  // AG-UI snapshots intentionally discard unknown tool-call fields. Merge the
  // timing stored in the session back into the client state after a reload so
  // the notebook log keeps its real timeline, not a fabricated +0:00 column.
  useEffect(() => {
    if (!toolCalls.length || !Object.keys(savedToolTimings).length) return
    let changed = false
    const withTimings = toolCalls.map(call => {
      const timing = savedToolTimings[call.id]
      if (!timing) return call
      const startedAt = call.startedAt ?? timing.startedAt
      const finishedAt = call.finishedAt ?? timing.finishedAt
      if (startedAt === call.startedAt && finishedAt === call.finishedAt) return call
      changed = true
      return { ...call, startedAt, finishedAt }
    })
    if (changed) setToolCalls(withTimings)
  }, [savedToolTimings, setToolCalls, toolCalls])

  // Auto-send a chat message so the agent knows the decision
  const onPlanDecided = useCallback((planId: string, status: string, feedback: string) => {
    if (!activeSessionId) return
    const labels: Record<string, string> = { approved: 'approved', denied: 'denied', changes_requested: 'needs changes' }
    let text = `Plan ${planId} is ${labels[status] || status}.`
    if (feedback) text += ` Feedback: ${feedback}`

    if (isRunning) {
      pendingPlanDecisionRef.current = { sessionId: activeSessionId, text }
      return
    }

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    sendMessage(activeSessionId, history, text)
  }, [isRunning, activeSessionId, messages, sendMessage])

  useEffect(() => {
    if (isRunning) return
    const pending = pendingPlanDecisionRef.current
    if (!pending) return
    pendingPlanDecisionRef.current = null
    sendMessage(pending.sessionId, [], pending.text)
  }, [isRunning, sendMessage])

  // Refresh plan state as soon as a plan tool result lands in the stream —
  // the hook's 5s poll is only a backstop.
  const planToolResultCount = useMemo(
    () => toolCalls.filter(tc => (tc.name === 'propose_plan' || tc.name === 'update_plan') && tc.status === 'complete').length,
    [toolCalls])
  const artifactToolResultCount = useMemo(
    () => toolCalls.filter(isSuccessfulArtifactPublish).length,
    [toolCalls])
  const latestPublishedArtifact = useMemo(() => {
    for (const tc of [...toolCalls].reverse()) {
      if (!isSuccessfulArtifactPublish(tc) || !tc.result) continue
      try {
        const parsed = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
        if (parsed?.success && parsed?.artifact_id && parsed?.version) {
          return {
            artifact_id: String(parsed.artifact_id),
            version: Number(parsed.version),
          }
        }
      } catch {
        continue
      }
    }
    return null
  }, [toolCalls])
  const refreshReportCounts = useCallback((sessionId: string | null) => {
    if (!sessionId) {
      setReportCounts({ published: 0, scratch: 0 })
      return
    }
    fetch(`${API}/artifacts?session_id=${encodeURIComponent(sessionId)}`, { headers: { Accept: 'application/json' } })
      .then(r => r.ok ? r.json() : null)
      .then(payload => {
        if (activeSessionIdRef.current !== sessionId || !Array.isArray(payload?.artifacts)) return
        const scratch = payload.artifacts.filter((artifact: any) => artifact?.kind === 'living_report').length
        setReportCounts({ published: payload.artifacts.length - scratch, scratch })
      })
      .catch(() => {
        if (activeSessionIdRef.current === sessionId) setReportCounts({ published: 0, scratch: 0 })
      })
  }, [])
  const { plans, refresh: refreshPlans, submitDecision } = usePlans(
    activeSessionId,
    hasPlansPlugin || planToolResultCount > 0,
    onPlanDecided,
  )
  useEffect(() => { if (planToolResultCount > 0) refreshPlans() }, [planToolResultCount, refreshPlans])
  useEffect(() => {
    if (artifactToolResultCount <= 0) return
    setArtifactRefreshKey(k => k + 1)
    if (activeSessionId) refreshReportCounts(activeSessionId)
    setSidebarTab('artifacts')
    setSidebarCollapsed(false)
  }, [activeSessionId, artifactToolResultCount, refreshReportCounts])

  const focusPlan = useCallback((planId: string) => {
    setSidebarTab('plans')
    setSidebarCollapsed(false)
    setFocusedPlan({ id: planId })
  }, [setSidebarTab, setSidebarCollapsed, setFocusedPlan])

  const pendingPlans = useMemo(() => plans.filter(p => p.status === 'pending'), [plans])
  const latestPendingPlan = pendingPlans[pendingPlans.length - 1] ?? null
  const attentionPlan = useMemo(
    () => plans.find(plan => plan.status === 'pending') || plans.find(plan => plan.status === 'running' || plan.status === 'approved') || plans[plans.length - 1] || null,
    [plans],
  )
  const attentionPlanStepTotal = attentionPlan?.steps?.length || 0
  const attentionPlanStepDone = attentionPlan?.steps?.filter(step => ['complete', 'completed', 'done', 'approved'].includes(String(step.status || '').toLowerCase())).length || 0
  const attentionPlanProgress = attentionPlanStepTotal ? `${attentionPlanStepDone}/${attentionPlanStepTotal}` : null
  const attentionPlanStatus = attentionPlan?.status === 'pending'
    ? 'needs review'
    : attentionPlan?.status === 'running'
      ? 'running'
      : attentionPlan?.status === 'approved'
        ? 'approved'
        : attentionPlan?.status || ''
  const planStatusTone = attentionPlan?.status === 'pending'
    ? 'pending'
    : attentionPlan?.status === 'running'
      ? 'running'
      : attentionPlan
        ? 'complete'
        : null
  const composerPlaceholder = latestPendingPlan
    ? 'Type feedback or revision notes for this plan...'
    : isRunning
      ? 'Message Dataclaw — sends when the current run finishes...'
      : 'Send a message...'

  const plansCtx = useMemo(
    () => ({ plans, submitDecision, focusPlan }),
    [plans, submitDecision, focusPlan])

  // Compatibility App view: collect loose chart/metric items from the session's
  // tool calls. Published artifacts are the durable output surface.
  const appItems = useMemo(() => {
    const persisted = itemsFromVisualArtifacts(visualArtifacts)
    const live = collectAppItems(toolCalls.map(tc => ({ name: tc.name, result: tc.result })))
    return mergeAppItems(persisted, live)
  }, [toolCalls, visualArtifacts])
  const scratchReports = useMemo(() => {
    // Prefer the session-persisted visual artifacts. They represent drafts the
    // user can return to after refresh; live tool output is only a fallback
    // while that session snapshot is catching up.
    const persisted = itemsFromVisualArtifacts(visualArtifacts)
    const candidates = persisted.length ? persisted : appItems
    return candidates.flatMap(item => item.kind === 'report'
      ? [{ id: item.id, htmlPath: item.htmlPath, title: item.title, updatedAt: item.updatedAt }]
      : [])
  }, [appItems, visualArtifacts])
  useEffect(() => {
    setAppLayout(null)
    setVisualArtifacts([])
    if (!activeSessionId) return
    fetch(`${API}/chat/sessions/${activeSessionId}`)
      .then(r => r.ok ? r.json() : null)
      .then(s => {
      if (s?.appLayout) setAppLayout(s.appLayout)
      if (Array.isArray(s?.visualArtifacts)) setVisualArtifacts(s.visualArtifacts)
      })
      .catch(() => {})
  }, [activeSessionId])
  useEffect(() => { refreshReportCounts(activeSessionId) }, [activeSessionId, refreshReportCounts])
  const saveAppLayout = useCallback((layout: AppLayout) => {
    setAppLayout(layout)
    if (!activeSessionId) return
    fetch(`${API}/chat/sessions/${activeSessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ appLayout: layout }),
    }).catch(() => {})
  }, [activeSessionId])

  // Check plugins
  useEffect(() => {
    fetch(`${API}/plugins`).then(r => r.ok ? r.json() : []).then(plugins => {
      setHasPlansPlugin(plugins.some((p: any) => p.id === 'plans'))
      setHasArtifactsPlugin(plugins.some((p: any) => p.id === 'artifacts'))
      setHasDataPlugin(plugins.some((p: any) => p.id === 'data'))
    }).catch(() => {})
  }, [])

  // Load sessions
  const loadSessions = useCallback(async () => {
    try {
      const url = projectId ? `${API}/chat/sessions?project_id=${projectId}` : `${API}/chat/sessions`
      const res = await fetch(url)
      if (res.ok) {
        const listed: Session[] = await res.json()
        // Keep the UI boundary intact even if a stale or third-party API returns
        // a broader list than it was asked for. A project chat never belongs in
        // the independent Chats browser, and vice versa.
        setSessions(listed.filter(session => {
          const owner = session.projectId ?? session.project_id ?? null
          return projectId ? owner === projectId : owner === null
        }))
      }
    } catch {}
  }, [projectId])
  useEffect(() => { loadSessions() }, [loadSessions])

  // The sidebar can create an independent chat from anywhere in the app. Keep
  // this focused surface in sync when navigation changes only the query string.
  useEffect(() => {
    if (isStandalone && urlSession && urlSession !== activeSessionId) {
      setActiveSessionId(urlSession)
    }
    // Deliberately react to navigation, not to local selection. A local
    // “back to chats” clears the session before the URL update is observed;
    // including activeSessionId here would immediately reopen that stale URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStandalone, urlSession])

  // Sync initialSessionId from parent (e.g. ProjectPage session tile click)
  useEffect(() => {
    if (initialSessionId && initialSessionId !== activeSessionId) {
      setActiveSessionId(initialSessionId)
    }
  }, [initialSessionId])

  // Load session: connect via AG-UI to get MessagesSnapshot, and fetch metadata for dataset filter
  useEffect(() => {
    setSavedToolTimings({})
    if (!activeSessionId) return
    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false
      return
    }
    reset()
    // Restore session-level dataset filter from metadata
    fetch(`${API}/chat/sessions/${activeSessionId}`)
      .then(r => r.ok ? r.json() : null)
      .then(session => {
        if (activeSessionIdRef.current !== activeSessionId) return
        setLoadedSessionTitle(typeof session?.title === 'string' ? session.title : '')
        setSavedToolTimings(persistedToolTimings(session?.messages))
        if (session?.datasetIds !== undefined) {
          setSelectedDatasetIds(session.datasetIds)
        }
        setSessionProjectId(session?.projectId || projectId || null)
        if (session?.toolIds !== undefined) setSelectedToolIds(session.toolIds)
        if (session?.skillIds !== undefined) setSelectedSkillIds(session.skillIds)
        if (session?.subagentIds !== undefined) setSelectedSubagentIds(session.subagentIds)
        if (session?.guardrailConfig?.disabled) setGuardrailDisabled(session.guardrailConfig.disabled)
        else setGuardrailDisabled([])
        const restoredQueue = Array.isArray(session?.queuedMessages) ? session.queuedMessages : []
        queuedMessagesRef.current = restoredQueue
        queuePausedRef.current = Boolean(session?.queuePaused)
        setQueuedMessages(restoredQueue)
        setQueuePaused(Boolean(session?.queuePaused))
        // Restore auto mode state
        if (session) {
          setAutoMode(!!session.autoMode)
          // Read the persisted counter so navigating away and back
          // doesn't reset the badge to 0/N.
          setAutoTurnsUsed(typeof session.autoTurnsUsed === 'number' ? session.autoTurnsUsed : 0)
          if (session.autoMessage) setAutoMessage(session.autoMessage)
          if (session.maxAutoTurns) setMaxAutoTurns(session.maxAutoTurns)
        }
      }).catch(() => {})
    // Load messages via MessagesSnapshot (handles both history and active run reconnection)
    checkAndReconnect(activeSessionId)
  }, [activeSessionId, reset, checkAndReconnect])

  // Load datasets for filter
  useEffect(() => {
    if (!hasDataPlugin) return
    fetch(`${API}/data/datasets`).then(r => r.ok ? r.json() : []).then(setAllDatasets).catch(() => {})
  }, [hasDataPlugin])

  // Load tools, skills, subagents for filters
  useEffect(() => {
    fetch(`${API}/tools`).then(r => r.ok ? r.json() : { tools: [] }).then(d => setAllTools(d.tools ?? [])).catch(() => {})
    fetch(`${API}/skills`).then(r => r.ok ? r.json() : []).then(setAllSkills).catch(() => {})
    fetch(`${API}/subagents/`).then(r => r.ok ? r.json() : []).then(setAllSubagents).catch(() => {})
    fetch(`${API}/guardrails`).then(r => r.ok ? r.json() : { guardrails: [] }).then(d => setAllGuardrails(d.guardrails ?? [])).catch(() => {})
  }, [])

  // Load project files for explorer
  const loadProjectFiles = useCallback(() => {
    if (!activeSessionId) {
      setProjectFiles([])
      setFileLoadError(null)
      return
    }
    setFileLoadError(null)
    const readJson = async (response: Response, failureMessage: string) => {
      if (!response.ok) throw new Error(failureMessage)
      try {
        return await response.json()
      } catch {
        throw new Error('Files service returned an invalid response')
      }
    }

    const sessionFilesRequest = fetch(`${API}/chat/sessions/${activeSessionId}/files`)
      .then(response => readJson(response, 'Session files could not be loaded'))
      .then(payload => {
        if (!payload || !Array.isArray(payload.files)) {
          throw new Error('Files service returned an invalid response')
        }
        return payload as { files: any[]; projectFiles?: any[] }
      })
    // Projects already expose their workspace through a stable endpoint.  Keep
    // it as a fallback so a project chat remains useful while an older backend
    // is restarted to pick up the session-output endpoint.
    const sharedProjectFilesRequest = effectiveProjectId
      ? fetch(`${API}/projects/${effectiveProjectId}/files`)
        .then(response => readJson(response, 'Project files could not be loaded'))
        .then(payload => {
          if (!payload || !Array.isArray(payload.project)) {
            throw new Error('Files service returned an invalid response')
          }
          return payload.project as any[]
        })
      : null

    Promise.allSettled([sessionFilesRequest, ...(sharedProjectFilesRequest ? [sharedProjectFilesRequest] : [])])
      .then(results => {
        const sessionResult = results[0]
        const projectResult = results[1]
        const fallbackProjectFiles = projectResult?.status === 'fulfilled' ? projectResult.value : []

        if (sessionResult.status === 'fulfilled') {
          const sessionFiles = sessionResult.value.files
          const sharedProjectFiles = Array.isArray(sessionResult.value.projectFiles)
            ? sessionResult.value.projectFiles
            : fallbackProjectFiles
          setProjectFiles(sharedProjectFiles.length && sessionFiles.length ? [
            { name: 'Session outputs', path: '__session_outputs__', is_dir: true, children: sessionFiles },
            { name: 'Project workspace', path: '__project_workspace__', is_dir: true, children: sharedProjectFiles },
          ] : (sessionFiles.length ? sessionFiles : sharedProjectFiles))
          return
        }

        // A project can still list the shared workspace when the dedicated
        // session-files route is temporarily unavailable (for example, before
        // a long-running local backend has been restarted after an upgrade).
        if (projectResult?.status === 'fulfilled') {
          setProjectFiles(fallbackProjectFiles)
          return
        }

        setProjectFiles([])
        const error = sessionResult.reason
        setFileLoadError(error instanceof Error ? error.message : 'Files could not be loaded')
      })
      .catch(() => {
        setProjectFiles([])
        setFileLoadError('Files could not be loaded')
      })
  }, [activeSessionId, effectiveProjectId])
  useEffect(() => { loadProjectFiles() }, [loadProjectFiles])

  // Plan approval recaps are represented by the focused plan surface instead.
  const filteredTimeline = useMemo(() => {
    return timeline.filter(e => {
      if (e.type !== 'message') return true
      return !isPlanApprovalRecap((e.item as AGUIMessage).content)
    })
  }, [timeline])

  // Windowed slice: only render the tail, expand on "load more"
  const windowedTimeline = useMemo(() => {
    if (filteredTimeline.length <= visibleCount) return filteredTimeline
    return filteredTimeline.slice(filteredTimeline.length - visibleCount)
  }, [filteredTimeline, visibleCount])

  const hasMore = filteredTimeline.length > visibleCount
  const windowedBlocks = useMemo(() => groupTranscript(windowedTimeline), [windowedTimeline])

  // Reset visible window when switching sessions
  useEffect(() => { setVisibleCount(WINDOW_SIZE) }, [activeSessionId])

  // Auto-scroll to bottom when new content arrives (only if already near bottom)
  const isNearBottomRef = useRef(true)
  useEffect(() => {
    if (isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, toolCalls])

  // Track scroll position to decide whether to auto-scroll
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const threshold = 150
    isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
  }, [])

  const createSession = async () => {
    try {
      const res = await fetch(`${API}/chat/sessions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat', project_id: projectId || null }),
      })
      if (res.ok) {
        const s = await res.json()
        setSessions(prev => [s, ...prev])
        setLoadedSessionTitle(s.title || 'New chat')
        setSessionProjectId(s.projectId || projectId || null)
        queuedMessagesRef.current = []
        queuePausedRef.current = false
        setQueuedMessages([])
        setQueuePaused(false)
        setActiveSessionId(s.id)
        reset()
      }
    } catch {}
  }

  const backToSessions = () => {
    setActiveSessionId(null)
    reset()
    if (onBackToSessions) {
      onBackToSessions()
      return
    }
    setSessionBrowserOpen(true)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text) return
    if (isRunning) {
      setInput('')
      const next = [...queuedMessagesRef.current, { id: crypto.randomUUID(), text, ts: Date.now() }]
      // A deliberate new message is also an explicit resume after Stop.
      commitQueue(next, false)
      return
    }
    setInput('')

    let sessionId = activeSessionId
    const isFirstMessage = messages.length === 0

    if (!sessionId) {
      // Create session on backend first (like ProjectPage does)
      try {
        const res = await fetch(`${API}/chat/sessions`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: sessionTitleFromMessage(text), project_id: projectId || null }),
        })
        if (!res.ok) return
        const s = await res.json()
        sessionId = s.id
        setSessions(prev => [s, ...prev])
        setLoadedSessionTitle(s.title || '')
        setSessionProjectId(s.projectId || projectId || null)
        queuedMessagesRef.current = []
        queuePausedRef.current = false
        setQueuedMessages([])
        setQueuePaused(false)
        skipNextLoadRef.current = true
        setActiveSessionId(sessionId)
      } catch { return }
    } else if (isFirstMessage) {
      // Update title for existing empty session
      const title = sessionTitleFromMessage(text)
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s))
      setLoadedSessionTitle(title)
      fetch(`${API}/chat/sessions/${sessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      }).catch(() => {})
    }

    // Pending-plan composer mode: the user's message doubles as plan feedback.
    // silent — this same message informs the agent, no synthetic one needed.
    if (latestPendingPlan) {
      await submitDecision(latestPendingPlan.id, 'changes_requested', text, true)
    }

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    if (queuePausedRef.current) commitQueue(queuedMessagesRef.current, false)
    sendMessage(sessionId!, history, text)
  }

  const removeQueuedMessage = useCallback((id: string) => {
    commitQueue(queuedMessagesRef.current.filter(message => message.id !== id), queuePausedRef.current)
  }, [commitQueue])

  const sendQueuedMessageNext = useCallback((id: string) => {
    const queue = queuedMessagesRef.current
    const item = queue.find(message => message.id === id)
    if (!item) return
    commitQueue([item, ...queue.filter(message => message.id !== id)], queuePausedRef.current)
  }, [commitQueue])

  const editQueuedMessage = useCallback((id: string) => {
    const item = queuedMessagesRef.current.find(message => message.id === id)
    if (!item) return
    const text = window.prompt('Edit queued message', item.text)?.trim()
    if (!text) return
    commitQueue(queuedMessagesRef.current.map(message => message.id === id ? { ...message, text } : message), queuePausedRef.current)
  }, [commitQueue])

  const resumeQueue = useCallback(() => {
    commitQueue(queuedMessagesRef.current, false)
    if (!isRunning) dispatchQueuedMessageRef.current()
  }, [commitQueue, isRunning])

  // Rename session (used by double-click on session selector)
  const _renameSession = (sessionId: string, title: string) => {
    setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s))
  }
  void _renameSession // suppress unused warning — wired to double-click handler

  // Sidebar resize handlers
  const startResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    resizingRef.current = true
    const startX = e.clientX
    const startWidth = sidebarWidth
    const onMove = (e: MouseEvent) => {
      if (!resizingRef.current) return
      const delta = startX - e.clientX
      setSidebarWidth(Math.max(360, Math.min(640, startWidth + delta)))
    }
    const onUp = () => { resizingRef.current = false; window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [sidebarWidth])

  const loadMlflowRuns = useCallback((sessionId: string) => {
    setMlflowLoading(true)
    setMlflowRuns([])
    fetch(`${API}/mlflow/runs?session_id=${sessionId}`)
      .then(r => r.ok ? r.json() : { runs: [] })
      .then(d => setMlflowRuns(d.runs || []))
      .catch(() => setMlflowRuns([]))
      .finally(() => setMlflowLoading(false))
  }, [])

  const openExperimentsPanel = () => {
    setSidebarTab('experiments')
    setSidebarCollapsed(false)
  }

  const saveSystemPrompt = () => {
    setSystemPrompt(promptDraft)
    localStorage.setItem('dataclaw_system_prompt', promptDraft)
    setPromptModalOpen(false)
  }

  const showPlansSidebar = hasPlansPlugin || plans.length > 0 || planToolResultCount > 0
  const showFilesSidebar = Boolean(activeSessionId)
  const showDatasetsSidebar = Boolean(activeSessionId) && (hasDataPlugin || allDatasets.length > 0)
  const showExperimentsSidebar = Boolean(activeSessionId)
  const showArtifactsSidebar = Boolean(activeSessionId) || hasArtifactsPlugin || artifactToolResultCount > 0
  const showCompatibilityApp = appItems.length > 0
  const displayedProjectFiles = useMemo(
    () => sortFileTree(projectFiles, fileSort, foldersFirst),
    [fileSort, foldersFirst, projectFiles],
  )
  const datasetOffCount = selectedDatasetIds === null ? 0 : Math.max(0, allDatasets.length - selectedDatasetIds.length)
  const scopeOffCount = [
    selectedToolIds === null ? 0 : Math.max(0, allTools.length - (selectedToolIds?.length || 0)),
    selectedSkillIds === null ? 0 : Math.max(0, allSkills.length - (selectedSkillIds?.length || 0)),
    selectedSubagentIds === null ? 0 : Math.max(0, allSubagents.length - (selectedSubagentIds?.length || 0)),
    guardrailDisabled.length,
  ].reduce((sum, count) => sum + count, 0)
  // Insights is core (viz layer) — the sidebar is always available.
  const showSidebar = true
  const panelOpen = !sidebarCollapsed
  const compactLayout = viewportWidth <= 1160
  const panelOverlay = panelOpen && viewportWidth <= 1400
  const panelWidth = compactLayout ? 'calc(100% - 46px)' : sidebarWidth
  const edgeWidth = compactLayout ? '100%' : sidebarWidth + 46
  const compactToolbar = viewportWidth <= 1160
  const narrowToolbar = viewportWidth <= 760
  // Keep the directory, transcript, and composer on one generous reading
  // edge. The desktop value scales with the workspace instead of leaving a
  // wide display feeling like an edge-to-edge document.
  const chatHorizontalGutter = narrowToolbar ? '28px' : compactToolbar ? '56px' : 'clamp(72px, 5vw, 120px)'
  const showSessionBrowser = isStandalone && sessionBrowserOpen
  const activeSessionTitle = sessions.find(session => session.id === activeSessionId)?.title || loadedSessionTitle
  const toolbarSessionTitle = activeSessionTitle || (isStandalone ? 'Choose a chat' : 'New chat')
  const panelTitle = sidebarTab === 'plans'
    ? 'Plans'
        : sidebarTab === 'files'
          ? 'Files'
          : sidebarTab === 'datasets'
            ? 'Datasets'
          : sidebarTab === 'experiments'
            ? 'Experiments'
          : sidebarTab === 'artifacts'
        ? 'Reports'
        : sidebarTab === 'scope'
          ? 'Scope'
          : 'Scratch'

  useEffect(() => {
    if (sidebarTab === 'experiments' && activeSessionId) loadMlflowRuns(activeSessionId)
  }, [sidebarTab, activeSessionId, loadMlflowRuns])

  useEffect(() => {
    if (sidebarTab !== 'app' || showCompatibilityApp) return
    if (showArtifactsSidebar) setSidebarTab('artifacts')
    else if (showPlansSidebar) setSidebarTab('plans')
    else if (showFilesSidebar) setSidebarTab('files')
    else setSidebarTab('plans')
  }, [sidebarTab, showCompatibilityApp, showArtifactsSidebar, showPlansSidebar, showFilesSidebar])

  return (
    <PlansContext.Provider value={plansCtx}>
    <div style={{ display: 'flex', height: '100%', position: 'relative' }}>
      <style>{`
        textarea.dataclaw-plan-feedback-composer::placeholder,
        .dataclaw-plan-feedback-composer textarea::placeholder {
          color: #98a2b3;
          font-style: italic;
        }
      `}</style>
      {/* Main chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* A session browser is a directory, not an empty chat. Keep the
            session-specific toolbar out of it until the user opens a chat. */}
        {!showSessionBrowser && <div style={{ height: 50, minHeight: 50, padding: '0 16px', borderBottom: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg)' }}>
          <Button type="text" icon={<ArrowLeftOutlined />} aria-label="Back to sessions" onClick={backToSessions} style={{ color: 'var(--muted)', paddingInline: 6 }} />
          <span title={activeSessionTitle || undefined} style={{ flex: '0 1 auto', minWidth: 0, maxWidth: narrowToolbar ? '36vw' : compactToolbar ? '44vw' : 520, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink)', fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>{toolbarSessionTitle}</span>

          <div style={{ flex: 1 }} />
          <div style={{ minWidth: 0, display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end' }}>
            <span title={effectiveProjectId ? projectName || 'Project workspace' : 'Independent chat'} style={{ flex: '0 1 auto', minWidth: 0, maxWidth: narrowToolbar ? 112 : compactToolbar ? 160 : 210, display: 'inline-flex', alignItems: 'center', gap: 7, padding: '4px 11px', border: '1px solid var(--line)', borderRadius: 999, color: effectiveProjectId ? 'var(--ink)' : 'var(--muted)', background: 'var(--bg)', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden' }}>
              {effectiveProjectId && <span style={{ flex: '0 0 auto', color: 'var(--faint)', fontFamily: 'var(--mono)', fontSize: 9.5, fontWeight: 600, letterSpacing: '.05em' }}>PROJECT</span>}
              <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: effectiveProjectId ? 600 : 500 }}>{effectiveProjectId ? projectName || 'workspace' : 'Independent'}</span>
            </span>
            {attentionPlan && (
              <Tooltip title={attentionPlan.name || 'Active plan'} placement="bottom">
                <Button size="small" onClick={() => { setSidebarTab('plans'); setSidebarCollapsed(false); focusPlan(attentionPlan.id) }} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flex: '0 1 auto', minWidth: 0, maxWidth: narrowToolbar ? 148 : compactToolbar ? 230 : 360, height: 'auto', padding: '4px 11px', borderRadius: 999, borderColor: attentionPlan.status === 'pending' ? '#f0d29a' : attentionPlan.status === 'running' ? '#c6dafc' : 'var(--line)', color: attentionPlan.status === 'pending' ? '#8a5a00' : 'var(--ink)', background: attentionPlan.status === 'pending' ? '#fff8ec' : attentionPlan.status === 'running' ? 'var(--accent-soft)' : 'var(--bg)', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                  <span aria-hidden="true" style={{ flex: '0 0 auto', width: 7, height: 7, borderRadius: '50%', background: attentionPlan.status === 'pending' ? 'var(--warn)' : attentionPlan.status === 'running' ? 'var(--accent)' : 'var(--good)' }} />
                  <span style={{ flex: '0 0 auto' }}>Plan</span>
                  <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', fontWeight: 600 }}>{conciseTitle(attentionPlan.name || 'active', narrowToolbar ? 16 : compactToolbar ? 28 : 42)}</span>
                  {!narrowToolbar && attentionPlanProgress && <span style={{ flex: '0 0 auto', color: 'var(--faint)', fontVariantNumeric: 'tabular-nums' }}>{attentionPlanProgress}</span>}
                  {!narrowToolbar && attentionPlanStatus && <span style={{ flex: '0 0 auto' }}>{attentionPlanStatus}</span>}
                  {plans.length > 1 && <span style={{ flex: '0 0 auto', padding: '1px 6px', border: '1px solid var(--line)', borderRadius: 99, color: 'var(--muted)', fontFamily: 'var(--mono)', fontSize: 10 }}>+{plans.length - 1}</span>}
                </Button>
              </Tooltip>
            )}
            {!narrowToolbar && (
              <Button size="small" type="text" onClick={() => { setSidebarTab('scope'); setSidebarCollapsed(false) }} style={{ height: 'auto', padding: '4px 11px', border: '1px solid var(--line)', borderRadius: 999, color: scopeOffCount ? 'var(--warn)' : 'var(--muted)', background: scopeOffCount ? 'var(--warn-soft)' : 'var(--bg)', whiteSpace: 'nowrap' }}>
                Scope · {scopeOffCount ? `${scopeOffCount} off` : 'All'}
              </Button>
            )}
            {/* Auto mode is session-level execution control, not a plans-only feature. */}
            {!narrowToolbar && (
              <Tooltip title={autoMode ? `Auto mode ON (${autoTurnsUsed}/${maxAutoTurns} turns)` : 'Enable auto mode'}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: 4, color: autoMode ? 'var(--accent)' : 'var(--faint)' }}>
                  <Switch size="small" checked={autoMode}
                    onChange={async (checked) => {
                      setAutoMode(checked)
                      setAutoTurnsUsed(0)
                      if (activeSessionId) {
                        fetch(`${API}/chat/sessions/${activeSessionId}`, {
                          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ autoMode: checked }),
                        }).catch(() => {})
                      }
                    }}
                  />
                  <span style={{ fontSize: 12, cursor: 'pointer' }}
                    onClick={() => { setAutoMessageDraft(autoMessage); setMaxAutoTurnsDraft(maxAutoTurns); setAutoMessageModalOpen(true) }}>
                    Auto
                  </span>
                  {autoMode && (
                    <Button size="small" type="text" icon={<EditOutlined />}
                      style={{ padding: '0 2px', height: 18, width: 18, minWidth: 18, fontSize: 10, color: 'var(--faint)' }}
                      onClick={() => { setAutoMessageDraft(autoMessage); setMaxAutoTurnsDraft(maxAutoTurns); setAutoMessageModalOpen(true) }} />
                  )}
                </div>
              </Tooltip>
            )}

            <Tooltip title="System prompt">
              <Button size="small" type="text"
                icon={<SettingOutlined />}
                onClick={() => { setPromptDraft(systemPrompt); setPromptModalOpen(true) }} style={{ color: 'var(--muted)' }} />
            </Tooltip>
          </div>
        </div>}

        {/* Messages */}
        <div ref={scrollContainerRef} onScroll={handleScroll} style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: showSessionBrowser ? `42px ${chatHorizontalGutter}` : `26px ${chatHorizontalGutter} 12px` }}>
          {showSessionBrowser ? (
            <SessionBrowser sessions={sessions} onOpen={setActiveSessionId} onCreate={createSession} />
          ) : filteredTimeline.length === 0 && !isRunning ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Empty description="Start a conversation" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            <div style={{ width: '100%', maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '0 auto' }}>
              {hasMore && (
                <div style={{ textAlign: 'center', padding: '8px 0' }}>
                  <Button size="small" type="link" onClick={() => setVisibleCount(prev => prev + WINDOW_SIZE)}>
                    Load earlier messages ({filteredTimeline.length - visibleCount} more)
                  </Button>
                </div>
              )}
              {windowedBlocks.map(block => (
                <div key={block.kind === 'activity' ? block.group.id : block.entry.item.id} style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 56px' }}>
                  {block.kind === 'activity'
                    ? <TurnActivity group={block.group} onFileClick={previewFile} sessionId={activeSessionId} />
                    : (block.entry.item as AGUIMessage).role === 'compaction'
                    ? <CompactionDivider message={block.entry.item as AGUIMessage} />
                    : <MessageBubble message={block.entry.item as AGUIMessage} onFileClick={previewFile} />
                  }
                </div>
              ))}
              {queuedMessages.map((message, index) => (
                <QueuedBubble
                  key={message.id}
                  message={message}
                  position={index}
                  paused={queuePaused}
                  onEdit={editQueuedMessage}
                  onSendNext={sendQueuedMessageNext}
                  onRemove={removeQueuedMessage}
                />
              ))}
              {/* Typing indicator */}
              {isRunning && (() => {
                const last = filteredTimeline[filteredTimeline.length - 1]
                if (last?.type === 'message' && (last.item as AGUIMessage).role === 'assistant') return false
                return true
              })() && (
                <div style={{ display: 'flex', gap: 6, padding: '8px 0', alignItems: 'center' }}>
                  <div style={{ display: 'flex', gap: 3 }}>
                    {[0, 1, 2].map(i => (
                      <div key={i} style={{
                        width: 7, height: 7, borderRadius: '50%', background: '#bbb',
                        animation: 'dataclaw-typing 1.2s infinite',
                        animationDelay: `${i * 0.2}s`,
                      }} />
                    ))}
                  </div>
                  <span style={{ fontSize: 12, color: '#999' }}>{reconnecting ? 'Reconnecting...' : 'Dataclaw is thinking...'}</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
          {error && <Alert type="error" message={error} style={{ maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '12px auto' }} closable />}
        </div>

        {/* Input */}
        {!showSessionBrowser && <div style={{ padding: `10px ${chatHorizontalGutter} 14px`, borderTop: '1px solid var(--line)', background: 'var(--bg)' }}>
          {latestPendingPlan && (
            <div style={{ maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '0 auto 8px', padding: '8px 10px', border: '1px solid #fedf89', borderRadius: 8, background: 'var(--warn-soft)', color: 'var(--warn)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 8 }} role="status">
              <SafetyOutlined aria-hidden="true" />
              <span><b>Plan {latestPendingPlan.name || 'review'}</b> awaits your review.</span>
              <Button type="link" size="small" onClick={() => focusPlan(latestPendingPlan.id)} style={{ marginLeft: 'auto', paddingInline: 0 }}>View plan</Button>
              <Button size="small" onClick={() => submitDecision(latestPendingPlan.id, 'approved')}>Approve</Button>
              <Button size="small" danger onClick={() => submitDecision(latestPendingPlan.id, 'denied')}>Deny</Button>
            </div>
          )}
          {queuePaused && queuedMessages.length > 0 && (
            <div style={{ maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '0 auto 8px', padding: '8px 10px', border: '1px solid #d0d5dd', borderRadius: 8, background: '#f7f8fa', color: '#475467', fontSize: 12, display: 'flex', alignItems: 'center', gap: 8 }} role="status">
              <PauseOutlined aria-hidden="true" />
              <span>Queue paused — {queuedMessages.length} message{queuedMessages.length === 1 ? '' : 's'} held.</span>
              <Button type="link" size="small" icon={<PlayCircleOutlined />} onClick={resumeQueue} style={{ marginLeft: 'auto', paddingInline: 0 }}>Resume</Button>
            </div>
          )}
          <div style={{ width: '100%', maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '0 auto', display: 'flex', gap: 10, alignItems: 'flex-end' }}>
            <Input.TextArea value={input} onChange={e => setInput(e.target.value)}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder={composerPlaceholder}
              className={latestPendingPlan ? 'dataclaw-plan-feedback-composer' : undefined}
              autoSize={{ minRows: 1, maxRows: 6 }}
              style={{ borderRadius: 10 }} />
            {isRunning ? (
              <>
                <Button danger icon={<StopOutlined />} onClick={() => {
                  if (activeSessionId) cancelRun(activeSessionId)
                  if (queuedMessagesRef.current.length > 0) commitQueue(queuedMessagesRef.current, true)
                  if (autoMode) {
                    setAutoMode(false)
                    if (activeSessionId) {
                      fetch(`${API}/chat/sessions/${activeSessionId}`, {
                        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ autoMode: false }),
                      }).catch(() => {})
                    }
                  }
                }}
                  style={{ borderRadius: 10, height: 36 }}>Stop</Button>
                <Button type="primary" onClick={handleSend} style={{ borderRadius: 10, height: 36 }}>Queue ↵</Button>
              </>
            ) : (
              <Button type="primary" icon={<SendOutlined />} onClick={handleSend}
                style={{ borderRadius: 10, minWidth: 44, height: 32 }} />
            )}
          </div>
          {isRunning && <div style={{ maxWidth: CHAT_SURFACE_MAX_WIDTH, margin: '6px auto 0', color: 'var(--faint)', fontSize: 11, textAlign: 'right' }}>↵ send — queues during a run · ⇧↵ newline</div>}
        </div>}
      </div>

      {/* Companion panel and persistent section rail. */}
      {!showSessionBrowser && showSidebar && (
        <div style={{
          display: 'flex',
          flexShrink: 0,
          ...(panelOverlay ? {
            position: 'absolute',
            top: 0,
            right: 0,
            bottom: 0,
            width: edgeWidth,
            zIndex: 20,
            boxShadow: '-18px 0 42px rgba(15, 23, 42, 0.16)',
          } : {}),
        }}>
          {/* Resize handle */}
          {panelOpen && !panelOverlay && (
            <div onMouseDown={startResize} style={{
              width: 4, cursor: 'col-resize', background: 'transparent', flexShrink: 0,
              borderLeft: '1px solid #f0f0f0',
            }}
              onMouseEnter={e => (e.currentTarget.style.background = '#ddd')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            />
          )}
        {panelOpen && <aside aria-label="Session panel" style={{
          width: panelWidth,
          minWidth: 0,
          flex: '0 1 auto',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          background: 'var(--bg)',
          transition: 'width 0.2s',
          height: panelOverlay ? '100%' : undefined,
          borderLeft: '1px solid var(--line)',
        }}>
          <div style={{ flex: '0 0 auto', minWidth: 0, display: 'flex', alignItems: 'center', gap: 8, minHeight: 50, padding: '8px 12px 8px 18px', borderBottom: '1px solid var(--line)' }}>
            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--ink)', fontSize: 13, fontWeight: 650 }}>{panelTitle}</span>
            <Button type="text" size="small" onClick={() => { setPlanReaderExpanded(false); setSidebarCollapsed(true) }} aria-label="Close side panel" style={{ marginLeft: 'auto', color: 'var(--muted)' }}>×</Button>
          </div>

          <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', padding: 12 }}>
            {/* Plans tab — read-only companion view; decisions live in the plan card */}
            {sidebarTab === 'plans' && showPlansSidebar && (
              <PlanPanel plans={plans} focusedPlan={focusedPlan} onFileClick={previewFile}
                expanded={planReaderExpanded}
                onExpandedChange={setPlanReaderExpanded}
                onViewExperiments={activeSessionId ? openExperimentsPanel : undefined} />
            )}

            {/* Files tab */}
            {sidebarTab === 'files' && showFilesSidebar && (
              <div style={{ minWidth: 0, maxWidth: '100%' }}>
                <div style={{ display: 'flex', minWidth: 0, alignItems: 'center', justifyContent: 'space-between', gap: 6, marginBottom: 8 }}>
                  <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)', fontSize: 11 }}>{effectiveProjectId ? `Project + session workspace · ${projectName || 'project'}` : 'Session workspace'}</span>
                  <Button size="small" type="text" icon={<ReloadOutlined />} onClick={loadProjectFiles} aria-label="Refresh files" style={{ flex: '0 0 auto', fontSize: 11 }} />
                </div>
                {projectFiles.length > 0 && <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                  <Button size="small" type={foldersFirst ? 'default' : 'text'} onClick={() => setFoldersFirst(value => !value)} style={{ fontSize: 10.5 }}>
                    {foldersFirst ? 'Folders first' : 'Mixed items'}
                  </Button>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--muted)', fontSize: 10.5 }}>
                    Sort
                    <select aria-label="Sort files" value={fileSort} onChange={event => setFileSort(event.target.value as FileSort)} style={{ height: 24, border: '1px solid var(--line)', borderRadius: 5, padding: '0 5px', color: 'var(--ink)', background: 'var(--bg)', fontSize: 10.5 }}>
                      <option value="name">Name</option>
                      <option value="size">Largest</option>
                    </select>
                  </label>
                </div>}
                {fileLoadError ? (
                  <Alert type="warning" showIcon message="Files unavailable" description={fileLoadError} />
                ) : displayedProjectFiles.length ? (
                  <ChatFileTree items={displayedProjectFiles} depth={0} onPreview={(path, name) => setFilePreviewTarget({ name, path })} />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No files in this workspace yet" />
                )}
              </div>
            )}

            {/* Artifacts tab — durable published reports/dashboards with version history */}
            {sidebarTab === 'artifacts' && showArtifactsSidebar && (
              <ArtifactPanel
                sessionId={activeSessionId}
                refreshKey={artifactRefreshKey}
                focusArtifactId={latestPublishedArtifact?.artifact_id ?? null}
                focusVersion={latestPublishedArtifact?.version ?? null}
                focusKey={artifactRefreshKey}
                scratchReports={scratchReports}
                onCountsChange={setReportCounts}
              />
            )}

            {sidebarTab === 'datasets' && showDatasetsSidebar && (
              <DatasetPanel
                projectName={effectiveProjectId ? projectName : null}
                datasets={allDatasets}
                selectedIds={selectedDatasetIds}
                onChange={updateDatasetFilter}
              />
            )}

            {sidebarTab === 'experiments' && showExperimentsSidebar && activeSessionId && (
              <SessionExperimentsPanel
                sessionId={activeSessionId}
                runs={mlflowRuns}
                loading={mlflowLoading}
                onRefresh={() => loadMlflowRuns(activeSessionId)}
              />
            )}

            {/* Scratch tab — compatibility view for loose metrics/charts. */}
            {sidebarTab === 'app' && showCompatibilityApp && (
              <div>
                {activeSessionId && appItems.length > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                    <Button size="small" icon={<ExportOutlined />}
                      href={`/app/${activeSessionId}`} target="_blank">
                      Open
                    </Button>
                  </div>
                )}
                <AppView items={appItems} layout={appLayout} editable onLayoutChange={saveAppLayout} />
              </div>
            )}

            {sidebarTab === 'scope' && (
              <ScopePanel
                projectName={effectiveProjectId ? projectName : null}
                tools={allTools} selectedToolIds={selectedToolIds} onToolChange={updateToolFilter}
                skills={allSkills} selectedSkillIds={selectedSkillIds} onSkillChange={updateSkillFilter}
                subagents={allSubagents} selectedSubagentIds={selectedSubagentIds} onSubagentChange={updateSubagentFilter}
                guardrails={allGuardrails} disabledGuardrailIds={guardrailDisabled} onGuardrailChange={updateGuardrailConfig}
              />
            )}
          </div>
        </aside>}
        <aside aria-label="Session panel sections" style={{
          width: 46,
          flex: '0 0 46px',
          overflow: 'hidden',
          background: 'var(--bg)',
          borderLeft: '1px solid var(--line)',
          color: 'var(--ink)',
        }}>
          <PanelRail
            active={panelOpen ? sidebarTab : ''}
            planCount={plans.length || planToolResultCount}
            planStatus={planStatusTone}
            reportCount={reportCounts.published}
            reportRunning={toolCalls.some(call => ['build_report', 'report_design_report', 'report_publish', 'publish_artifact'].includes(toolBaseName(call.name)) && call.status === 'calling')}
            scopeOffCount={scopeOffCount}
            datasetOffCount={datasetOffCount}
            showFiles={showFilesSidebar}
            showDatasets={showDatasetsSidebar}
            showExperiments={showExperimentsSidebar}
            onOpen={tab => {
              if (panelOpen && sidebarTab === tab) {
                setSidebarCollapsed(true)
                return
              }
              setPlanReaderExpanded(false)
              setSidebarTab(tab)
              setSidebarCollapsed(false)
            }}
          />
        </aside>
        </div>
      )}

      {/* System prompt modal */}
      <Modal title="System Prompt" open={promptModalOpen} onCancel={() => setPromptModalOpen(false)}
        onOk={saveSystemPrompt} okText="Save" width={600}>
        <Input.TextArea value={promptDraft} onChange={e => setPromptDraft(e.target.value)}
          rows={10} style={{ fontFamily: 'monospace', fontSize: 13 }}
          placeholder="Custom system prompt (leave empty for default)..." />
        {promptDraft && (
          <Button size="small" style={{ marginTop: 8 }} onClick={() => setPromptDraft('')}>Clear</Button>
        )}
      </Modal>

      {/* Auto message editor modal */}
      <Modal title="Auto Mode Settings" open={autoMessageModalOpen} onCancel={() => setAutoMessageModalOpen(false)}
        onOk={() => {
          const msg = autoMessageDraft.trim() || DEFAULT_AUTO_MESSAGE
          const turns = Math.max(1, Math.min(100, maxAutoTurnsDraft || 10))
          setAutoMessage(msg)
          setMaxAutoTurns(turns)
          setAutoMessageModalOpen(false)
          if (activeSessionId) {
            fetch(`${API}/chat/sessions/${activeSessionId}`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ autoMessage: msg, maxAutoTurns: turns }),
            }).catch(() => {})
          }
        }}
        okText="Save" width={600}>
        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 12, fontWeight: 500, display: 'block', marginBottom: 4 }}>Max auto turns</label>
          <Input type="number" min={1} max={100} value={maxAutoTurnsDraft}
            onChange={e => setMaxAutoTurnsDraft(parseInt(e.target.value) || 10)}
            style={{ width: 120 }} />
          <span style={{ fontSize: 11, color: '#888', marginLeft: 8 }}>How many turns the agent will run autonomously</span>
        </div>
        <div>
          <label style={{ fontSize: 12, fontWeight: 500, display: 'block', marginBottom: 4 }}>Continuation message</label>
          <p style={{ fontSize: 12, color: '#888', marginBottom: 8 }}>
            This message is sent to the agent after each turn in auto mode.
          </p>
          <Input.TextArea value={autoMessageDraft} onChange={e => setAutoMessageDraft(e.target.value)}
            rows={6} style={{ fontFamily: 'monospace', fontSize: 13 }}
            placeholder="Custom auto-continue message..." />
          {autoMessageDraft !== DEFAULT_AUTO_MESSAGE && (
            <Button size="small" style={{ marginTop: 8 }} onClick={() => setAutoMessageDraft(DEFAULT_AUTO_MESSAGE)}>Reset to Default</Button>
          )}
        </div>
      </Modal>

      {/* File preview modal */}
      <FileViewerModal file={filePreviewTarget} onClose={() => setFilePreviewTarget(null)} />

      {/* Tools filter modal */}
      <Modal title="Chat Tools" open={toolModalOpen} onCancel={() => setToolModalOpen(false)} footer={[
        <Button key="none" onClick={() => updateToolFilter([])}>Remove all</Button>,
        <Button key="all" onClick={() => updateToolFilter(null)}>Use all tools</Button>,
        <Button key="done" type="primary" onClick={() => setToolModalOpen(false)}>Done</Button>,
      ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '50vh', overflow: 'auto' }}>
          {allTools.map(t => {
            const isOn = selectedToolIds === null || selectedToolIds.includes(t.name)
            return (
              <Card key={t.name} size="small" style={{ borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch size="small" checked={isOn} onChange={on => {
                    const current = selectedToolIds ?? allTools.map(x => x.name)
                    updateToolFilter(on ? [...current, t.name] : current.filter(x => x !== t.name))
                  }} />
                  <span style={{ fontWeight: 500, fontSize: 13, fontFamily: 'monospace' }}>{t.name}</span>
                  {t.source && <Tag style={{ fontSize: 10 }}>{t.source}</Tag>}
                </div>
              </Card>
            )
          })}
        </div>
      </Modal>

      {/* Skills filter modal */}
      <Modal title="Chat Skills" open={skillModalOpen} onCancel={() => setSkillModalOpen(false)} footer={[
        <Button key="none" onClick={() => updateSkillFilter([])}>Remove all</Button>,
        <Button key="all" onClick={() => updateSkillFilter(null)}>Use all skills</Button>,
        <Button key="done" type="primary" onClick={() => setSkillModalOpen(false)}>Done</Button>,
      ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '50vh', overflow: 'auto' }}>
          {allSkills.map(s => {
            const isOn = selectedSkillIds === null || selectedSkillIds.includes(s.id)
            return (
              <Card key={s.id} size="small" style={{ borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch size="small" checked={isOn} onChange={on => {
                    const current = selectedSkillIds ?? allSkills.map(x => x.id)
                    updateSkillFilter(on ? [...current, s.id] : current.filter(x => x !== s.id))
                  }} />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{s.name}</span>
                  {s.description && <span style={{ fontSize: 11, color: '#888' }}>{s.description}</span>}
                </div>
              </Card>
            )
          })}
        </div>
      </Modal>

      {/* Subagents filter modal */}
      <Modal title="Chat Subagents" open={subagentModalOpen} onCancel={() => setSubagentModalOpen(false)} footer={[
        <Button key="none" onClick={() => updateSubagentFilter([])}>Remove all</Button>,
        <Button key="all" onClick={() => updateSubagentFilter(null)}>Use all subagents</Button>,
        <Button key="done" type="primary" onClick={() => setSubagentModalOpen(false)}>Done</Button>,
      ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '50vh', overflow: 'auto' }}>
          {allSubagents.map(sa => {
            const isOn = selectedSubagentIds === null || selectedSubagentIds.includes(sa.id)
            return (
              <Card key={sa.id} size="small" style={{ borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch size="small" checked={isOn} onChange={on => {
                    const current = selectedSubagentIds ?? allSubagents.map(x => x.id)
                    updateSubagentFilter(on ? [...current, sa.id] : current.filter(x => x !== sa.id))
                  }} />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{sa.name}</span>
                  {sa.agent_type && <Tag style={{ fontSize: 10 }}>{sa.agent_type}</Tag>}
                </div>
              </Card>
            )
          })}
        </div>
      </Modal>

      {/* Guardrails config modal */}
      <Modal title="Guardrails" open={guardrailModalOpen} onCancel={() => setGuardrailModalOpen(false)} footer={[
        <Button key="none" onClick={() => updateGuardrailConfig(allGuardrails.map((g: any) => g.id))}>Disable all</Button>,
        <Button key="all" onClick={() => updateGuardrailConfig([])}>Enable all</Button>,
        <Button key="done" type="primary" onClick={() => setGuardrailModalOpen(false)}>Done</Button>,
      ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '50vh', overflow: 'auto' }}>
          {allGuardrails.map((g: any) => {
            const isOn = !guardrailDisabled.includes(g.id)
            return (
              <Card key={g.id} size="small" style={{ borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch size="small" checked={isOn} onChange={on => {
                    updateGuardrailConfig(on
                      ? guardrailDisabled.filter(x => x !== g.id)
                      : [...guardrailDisabled, g.id]
                    )
                  }} />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{g.id.replace(/_/g, ' ')}</span>
                  <Tag style={{ fontSize: 10 }}>{g.phase}</Tag>
                  <Tag style={{ fontSize: 10 }} color={g.mode === 'user_approval' ? 'orange' : 'blue'}>{g.mode === 'user_approval' ? 'approval' : 'auto'}</Tag>
                </div>
              </Card>
            )
          })}
        </div>
      </Modal>
    </div>
    </PlansContext.Provider>
  )
}

function PanelRail({ active, planCount, planStatus, reportCount, reportRunning, scopeOffCount, datasetOffCount, showFiles, showDatasets, showExperiments, onOpen }: {
  active: string
  planCount: number
  planStatus: 'pending' | 'running' | 'complete' | null
  reportCount: number
  reportRunning: boolean
  scopeOffCount: number
  datasetOffCount: number
  showFiles: boolean
  showDatasets: boolean
  showExperiments: boolean
  onOpen: (tab: 'plans' | 'files' | 'artifacts' | 'datasets' | 'experiments' | 'scope') => void
}) {
  const item = (tab: 'plans' | 'files' | 'artifacts' | 'datasets' | 'experiments' | 'scope', label: string, icon: ReactNode, badge?: number, status?: 'pending' | 'running' | 'complete' | null) => (
    <Tooltip title={label} placement="left" key={tab}>
      <button type="button" onClick={() => onOpen(tab)} aria-label={label} aria-pressed={active === tab} style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, width: 34, minHeight: 62, padding: '9px 3px 10px', border: 0, borderRadius: 9, color: active === tab ? 'var(--accent)' : 'var(--faint)', background: active === tab ? 'var(--accent-soft)' : 'transparent', cursor: 'pointer' }}>
        {status && <span aria-label={status === 'pending' ? 'Needs review' : status === 'running' ? 'Running' : 'Up to date'} style={{ position: 'absolute', top: 5, left: 5, width: 6, height: 6, borderRadius: '50%', background: status === 'pending' ? 'var(--warn)' : status === 'running' ? 'var(--accent)' : 'var(--good)', boxShadow: status === 'running' ? '0 0 0 3px var(--accent-soft)' : undefined }} />}
        <span style={{ fontSize: 13, lineHeight: 1 }}>{icon}</span>
        <span style={{ writingMode: 'vertical-rl', fontSize: 10, fontWeight: 600, letterSpacing: '.05em', lineHeight: 1 }}>{label}</span>
        {badge ? <span style={{ position: 'absolute', right: -2, top: 2, minWidth: 13, height: 13, padding: '0 3px', borderRadius: 7, color: '#fff', background: tab === 'scope' ? 'var(--warn)' : 'var(--accent)', fontSize: 9, lineHeight: '13px' }}>{badge}</span> : null}
      </button>
    </Tooltip>
  )
  return <nav aria-label="Session panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '12px 6px' }}>{item('plans', 'Plans', <FileTextOutlined />, planCount, planStatus)}{showFiles && item('files', 'Files', <FolderOutlined />)}{item('artifacts', 'Reports', <ExportOutlined />, reportCount, reportRunning ? 'running' : reportCount ? 'complete' : null)}{showDatasets && item('datasets', 'Datasets', <DatabaseOutlined />, datasetOffCount)}{showExperiments && item('experiments', 'Experiments', <ExperimentOutlined />)}{item('scope', 'Scope', <SettingOutlined />, scopeOffCount)}</nav>
}

function SessionBrowser({ sessions, onOpen, onCreate }: {
  sessions: Session[]
  onOpen: (id: string) => void
  onCreate: () => void
}) {
  return (
    <section aria-label="Independent chat sessions" style={{ width: '100%', maxWidth: 760, margin: '0 auto', padding: '12px 0 28px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
        <div>
          <h1 style={{ margin: 0, color: 'var(--ink)', fontSize: 18, fontWeight: 650 }}>Independent chats</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: 12 }}>Personal sessions that are not part of a project.</p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={onCreate} style={{ marginLeft: 'auto' }}>New chat</Button>
      </div>
      {sessions.length === 0 ? (
        <Empty description="No independent chats yet" image={Empty.PRESENTED_IMAGE_SIMPLE}>
          <Button type="primary" onClick={onCreate}>Start a chat</Button>
        </Empty>
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {sessions.map(session => (
            <button key={session.id} type="button" onClick={() => onOpen(session.id)} style={{ display: 'flex', minWidth: 0, alignItems: 'center', gap: 12, width: '100%', padding: '13px 14px', border: '1px solid var(--line)', borderRadius: 9, color: 'var(--ink)', background: 'var(--bg)', cursor: 'pointer', textAlign: 'left' }}>
              <MessageOutlined style={{ flex: '0 0 auto', color: 'var(--accent)' }} />
              <span title={session.title || 'Untitled chat'} style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13, fontWeight: 600 }}>{conciseTitle(session.title || 'Untitled chat', 56)}</span>
              <span style={{ flex: '0 0 auto', color: 'var(--faint)', fontSize: 11 }}>{formatSessionDate(session.createdAt)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}

function formatSessionDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function conciseTitle(value: string, limit: number) {
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (normalized.length <= limit) return normalized
  const clipped = normalized.slice(0, Math.max(1, limit - 1))
  const wordBoundary = clipped.lastIndexOf(' ')
  return `${(wordBoundary > Math.floor(limit * 0.55) ? clipped.slice(0, wordBoundary) : clipped).trim()}…`
}

function sessionTitleFromMessage(message: string) {
  // A session needs a useful label, not the first full sentence of a request.
  // Keep the original prompt in the transcript; the label is only navigation.
  return conciseTitle(message.split(/\r?\n/, 1)[0] || message, 42)
}

function DatasetPanel({ projectName, datasets, selectedIds, onChange }: {
  projectName: string | null
  datasets: any[]
  selectedIds: string[] | null
  onChange: (ids: string[] | null) => void
}) {
  const enabledCount = selectedIds === null ? datasets.length : selectedIds.length
  return (
    <section aria-label="Session datasets" style={{ color: 'var(--ink)' }}>
      <p style={{ margin: '0 0 14px', color: 'var(--muted)', fontSize: 12, lineHeight: 1.45 }}>
        {projectName ? <>Project context · <b>{projectName}</b><br />Choose the datasets available to this session.</> : 'Choose the datasets available to this independent session.'}
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ color: 'var(--muted)', fontSize: 11 }}>{enabledCount} of {datasets.length} enabled</span>
        <Button size="small" type="text" onClick={() => onChange(null)} style={{ marginLeft: 'auto', fontSize: 11 }}>Use all</Button>
        <Button size="small" type="text" onClick={() => onChange([])} style={{ fontSize: 11 }}>Clear</Button>
      </div>
      {datasets.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No datasets available" />
      ) : (
        <div style={{ display: 'grid', gap: 6 }}>
          {datasets.map(dataset => {
            const enabled = selectedIds === null || selectedIds.includes(dataset.id)
            const name = dataset.name || dataset.title || humanizeScopeId(dataset.id)
            return (
              <div key={dataset.id} style={{ display: 'flex', minWidth: 0, alignItems: 'center', gap: 9, padding: '9px 10px', border: '1px solid var(--line)', borderRadius: 8, background: 'var(--bg)' }}>
                <Switch size="small" checked={enabled} onChange={checked => {
                  const current = selectedIds === null ? datasets.map(item => item.id) : selectedIds
                  onChange(checked ? [...current, dataset.id] : current.filter(id => id !== dataset.id))
                }} />
                <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                  <div title={name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, fontWeight: 600 }}>{name}</div>
                  <div title={dataset.id} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--faint)', fontFamily: 'var(--mono)', fontSize: 10 }}>{dataset.id}</div>
                  {dataset.description && <div title={dataset.description} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)', fontSize: 10, marginTop: 2 }}>{dataset.description}</div>}
                </div>
                {dataset.type && <Tag style={{ flex: '0 0 auto', marginInlineEnd: 0, fontSize: 10 }}>{dataset.type}</Tag>}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function ScopePanel({
  projectName,
  tools, selectedToolIds, onToolChange,
  skills, selectedSkillIds, onSkillChange,
  subagents, selectedSubagentIds, onSubagentChange,
  guardrails, disabledGuardrailIds, onGuardrailChange,
}: {
  projectName: string | null
  tools: any[]; selectedToolIds: string[] | null; onToolChange: (ids: string[] | null) => void
  skills: any[]; selectedSkillIds: string[] | null; onSkillChange: (ids: string[] | null) => void
  subagents: any[]; selectedSubagentIds: string[] | null; onSubagentChange: (ids: string[] | null) => void
  guardrails: any[]; disabledGuardrailIds: string[]; onGuardrailChange: (ids: string[]) => void
}) {
  return (
    <section aria-label="Session scope" style={{ color: 'var(--ink)' }}>
      <p style={{ margin: '0 0 14px', color: 'var(--muted)', fontSize: 12, lineHeight: 1.45 }}>
        {projectName ? <>Project defaults · <b>{projectName}</b><br />Changes below are session-only overrides.</> : 'Independent session scope'}
      </p>
      <ScopeGroup name="Tools" items={tools} selectedIds={selectedToolIds} getId={item => item.name} getName={item => item.label || item.display_name || item.name} describe={item => item.source} onChange={onToolChange} mono />
      <ScopeGroup name="Skills" items={skills} selectedIds={selectedSkillIds} getId={item => item.id} getName={item => item.name || item.title || item.id} describe={item => item.description} onChange={onSkillChange} />
      <ScopeGroup name="Subagents" items={subagents} selectedIds={selectedSubagentIds} getId={item => item.id} getName={item => item.name || item.title || item.id} describe={item => item.agent_type} onChange={onSubagentChange} />
      <ScopeGroup name="Guardrails" items={guardrails} selectedIds={guardrails.length ? guardrails.filter(item => !disabledGuardrailIds.includes(item.id)).map(item => item.id) : null} getId={item => item.id} getName={item => item.name || item.title || item.id} describe={item => `${item.phase || 'runtime'} · ${item.mode === 'user_approval' ? 'approval' : 'auto'}`} onChange={ids => onGuardrailChange(ids === null ? [] : guardrails.map(item => item.id).filter(id => !ids.includes(id)))} />
    </section>
  )
}

function ScopeGroup({ name, items, selectedIds, getId, getName, describe, onChange, mono = false }: {
  name: string
  items: any[]
  selectedIds: string[] | null
  getId: (item: any) => string
  getName?: (item: any) => string
  describe: (item: any) => string | undefined
  onChange: (ids: string[] | null) => void
  mono?: boolean
}) {
  const [expanded, setExpanded] = useState(true)
  const [showAll, setShowAll] = useState(false)
  const allOn = selectedIds === null
  const off = allOn ? 0 : Math.max(0, items.length - selectedIds.length)
  const visible = showAll ? items : items.slice(0, 6)
  return (
    <div style={{ borderTop: '1px solid var(--line)', padding: '10px 0' }}>
      <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} style={{ display: 'flex', width: '100%', alignItems: 'center', gap: 7, border: 0, padding: 0, background: 'transparent', color: 'var(--ink)', cursor: 'pointer', textAlign: 'left' }}>
        <RightOutlined style={{ fontSize: 9, transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform .15s' }} />
        <span style={{ fontSize: 12, fontWeight: 600 }}>{name}</span>
        <span style={{ color: 'var(--faint)', fontSize: 11 }}>{items.length}</span>
        <span style={{ marginLeft: 'auto', color: off ? 'var(--warn)' : 'var(--good)', fontSize: 11 }}>{items.length ? off ? `${off} off` : 'all on' : 'none defined'}</span>
      </button>
      {expanded && visible.map(item => {
        const id = getId(item)
        const configuredName = getName?.(item)
        const displayName = configuredName && configuredName !== id ? configuredName : humanizeScopeId(id)
        const detail = describe(item)
        const on = selectedIds === null || selectedIds.includes(id)
        return (
          <div key={id} style={{ display: 'flex', minWidth: 0, alignItems: 'center', gap: 8, padding: '8px 2px 0 18px' }}>
            <Switch size="small" checked={on} onChange={checked => {
              const current = selectedIds === null ? items.map(getId) : selectedIds
              onChange(checked ? [...current, id] : current.filter(value => value !== id))
            }} />
            <div style={{ flex: '1 1 auto', minWidth: 0 }}>
              <div title={displayName} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: mono ? 'var(--mono)' : undefined, fontSize: 12 }}>{displayName}</div>
              {displayName !== id && <div title={id} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--faint)', fontFamily: 'var(--mono)', fontSize: 10 }}>{id}</div>}
            </div>
            {detail && <span title={detail} style={{ flex: '0 1 34%', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--faint)', fontSize: 10, textAlign: 'right', whiteSpace: 'nowrap' }}>{detail}</span>}
          </div>
        )
      })}
      {expanded && items.length > 6 && <button type="button" onClick={() => setShowAll(value => !value)} style={{ border: 0, margin: '8px 0 0 18px', padding: 0, color: 'var(--accent)', background: 'transparent', cursor: 'pointer', fontSize: 11 }}>{showAll ? 'Show less' : `Show ${items.length - 6} more…`}</button>}
    </div>
  )
}

function SessionExperimentsPanel({ sessionId, runs, loading, onRefresh }: {
  sessionId: string
  runs: any[]
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <section aria-label="Session experiments" style={{ minWidth: 0, color: 'var(--ink)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>MLflow runs</div>
          <div title={sessionId} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--faint)', fontFamily: 'var(--mono)', fontSize: 10 }}>{sessionId}</div>
        </div>
        <Button size="small" type="text" icon={<ReloadOutlined />} onClick={onRefresh} aria-label="Refresh experiments" style={{ marginLeft: 'auto' }} />
      </div>
      {loading ? (
        <div style={{ padding: 32, color: 'var(--muted)', fontSize: 12, textAlign: 'center' }}>Loading experiments…</div>
      ) : runs.length === 0 ? (
        <Empty description="No MLflow runs recorded yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {runs.map((run, index) => {
            const metrics = Object.entries(run.metrics || {}).slice(0, 5)
            const params = Object.entries(run.params || {}).slice(0, 3)
            const runName = run.tags?.['mlflow.runName'] || `Run ${index + 1}`
            return (
              <article key={run.run_id || index} style={{ minWidth: 0, border: '1px solid var(--line)', borderRadius: 8, padding: 10, background: 'var(--bg)' }}>
                <div style={{ display: 'flex', minWidth: 0, alignItems: 'center', gap: 8 }}>
                  <span title={runName} style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, fontWeight: 600 }}>{runName}</span>
                  <Tag color={run.status === 'FINISHED' ? 'green' : run.status === 'RUNNING' ? 'blue' : 'default'} style={{ flex: '0 0 auto', marginInlineEnd: 0, fontSize: 10 }}>{run.status || 'UNKNOWN'}</Tag>
                </div>
                <div style={{ display: 'flex', minWidth: 0, gap: 6, marginTop: 5, color: 'var(--faint)', fontSize: 10 }}>
                  <code title={run.run_id}>{run.run_id?.slice(0, 8) || 'no run id'}</code>
                  {run.start_time && <span>{formatExperimentTime(run.start_time)}</span>}
                  {run.artifacts?.length > 0 && <span>{run.artifacts.length} file{run.artifacts.length === 1 ? '' : 's'}</span>}
                </div>
                {metrics.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
                  {metrics.map(([key, value]) => <Tag key={key} color="green" style={{ maxWidth: '100%', marginInlineEnd: 0, overflow: 'hidden', textOverflow: 'ellipsis', fontSize: 10 }}>{key}: {formatExperimentValue(value)}</Tag>)}
                </div>}
                {params.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                  {params.map(([key, value]) => <Tag key={key} color="blue" style={{ maxWidth: '100%', marginInlineEnd: 0, overflow: 'hidden', textOverflow: 'ellipsis', fontSize: 10 }}>{key}: {formatExperimentValue(value)}</Tag>)}
                </div>}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function formatExperimentTime(value: number) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

function formatExperimentValue(value: unknown) {
  const numeric = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(numeric) ? Number(numeric.toPrecision(5)).toString() : String(value)
}

function humanizeScopeId(value: string) {
  return value.split(/[-_]+/).filter(Boolean).map(word => {
    if (word === word.toUpperCase()) return word
    return `${word.charAt(0).toUpperCase()}${word.slice(1)}`
  }).join(' ') || value
}

function isPlanApprovalRecap(content: string): boolean {
  const text = content.trim().toLowerCase()
  if (!text) return false
  const mentionsApproval = /waiting on your approval|awaiting your approval|awaiting approval|approve it and/.test(text)
  const mentionsPlanSteps = /plan'?s submitted|plan submitted|steps:/.test(text)
  const mentionsRetarget = /retarget before executing|narrower in mind|before executing/.test(text)
  return mentionsApproval && (mentionsPlanSteps || mentionsRetarget)
}

function MessageBubble({ message, onFileClick }: { message: AGUIMessage; onFileClick?: (path: string) => void }) {
  const planDecision = planDecisionMarker(message.content)
  if (planDecision) {
    return (
      <div className={`chat-system-marker is-${planDecision.status}`} role="status">
        <span aria-hidden="true">{planDecision.status === 'approved' ? '✓' : planDecision.status === 'denied' ? '!' : '↺'}</span>
        <span>{planDecision.label}</span>
      </div>
    )
  }
  const isUser = message.role === 'user'
  return (
    <div className={isUser ? 'chat-message chat-message--user' : 'chat-message chat-message--assistant'} style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 18 }}>
      <div style={{
        // Prose gets a readable character measure; evidence cards and the
        // composer retain the wider shared transcript canvas.
        maxWidth: isUser ? 'min(70%, 780px)' : '76ch',
        padding: isUser ? '10px 16px' : '2px 0',
        borderRadius: isUser ? '16px 16px 4px 16px' : 0,
        background: isUser ? '#1677ff' : 'transparent',
        color: isUser ? '#fff' : '#1a1a1a',
        fontSize: isUser ? 14 : 14.5, lineHeight: isUser ? 1.55 : 1.65,
      }}>
        {isUser && message.sentFromQueue && <div style={{ marginBottom: 4, opacity: 0.8, fontSize: 10, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Sent from queue</div>}
        {isUser ? <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span> : <MarkdownContent content={message.content} onFileClick={onFileClick} />}
      </div>
    </div>
  )
}

function planDecisionMarker(content: string) {
  const match = content.trim().match(/^Plan\s+.+?\s+is\s+(approved|denied|needs changes)\.(?:\s+Feedback:\s*[\s\S]*)?$/i)
  if (!match) return null
  const status = match[1].toLowerCase()
  if (status === 'approved') return { status: 'approved', label: 'Plan approved' }
  if (status === 'denied') return { status: 'denied', label: 'Plan not approved' }
  return { status: 'changes', label: 'Plan changes requested' }
}

function QueuedBubble({ message, position, paused, onEdit, onSendNext, onRemove }: {
  message: QueuedMessage
  position: number
  paused: boolean
  onEdit: (id: string) => void
  onSendNext: (id: string) => void
  onRemove: (id: string) => void
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }} role="status" aria-label={`Queued message, ${queuePosition(position)}`}>
      <div style={{ maxWidth: '85%', padding: '9px 12px', border: '1px dashed #98a2b3', borderRadius: '14px 14px 4px 14px', background: paused ? '#f7f8fa' : '#fff', color: paused ? '#667085' : '#344054', fontSize: 13, lineHeight: 1.5 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5, fontSize: 10, letterSpacing: '0.04em', color: '#667085', textTransform: 'uppercase' }}>
          <span>Queued · {queuePosition(position)}</span>
          <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 2 }}>
            <Button type="text" size="small" icon={<EditOutlined />} onClick={() => onEdit(message.id)} aria-label="Edit queued message" style={{ width: 22, minWidth: 22, height: 20, padding: 0 }} />
            <Button type="text" size="small" icon={<ArrowUpOutlined />} onClick={() => onSendNext(message.id)} aria-label="Send this message next" style={{ width: 22, minWidth: 22, height: 20, padding: 0 }} />
            <Button type="text" size="small" icon={<CloseOutlined />} onClick={() => onRemove(message.id)} aria-label="Remove queued message" style={{ width: 22, minWidth: 22, height: 20, padding: 0 }} />
          </span>
        </div>
        <span style={{ whiteSpace: 'pre-wrap' }}>{message.text}</span>
      </div>
    </div>
  )
}

function queuePosition(index: number) {
  if (index === 0) return 'next'
  if (index === 1) return '2nd'
  if (index === 2) return '3rd'
  return `${index + 1}th`
}

function CompactionDivider({ message }: { message: AGUIMessage }) {
  const [expanded, setExpanded] = useState(false)
  const summarized = message.compactedCount || 0
  const kept = message.keptCount || 0
  const label = summarized > 0
    ? `${summarized} messages summarized${kept > 0 ? `, ${kept} kept for context` : ''}`
    : 'Conversation summarized'
  return (
    <div style={{ margin: '16px 0', textAlign: 'center' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '6px 16px', borderRadius: 20,
          background: '#f5f5f5', border: '1px solid #e8e8e8',
          fontSize: 12, color: '#888', cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <span style={{ fontSize: 14 }}>---</span>
        <span>{label}</span>
        <span style={{ fontSize: 10 }}>{expanded ? '\u25B2' : '\u25BC'}</span>
      </div>
      {expanded && message.content && (
        <div style={{
          marginTop: 8, padding: '12px 16px', borderRadius: 8,
          background: '#fafafa', border: '1px solid #f0f0f0',
          textAlign: 'left', fontSize: 13, color: '#666',
          lineHeight: 1.6, maxWidth: 700, margin: '8px auto 0',
          whiteSpace: 'pre-wrap',
        }}>
          {message.content}
        </div>
      )}
    </div>
  )
}

function sortFileTree(items: any[], sort: FileSort, foldersFirst: boolean): any[] {
  const virtualRoots: any[] = []
  const ordinary: any[] = []
  for (const item of items) {
    const normalized = item?.is_dir && Array.isArray(item.children)
      ? { ...item, children: sortFileTree(item.children, sort, foldersFirst) }
      : item
    if (String(item?.path || '').startsWith('__')) virtualRoots.push(normalized)
    else ordinary.push(normalized)
  }
  ordinary.sort((left, right) => {
    if (foldersFirst && Boolean(left?.is_dir) !== Boolean(right?.is_dir)) return left?.is_dir ? -1 : 1
    if (sort === 'size') {
      const sizeDifference = (Number(right?.size) || 0) - (Number(left?.size) || 0)
      if (sizeDifference) return sizeDifference
    }
    return String(left?.name || '').localeCompare(String(right?.name || ''), undefined, { numeric: true, sensitivity: 'base' })
  })
  // Workspace roots are an intentional grouping, not ordinary folders.
  return [...virtualRoots, ...ordinary]
}

function ChatFileTree({ items, depth, onPreview }: { items: any[]; depth: number; onPreview?: (path: string, name: string) => void }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(items.filter(item => item.path?.startsWith('__')).map(item => item.path)))
  useEffect(() => {
    const virtualRootPaths = items.filter(item => item.path?.startsWith('__')).map(item => item.path)
    if (!virtualRootPaths.length) return
    setExpanded(prev => new Set([...prev, ...virtualRootPaths]))
  }, [items])
  const toggle = (path: string) => setExpanded(prev => { const n = new Set(prev); n.has(path) ? n.delete(path) : n.add(path); return n })

  return (
    <div style={{ paddingLeft: depth * 14 }}>
      {items.map((item: any, i: number) => (
        <div key={item.path || `${item.name}-${i}`}>
          <div onClick={() => item.is_dir ? toggle(item.path) : onPreview?.(item.path, item.name)} style={{
            padding: '3px 6px', fontSize: 12, fontFamily: 'monospace', cursor: 'pointer',
            display: 'flex', minWidth: 0, alignItems: 'center', gap: 4, borderRadius: 3,
            color: item.is_dir ? '#1677ff' : '#555',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = '#f5f5f5')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {item.is_dir ? (expanded.has(item.path) ? <FolderOpenOutlined style={{ fontSize: 11 }} /> : <FolderOutlined style={{ fontSize: 11 }} />) : <FileIcon name={item.name} />}
            <span title={item.name} style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
            {!item.is_dir && <span style={{ flex: '0 0 auto', color: '#bbb', fontSize: 10, marginLeft: 'auto' }}>{(item.size / 1024).toFixed(1)}K</span>}
          </div>
          {item.is_dir && expanded.has(item.path) && item.children && <ChatFileTree items={item.children} depth={depth + 1} onPreview={onPreview} />}
        </div>
      ))}
    </div>
  )
}
