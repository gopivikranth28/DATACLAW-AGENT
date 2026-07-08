import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Button, Card, Input, Select, Empty, Popconfirm, Alert, Modal, Switch, Tag, Tooltip, Table } from 'antd'
import {
  PlusOutlined, DeleteOutlined, SendOutlined, SettingOutlined, DatabaseOutlined,
  EyeOutlined, EyeInvisibleOutlined,
  FolderOutlined, FolderOpenOutlined, ExperimentOutlined, StopOutlined, ReloadOutlined,
  ThunderboltOutlined, EditOutlined, ToolOutlined, BulbOutlined, TeamOutlined, SafetyOutlined,
  ExportOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { API } from '../api'
import { useAGUI } from '../hooks/useAGUI'
import type { AGUIMessage } from '../hooks/useAGUI'
import MarkdownContent from '../components/MarkdownContent'
import ToolCallCard from '../components/ToolCallCard'
import GuardrailCard from '../components/GuardrailCard'
import PlanPanel from '../components/PlanPanel'
import PendingPlanBanner from '../components/PendingPlanBanner'
import ArtifactPanel from '../components/ArtifactPanel'
import { usePlans, PlansContext } from '../hooks/usePlans'
import type { Plan } from '../hooks/usePlans'
import { FileViewerModal } from '../components/FilePreview'
import FileIcon from '../components/FileIcon'
import AppView, {
  collectAppItems,
  itemsFromVisualArtifacts,
  mergeAppItems,
  type AppLayout,
  type VisualArtifact,
} from '../components/AppView'

interface Session { id: string; title: string; createdAt: string }

interface ChatPageProps { projectId?: string; initialSessionId?: string | null; initialDatasetIds?: string[] | null; onSessionChange?: (id: string | null) => void }

export default function ChatPage({ projectId, initialSessionId, initialDatasetIds, onSessionChange }: ChatPageProps = {}) {
  const [sessions, setSessions] = useState<Session[]>([])
  // Only use URL params for session persistence when standalone (no projectId)
  const isStandalone = !projectId
  const [searchParams] = useSearchParams()
  const urlSession = isStandalone ? searchParams.get('session') : null
  const [activeSessionId, _setActiveSessionId] = useState<string | null>(initialSessionId ?? urlSession ?? null)
  const setActiveSessionId = (id: string | null) => {
    _setActiveSessionId(id)
    onSessionChange?.(id)
    if (isStandalone) {
      const next = new URLSearchParams(window.location.search)
      if (id) next.set('session', id)
      else next.delete('session')
      window.history.replaceState(null, '', next.toString() ? `?${next}` : window.location.pathname)
    }
  }
  const [input, setInput] = useState('')
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

  // Tool toggle
  const [showTools, setShowTools] = useState(true)

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

  // Plans — shared state lives in usePlans (wired after useAGUI below);
  // reviewed on the right (PlanPanel), referenced from the chat/bottom banner.
  const [hasPlansPlugin, setHasPlansPlugin] = useState(false)
  const [hasArtifactsPlugin, setHasArtifactsPlugin] = useState(false)
  const [artifactRefreshKey, setArtifactRefreshKey] = useState(0)
  // Fresh object per focusPlan() call so repeat clicks re-trigger the panel's
  // expand-and-scroll effect even for the same plan id.
  const [focusedPlan, setFocusedPlan] = useState<{ id: string } | null>(null)
  const [planPopoverOpen, setPlanPopoverOpen] = useState(false)
  const [planReaderExpanded, setPlanReaderExpanded] = useState(false)

  // Dataset filters
  const [hasDataPlugin, setHasDataPlugin] = useState(false)
  const [allDatasets, setAllDatasets] = useState<any[]>([])
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[] | null>(initialDatasetIds !== undefined ? initialDatasetIds ?? null : null)
  const [datasetModalOpen, setDatasetModalOpen] = useState(false)

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
    if (!projectId) return
    fetch(`${API}/projects/${projectId}`).then(r => r.ok ? r.json() : null)
      .then(p => setProjectDir(p?.directory || null)).catch(() => {})
  }, [projectId])

  const resolveFilePath = (path: string) => {
    if (path.startsWith('/')) return path
    return projectDir ? `${projectDir}/${path}` : path
  }

  const previewFile = (path: string) => {
    const resolved = resolveFilePath(path)
    setFilePreviewTarget({ name: path.split('/').pop() || path, path: resolved })
  }

  // File explorer
  const [hasWorkspacePlugin, setHasWorkspacePlugin] = useState(false)
  const [sidebarTab, setSidebarTab] = useState<'plans' | 'files' | 'artifacts' | 'app'>('plans')

  // App view curation — persisted on the session so the published
  // /app/<session-id> route reflects it.
  const [appLayout, setAppLayout] = useState<AppLayout | null>(null)
  const [visualArtifacts, setVisualArtifacts] = useState<VisualArtifact[]>([])
  const [projectFiles, setProjectFiles] = useState<any[]>([])
  const [filePreviewTarget, setFilePreviewTarget] = useState<{ name: string; path: string } | null>(null)

  // MLflow modal
  const [mlflowModalOpen, setMlflowModalOpen] = useState(false)
  const [mlflowRuns, setMlflowRuns] = useState<any[]>([])
  const [mlflowLoading, setMlflowLoading] = useState(false)
  const [mlflowSessionId, setMlflowSessionId] = useState('')

  // Resizable sidebar
  const [sidebarWidth, setSidebarWidth] = useState(420)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const resizingRef = useRef(false)

  // Keep auto mode refs in sync
  useEffect(() => { autoModeRef.current = autoMode }, [autoMode])
  useEffect(() => { autoTurnsRef.current = autoTurnsUsed }, [autoTurnsUsed])
  useEffect(() => { autoMessageRef.current = autoMessage }, [autoMessage])
  useEffect(() => { maxAutoTurnsRef.current = maxAutoTurns }, [maxAutoTurns])
  useEffect(() => { activeSessionIdRef.current = activeSessionId }, [activeSessionId])

  // Stable ref for sendMessage so onRunFinished doesn't go stale
  const sendMessageRef = useRef<typeof sendMessage>(null as any)
  const autoContinuePendingRef = useRef(false)

  const onRunFinished = useCallback(() => {
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

  const { messages, toolCalls, timeline, isRunning, reconnecting, error, sendMessage, cancelRun, checkAndReconnect, reset } = useAGUI({ onRunFinished })
  sendMessageRef.current = sendMessage

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
    () => toolCalls.filter(tc => tc.name === 'publish_artifact' && tc.status === 'complete').length,
    [toolCalls])
  const { plans, refresh: refreshPlans, submitDecision } = usePlans(
    activeSessionId,
    hasPlansPlugin || planToolResultCount > 0,
    onPlanDecided,
  )
  useEffect(() => { if (planToolResultCount > 0) refreshPlans() }, [planToolResultCount, refreshPlans])
  useEffect(() => {
    if (artifactToolResultCount <= 0) return
    setArtifactRefreshKey(k => k + 1)
    setSidebarTab('artifacts')
    setSidebarCollapsed(false)
  }, [artifactToolResultCount])

  const activePlanDraft = useMemo<Partial<Plan> | null>(() => {
    const draftCall = [...toolCalls].reverse().find(tc => tc.name === 'propose_plan' && tc.status === 'calling')
    if (!draftCall) return null
    try {
      const parsed = JSON.parse(draftCall.args || '{}')
      return {
        id: 'draft-plan',
        name: parsed.name || 'Drafting analysis plan...',
        description: parsed.description || '',
        plan_markdown: parsed.plan_markdown || '',
        status: 'drafting',
        steps: Array.isArray(parsed.steps) ? parsed.steps : [],
      }
    } catch {
      return { id: 'draft-plan', name: 'Drafting analysis plan...', status: 'drafting', steps: [] }
    }
  }, [toolCalls])

  const wasDraftingPlanRef = useRef(false)
  useEffect(() => {
    const isDraftingPlan = !!activePlanDraft
    if (isDraftingPlan && !wasDraftingPlanRef.current) setPlanPopoverOpen(true)
    wasDraftingPlanRef.current = isDraftingPlan
  }, [activePlanDraft])

  const focusPlan = useCallback((planId: string) => {
    setSidebarTab('plans')
    setSidebarCollapsed(false)
    setFocusedPlan({ id: planId })
  }, [setSidebarTab, setSidebarCollapsed, setFocusedPlan])

  // A new pending plan blocks the agent — bring it into view (open a collapsed
  // sidebar, switch tab, expand). Covers changes_requested → re-propose too,
  // since the same record flips back to pending. Keyboard focus is not moved.
  const prevPendingIdsRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    const pendingIds = plans.filter(p => p.status === 'pending').map(p => p.id)
    const newPending = pendingIds.filter(id => !prevPendingIdsRef.current.has(id))
    prevPendingIdsRef.current = new Set(pendingIds)
    if (newPending.length > 0) {
      focusPlan(newPending[newPending.length - 1])
      setPlanPopoverOpen(true)
    }
  }, [plans, focusPlan])

  const pendingPlans = useMemo(() => plans.filter(p => p.status === 'pending'), [plans])
  const latestPendingPlan = pendingPlans[pendingPlans.length - 1] ?? null
  const composerPlaceholder = latestPendingPlan
    ? 'Type feedback or revision notes for this plan...'
    : 'Send a message...'

  const plansCtx = useMemo(
    () => ({ plans, submitDecision, focusPlan }),
    [plans, submitDecision, focusPlan])

  // App view: collect chart/metric items from the session's tool calls;
  // load saved curation from the session and persist edits back to it.
  const appItems = useMemo(() => {
    const persisted = itemsFromVisualArtifacts(visualArtifacts)
    const live = collectAppItems(toolCalls.map(tc => ({ name: tc.name, result: tc.result })))
    return mergeAppItems(persisted, live)
  }, [toolCalls, visualArtifacts])
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
      setHasWorkspacePlugin(plugins.some((p: any) => p.id === 'workspace'))
    }).catch(() => {})
  }, [])

  // Load sessions
  const loadSessions = useCallback(async () => {
    try {
      const url = projectId ? `${API}/chat/sessions?project_id=${projectId}` : `${API}/chat/sessions`
      const res = await fetch(url)
      if (res.ok) setSessions(await res.json())
    } catch {}
  }, [projectId])
  useEffect(() => { loadSessions() }, [loadSessions])

  // Sync initialSessionId from parent (e.g. ProjectPage session tile click)
  useEffect(() => {
    if (initialSessionId && initialSessionId !== activeSessionId) {
      setActiveSessionId(initialSessionId)
    }
  }, [initialSessionId])

  // Load session: connect via AG-UI to get MessagesSnapshot, and fetch metadata for dataset filter
  useEffect(() => {
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
        if (session?.datasetIds !== undefined) {
          setSelectedDatasetIds(session.datasetIds)
        }
        if (session?.toolIds !== undefined) setSelectedToolIds(session.toolIds)
        if (session?.skillIds !== undefined) setSelectedSkillIds(session.skillIds)
        if (session?.subagentIds !== undefined) setSelectedSubagentIds(session.subagentIds)
        if (session?.guardrailConfig?.disabled) setGuardrailDisabled(session.guardrailConfig.disabled)
        else setGuardrailDisabled([])
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
    if (!hasWorkspacePlugin || !projectId) { setProjectFiles([]); return }
    fetch(`${API}/projects/${projectId}/files`)
      .then(r => r.ok ? r.json() : { project: [] })
      .then(d => setProjectFiles(d.project || []))
      .catch(() => setProjectFiles([]))
  }, [hasWorkspacePlugin, projectId])
  useEffect(() => { loadProjectFiles() }, [loadProjectFiles])

  // Filtered timeline (pre-filter tool calls when hidden)
  const filteredTimeline = useMemo(() => {
    const visible = showTools ? timeline : timeline.filter(e => e.type !== 'toolCall')
    return visible.filter(e => {
      if (e.type !== 'message') return true
      return !isPlanApprovalRecap((e.item as AGUIMessage).content)
    })
  }, [timeline, showTools])

  // Windowed slice: only render the tail, expand on "load more"
  const windowedTimeline = useMemo(() => {
    if (filteredTimeline.length <= visibleCount) return filteredTimeline
    return filteredTimeline.slice(filteredTimeline.length - visibleCount)
  }, [filteredTimeline, visibleCount])

  const hasMore = filteredTimeline.length > visibleCount

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
      if (res.ok) { const s = await res.json(); setSessions(prev => [s, ...prev]); setActiveSessionId(s.id); reset() }
    } catch {}
  }

  const deleteSession = async () => {
    if (!activeSessionId) return
    await fetch(`${API}/chat/sessions/${activeSessionId}`, { method: 'DELETE' })
    setSessions(prev => prev.filter(s => s.id !== activeSessionId))
    setActiveSessionId(null); reset()
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isRunning) return
    setInput('')

    let sessionId = activeSessionId
    const isFirstMessage = messages.length === 0

    if (!sessionId) {
      // Create session on backend first (like ProjectPage does)
      try {
        const res = await fetch(`${API}/chat/sessions`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: text.slice(0, 50), project_id: projectId || null }),
        })
        if (!res.ok) return
        const s = await res.json()
        sessionId = s.id
        setSessions(prev => [s, ...prev])
        skipNextLoadRef.current = true
        setActiveSessionId(sessionId)
      } catch { return }
    } else if (isFirstMessage) {
      // Update title for existing empty session
      const title = text.slice(0, 50)
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s))
      fetch(`${API}/chat/sessions/${sessionId}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      }).catch(() => {})
    }

    // Pending-plan composer mode: the user's message doubles as plan feedback.
    // silent — this same message informs the agent, no synthetic one needed.
    if (latestPendingPlan) {
      await submitDecision(latestPendingPlan.id, 'changes_requested', text, true)
      setPlanPopoverOpen(false)
    }

    const history = messages.map(m => ({ role: m.role, content: m.content }))
    sendMessage(sessionId!, history, text)
  }

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
      setSidebarWidth(Math.max(360, Math.min(900, startWidth + delta)))
    }
    const onUp = () => { resizingRef.current = false; window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [sidebarWidth])

  const openMlflowModal = (sessionId: string) => {
    setMlflowSessionId(sessionId)
    setMlflowModalOpen(true)
    setMlflowLoading(true)
    fetch(`${API}/mlflow/runs?session_id=${sessionId}`)
      .then(r => r.ok ? r.json() : { runs: [] })
      .then(d => setMlflowRuns(d.runs || []))
      .catch(() => setMlflowRuns([]))
      .finally(() => setMlflowLoading(false))
  }

  const saveSystemPrompt = () => {
    setSystemPrompt(promptDraft)
    localStorage.setItem('dataclaw_system_prompt', promptDraft)
    setPromptModalOpen(false)
  }

  const showPlansSidebar = hasPlansPlugin || plans.length > 0 || planToolResultCount > 0
  const showFilesSidebar = hasWorkspacePlugin && !!projectId
  const showArtifactsSidebar = hasArtifactsPlugin || artifactToolResultCount > 0
  // Insights is core (viz layer) — the sidebar is always available.
  const showSidebar = true
  const planSidebarOverlay = planReaderExpanded && sidebarTab === 'plans' && !sidebarCollapsed
  const sidebarPanelWidth = planSidebarOverlay
    ? 'min(1120px, calc(100vw - 32px))'
    : sidebarCollapsed ? 36 : sidebarWidth

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
        {/* Top bar */}
        <div style={{ padding: '10px 20px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8, background: '#fff' }}>
          <Select value={activeSessionId} onChange={id => setActiveSessionId(id)} placeholder="Select session" style={{ width: 240 }}
            options={sessions.map(s => ({ value: s.id, label: s.title || s.id.slice(0, 8) }))} allowClear onClear={() => { setActiveSessionId(null); reset() }} />
          <Button icon={<PlusOutlined />} onClick={createSession} size="small">New</Button>
          {activeSessionId && <Popconfirm title="Delete this session?" onConfirm={deleteSession}><Button icon={<DeleteOutlined />} danger size="small" /></Popconfirm>}

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            {/* Auto mode toggle */}
            {hasPlansPlugin && (
              <Tooltip title={autoMode ? `Auto mode ON (${autoTurnsUsed}/${maxAutoTurns} turns)` : 'Enable auto mode'}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '0 4px' }}>
                  <ThunderboltOutlined style={{ fontSize: 12, color: autoMode ? '#1677ff' : '#999' }} />
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
                  <span style={{ fontSize: 11, color: autoMode ? '#1677ff' : '#999', cursor: 'pointer' }}
                    onClick={() => { setAutoMessageDraft(autoMessage); setMaxAutoTurnsDraft(maxAutoTurns); setAutoMessageModalOpen(true) }}>
                    Auto
                  </span>
                  {autoMode && (
                    <Button size="small" type="text" icon={<EditOutlined />}
                      style={{ padding: '0 2px', height: 18, width: 18, minWidth: 18, fontSize: 10, color: '#999' }}
                      onClick={() => { setAutoMessageDraft(autoMessage); setMaxAutoTurnsDraft(maxAutoTurns); setAutoMessageModalOpen(true) }} />
                  )}
                </div>
              </Tooltip>
            )}

            {/* Dataset filter */}
            {hasDataPlugin && (
              <Tooltip title="Manage datasets">
                <Tag icon={<DatabaseOutlined />} color={selectedDatasetIds !== null ? 'blue' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setDatasetModalOpen(true)}>
                  {selectedDatasetIds !== null ? `${selectedDatasetIds.length} datasets` : 'All datasets'}
                </Tag>
              </Tooltip>
            )}

            {/* Tools filter */}
            {allTools.length > 0 && (
              <Tooltip title="Manage tools">
                <Tag icon={<ToolOutlined />} color={selectedToolIds !== null ? 'blue' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setToolModalOpen(true)}>
                  {selectedToolIds !== null ? `${selectedToolIds.length} tools` : 'All tools'}
                </Tag>
              </Tooltip>
            )}

            {/* Skills filter */}
            {allSkills.length > 0 && (
              <Tooltip title="Manage skills">
                <Tag icon={<BulbOutlined />} color={selectedSkillIds !== null ? 'blue' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setSkillModalOpen(true)}>
                  {selectedSkillIds !== null ? `${selectedSkillIds.length} skills` : 'All skills'}
                </Tag>
              </Tooltip>
            )}

            {/* Subagents filter */}
            {allSubagents.length > 0 && (
              <Tooltip title="Manage subagents">
                <Tag icon={<TeamOutlined />} color={selectedSubagentIds !== null ? 'blue' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setSubagentModalOpen(true)}>
                  {selectedSubagentIds !== null ? `${selectedSubagentIds.length} subagents` : 'All subagents'}
                </Tag>
              </Tooltip>
            )}

            {/* Guardrails config */}
            {allGuardrails.length > 0 && (
              <Tooltip title="Manage guardrails">
                <Tag icon={<SafetyOutlined />} color={guardrailDisabled.length > 0 ? 'orange' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setGuardrailModalOpen(true)}>
                  {guardrailDisabled.length > 0 ? `${allGuardrails.length - guardrailDisabled.length}/${allGuardrails.length} guardrails` : 'All guardrails'}
                </Tag>
              </Tooltip>
            )}

            {/* Tool call visibility toggle */}
            <Tooltip title={showTools ? 'Hide tool calls' : 'Show tool calls'}>
              <Button size="small" type={showTools ? 'default' : 'dashed'}
                icon={showTools ? <EyeOutlined /> : <EyeInvisibleOutlined />}
                onClick={() => setShowTools(!showTools)} />
            </Tooltip>

            {/* System prompt */}
            <Tooltip title="System prompt">
              <Button size="small" type={systemPrompt ? 'primary' : 'default'} ghost={!!systemPrompt}
                icon={<SettingOutlined />}
                onClick={() => { setPromptDraft(systemPrompt); setPromptModalOpen(true) }} />
            </Tooltip>
          </div>
        </div>

        {/* Standalone chat warning */}
        {!projectId && (
          <Alert type="info" showIcon closable
            style={{ margin: '8px 24px 0', borderRadius: 8 }}
            message={<span>
              This is a standalone chat — work will be stored in a temporary directory.{' '}
              <a href="/projects?new=1" style={{ fontWeight: 500 }}>Create a project</a> for persistent, organized workspaces.
            </span>} />
        )}

        {/* Messages */}
        <div ref={scrollContainerRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
          {filteredTimeline.length === 0 && !isRunning ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Empty description="Start a conversation" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            <div style={{ maxWidth: 800, margin: '0 auto' }}>
              {hasMore && (
                <div style={{ textAlign: 'center', padding: '8px 0' }}>
                  <Button size="small" type="link" onClick={() => setVisibleCount(prev => prev + WINDOW_SIZE)}>
                    Load earlier messages ({filteredTimeline.length - visibleCount} more)
                  </Button>
                </div>
              )}
              {windowedTimeline.map(entry => (
                <div key={entry.item.id} style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 80px' }}>
                  {entry.type === 'message'
                    ? (entry.item as AGUIMessage).role === 'compaction'
                      ? <CompactionDivider message={entry.item as AGUIMessage} />
                      : <MessageBubble message={entry.item as AGUIMessage} onFileClick={previewFile} />
                    : entry.type === 'guardrail'
                    ? <GuardrailCard guardrail={entry.item as any} threadId={activeSessionId || ''} />
                    : <ToolCallCard toolCall={entry.item as any} onFileClick={previewFile} />
                  }
                </div>
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
          {error && <Alert type="error" message={error} style={{ maxWidth: 800, margin: '12px auto' }} closable />}
        </div>

        {/* Input */}
        <div style={{ padding: '12px 24px 16px', borderTop: '1px solid #f0f0f0', background: '#fff' }}>
          <PendingPlanBanner
            pendingPlans={pendingPlans}
            draftPlan={activePlanDraft}
            open={planPopoverOpen}
            onOpenChange={setPlanPopoverOpen}
            onView={focusPlan}
            onApprove={id => submitDecision(id, 'approved')}
            onDeny={id => submitDecision(id, 'denied')}
          />
          <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', gap: 10, alignItems: 'flex-end' }}>
            <Input.TextArea value={input} onChange={e => setInput(e.target.value)}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder={composerPlaceholder}
              className={latestPendingPlan ? 'dataclaw-plan-feedback-composer' : undefined}
              autoSize={{ minRows: 1, maxRows: 6 }}
              style={{ borderRadius: 10 }} disabled={isRunning} />
            {isRunning ? (
              <Button danger icon={<StopOutlined />} onClick={() => {
                if (activeSessionId) cancelRun(activeSessionId)
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
                style={{ borderRadius: 10, minWidth: 44, height: 32 }} />
            ) : (
              <Button type="primary" icon={<SendOutlined />} onClick={handleSend}
                style={{ borderRadius: 10, minWidth: 44, height: 32 }} />
            )}
          </div>
        </div>
      </div>

      {/* Sidebar: Plans + Files — resizable + collapsible */}
      {showSidebar && (
        <div style={{
          display: 'flex',
          flexShrink: 0,
          ...(planSidebarOverlay ? {
            position: 'absolute',
            top: 0,
            right: 0,
            bottom: 0,
            zIndex: 20,
            boxShadow: '-18px 0 42px rgba(15, 23, 42, 0.16)',
          } : {}),
        }}>
          {/* Resize handle */}
          {!planSidebarOverlay && (
            <div onMouseDown={startResize} style={{
              width: 4, cursor: 'col-resize', background: 'transparent', flexShrink: 0,
              borderLeft: '1px solid #f0f0f0',
            }}
              onMouseEnter={e => (e.currentTarget.style.background = '#ddd')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            />
          )}
        <div style={{
          width: sidebarPanelWidth,
          overflow: 'auto',
          background: '#fafafa',
          transition: sidebarCollapsed || planSidebarOverlay ? 'width 0.2s' : 'none',
          position: 'relative',
          height: planSidebarOverlay ? '100%' : undefined,
          borderLeft: planSidebarOverlay ? '1px solid #eaecf0' : undefined,
        }}>
          {/* Collapse toggle */}
          <div onClick={() => { setPlanReaderExpanded(false); setSidebarCollapsed(!sidebarCollapsed) }} style={{
            position: 'absolute', top: 8, right: 8, cursor: 'pointer', fontSize: 11, color: '#999', zIndex: 1,
            padding: '2px 6px', borderRadius: 4, background: '#f0f0f0',
          }}>{sidebarCollapsed ? '◀' : '▶'}</div>

          {sidebarCollapsed ? null : (<>

          {/* Tab header */}
          <div style={{ display: 'flex', borderBottom: '1px solid #eee' }}>
            {showPlansSidebar && (
              <div onClick={() => setSidebarTab('plans')} style={{
                flex: 1, padding: '8px 12px', textAlign: 'center', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                color: sidebarTab === 'plans' ? '#1677ff' : '#999',
                borderBottom: sidebarTab === 'plans' ? '2px solid #1677ff' : '2px solid transparent',
              }}>Plans</div>
            )}
            {showFilesSidebar && (
              <div onClick={() => { setPlanReaderExpanded(false); setSidebarTab('files') }} style={{
                flex: 1, padding: '8px 12px', textAlign: 'center', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                color: sidebarTab === 'files' ? '#1677ff' : '#999',
                borderBottom: sidebarTab === 'files' ? '2px solid #1677ff' : '2px solid transparent',
              }}>Files</div>
            )}
            {showArtifactsSidebar && (
              <div onClick={() => { setPlanReaderExpanded(false); setSidebarTab('artifacts') }} style={{
                flex: 1, padding: '8px 12px', textAlign: 'center', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                color: sidebarTab === 'artifacts' ? '#1677ff' : '#999',
                borderBottom: sidebarTab === 'artifacts' ? '2px solid #1677ff' : '2px solid transparent',
              }}>Artifacts</div>
            )}
            <div onClick={() => { setPlanReaderExpanded(false); setSidebarTab('app') }} style={{
              flex: 1, padding: '8px 12px', textAlign: 'center', cursor: 'pointer', fontSize: 12, fontWeight: 600,
              color: sidebarTab === 'app' ? '#1677ff' : '#999',
              borderBottom: sidebarTab === 'app' ? '2px solid #1677ff' : '2px solid transparent',
            }}>App</div>
          </div>

          <div style={{ padding: 12 }}>
            {/* Plans tab — read-only companion view; decisions live in the plan card */}
            {sidebarTab === 'plans' && showPlansSidebar && (
              <PlanPanel plans={plans} focusedPlan={focusedPlan} onFileClick={previewFile}
                expanded={planReaderExpanded}
                onExpandedChange={setPlanReaderExpanded}
                onViewExperiments={activeSessionId ? () => openMlflowModal(activeSessionId) : undefined} />
            )}

            {/* Files tab */}
            {sidebarTab === 'files' && showFilesSidebar && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
                  <Button size="small" type="text" icon={<ReloadOutlined />} onClick={loadProjectFiles} style={{ fontSize: 11 }} />
                </div>
                <ChatFileTree items={projectFiles} depth={0} onPreview={(path, name) => setFilePreviewTarget({ name, path })} />
              </div>
            )}

            {/* Artifacts tab — durable published reports/dashboards with version history */}
            {sidebarTab === 'artifacts' && showArtifactsSidebar && (
              <ArtifactPanel sessionId={activeSessionId} refreshKey={artifactRefreshKey} />
            )}

            {/* App tab — auto-composed session app (metrics + charts), curatable + publishable */}
            {sidebarTab === 'app' && (
              <div>
                {activeSessionId && appItems.length > 0 && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                    <Button size="small" icon={<ExportOutlined />}
                      href={`/app/${activeSessionId}`} target="_blank">
                      Publish
                    </Button>
                  </div>
                )}
                <AppView items={appItems} layout={appLayout} editable onLayoutChange={saveAppLayout} />
              </div>
            )}
          </div>
          </>)}
        </div>
        </div>
      )}

      {/* MLflow experiments modal */}
      <Modal title={<><ExperimentOutlined style={{ marginRight: 8 }} />MLflow Experiment Tracking</>}
        open={mlflowModalOpen} onCancel={() => setMlflowModalOpen(false)} footer={null} width={900}>
        <div style={{ marginBottom: 12, fontSize: 11, color: '#888' }}>
          Session: <code>{mlflowSessionId}</code>
        </div>
        {mlflowLoading ? (
          <div style={{ textAlign: 'center', padding: 32 }}>Loading...</div>
        ) : mlflowRuns.length === 0 ? (
          <Empty description="No MLflow runs recorded yet" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table size="small" scroll={{ x: 'max-content' }} pagination={mlflowRuns.length > 10 ? { pageSize: 10 } : false}
            dataSource={mlflowRuns.map((r: any, i: number) => ({ key: i, ...r }))}
            columns={[
              { title: 'Run ID', dataIndex: 'run_id', key: 'run_id', width: 90,
                render: (v: string) => <Tooltip title={v}><code style={{ fontSize: 11 }}>{v?.slice(0, 8)}</code></Tooltip> },
              { title: 'Name', key: 'name', width: 120,
                render: (_: any, r: any) => r.tags?.['mlflow.runName'] || <span style={{ color: '#ccc' }}>&mdash;</span> },
              { title: 'Status', dataIndex: 'status', key: 'status', width: 80,
                render: (v: string) => <Tag color={v === 'FINISHED' ? 'green' : v === 'RUNNING' ? 'blue' : 'default'} style={{ fontSize: 10 }}>{v}</Tag> },
              { title: 'Params', dataIndex: 'params', key: 'params',
                render: (v: any) => v ? Object.entries(v).map(([k, val]) => <Tag key={k} color="blue" style={{ fontSize: 10 }}>{k}: {String(val)}</Tag>) : null },
              { title: 'Metrics', dataIndex: 'metrics', key: 'metrics',
                render: (v: any) => v ? Object.entries(v).map(([k, val]) => <Tag key={k} color="green" style={{ fontSize: 10 }}>{k}: {Number(val).toFixed(4)}</Tag>) : null },
              { title: 'Tags', dataIndex: 'tags', key: 'tags',
                render: (v: any) => v ? Object.entries(v).filter(([k]) => !k.startsWith('mlflow.')).map(([k, val]) => <Tag key={k} color="purple" style={{ fontSize: 10 }}>{k}: {String(val)}</Tag>) : null },
              { title: 'Datasets', dataIndex: 'datasets', key: 'datasets',
                render: (v: any[]) => v?.length ? v.map((d, i) => <Tag key={i} color="cyan" style={{ fontSize: 10 }}>{d.name}</Tag>) : null },
              { title: 'Artifacts', dataIndex: 'artifacts', key: 'artifacts',
                render: (v: any[]) => v?.length ? <Tag style={{ fontSize: 10 }}>{v.length} file(s)</Tag> : null },
              { title: 'Started', dataIndex: 'start_time', key: 'start_time', width: 140,
                render: (v: number) => v ? <span style={{ fontSize: 11, color: '#999' }}>{new Date(v).toLocaleString()}</span> : '' },
            ]}
          />
        )}
      </Modal>

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

      {/* Dataset filter modal */}
      <Modal title="Chat Datasets" open={datasetModalOpen} onCancel={() => setDatasetModalOpen(false)} footer={[
        <Button key="none" onClick={() => updateDatasetFilter([])}>Remove all</Button>,
        <Button key="all" onClick={() => updateDatasetFilter(null)}>Use all datasets</Button>,
        <Button key="done" type="primary" onClick={() => setDatasetModalOpen(false)}>Done</Button>,
      ]}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: '50vh', overflow: 'auto' }}>
          {allDatasets.map(ds => {
            const isOn = selectedDatasetIds === null || selectedDatasetIds.includes(ds.id)
            return (
              <Card key={ds.id} size="small" style={{ borderRadius: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Switch size="small" checked={isOn} onChange={on => {
                    const current = selectedDatasetIds ?? allDatasets.map(d => d.id)
                    updateDatasetFilter(on ? [...current, ds.id] : current.filter(x => x !== ds.id))
                  }} />
                  <span style={{ fontWeight: 500, fontSize: 13 }}>{ds.name}</span>
                  <Tag style={{ fontSize: 10 }}>{ds.type}</Tag>
                </div>
              </Card>
            )
          })}
        </div>
      </Modal>

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

function isPlanApprovalRecap(content: string): boolean {
  const text = content.trim().toLowerCase()
  if (!text) return false
  const mentionsApproval = /waiting on your approval|awaiting your approval|awaiting approval|approve it and/.test(text)
  const mentionsPlanSteps = /plan'?s submitted|plan submitted|steps:/.test(text)
  const mentionsRetarget = /retarget before executing|narrower in mind|before executing/.test(text)
  return mentionsApproval && (mentionsPlanSteps || mentionsRetarget)
}

function MessageBubble({ message, onFileClick }: { message: AGUIMessage; onFileClick?: (path: string) => void }) {
  const isUser = message.role === 'user'
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
      <div style={{
        maxWidth: '85%',
        padding: isUser ? '10px 16px' : '2px 0',
        borderRadius: isUser ? '16px 16px 4px 16px' : 0,
        background: isUser ? '#1677ff' : 'transparent',
        color: isUser ? '#fff' : '#1a1a1a',
        fontSize: 14, lineHeight: 1.6,
      }}>
        {isUser ? <span style={{ whiteSpace: 'pre-wrap' }}>{message.content}</span> : <MarkdownContent content={message.content} onFileClick={onFileClick} />}
      </div>
    </div>
  )
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

function ChatFileTree({ items, depth, onPreview }: { items: any[]; depth: number; onPreview?: (path: string, name: string) => void }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (name: string) => setExpanded(prev => { const n = new Set(prev); n.has(name) ? n.delete(name) : n.add(name); return n })

  return (
    <div style={{ paddingLeft: depth * 14 }}>
      {items.map((item: any, i: number) => (
        <div key={i}>
          <div onClick={() => item.is_dir ? toggle(item.name) : onPreview?.(item.path, item.name)} style={{
            padding: '3px 6px', fontSize: 12, fontFamily: 'monospace', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 4, borderRadius: 3,
            color: item.is_dir ? '#1677ff' : '#555',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = '#f5f5f5')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          >
            {item.is_dir ? (expanded.has(item.name) ? <FolderOpenOutlined style={{ fontSize: 11 }} /> : <FolderOutlined style={{ fontSize: 11 }} />) : <FileIcon name={item.name} />}
            <span>{item.name}</span>
            {!item.is_dir && <span style={{ color: '#bbb', fontSize: 10, marginLeft: 'auto' }}>{(item.size / 1024).toFixed(1)}K</span>}
          </div>
          {item.is_dir && expanded.has(item.name) && item.children && <ChatFileTree items={item.children} depth={depth + 1} onPreview={onPreview} />}
        </div>
      ))}
    </div>
  )
}
