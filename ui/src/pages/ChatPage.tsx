import { useState, useEffect, useRef, useCallback } from 'react'
import { Button, Card, Input, Select, Empty, Popconfirm, Alert, Modal, Switch, Tag, Collapse, Tooltip, Table } from 'antd'
import {
  PlusOutlined, DeleteOutlined, SendOutlined, SettingOutlined, DatabaseOutlined,
  EyeOutlined, EyeInvisibleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ClockCircleOutlined, FolderOutlined, FolderOpenOutlined, ExperimentOutlined, StopOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { API } from '../api'
import { useAGUI } from '../hooks/useAGUI'
import type { AGUIMessage, ToolCallState } from '../hooks/useAGUI'
import MarkdownContent from '../components/MarkdownContent'
import ToolCallCard from '../components/ToolCallCard'
import { FileViewerModal } from '../components/FilePreview'
import FileIcon from '../components/FileIcon'

interface Session { id: string; title: string; createdAt: string }
interface Plan { id: string; name: string; status: string; steps: any[]; iteration?: number; feedback?: string; progress_summary?: string; mlflow_experiment_id?: string; mlflow_run_ids?: string[] }

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
  const skipNextLoadRef = useRef(false)

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem('dataclaw_system_prompt') || '')
  const [promptModalOpen, setPromptModalOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState('')

  // Tool toggle
  const [showTools, setShowTools] = useState(true)

  // Plans sidebar
  const [plans, setPlans] = useState<Plan[]>([])
  const [expandedPlanKeys, setExpandedPlanKeys] = useState<string[]>([])
  const prevPlanIdsRef = useRef<Set<string>>(new Set())
  const [hasPlansPlugin, setHasPlansPlugin] = useState(false)
  const [feedbackModal, setFeedbackModal] = useState<string | null>(null)
  const [feedbackText, setFeedbackText] = useState('')

  // Dataset filters
  const [hasDataPlugin, setHasDataPlugin] = useState(false)
  const [allDatasets, setAllDatasets] = useState<any[]>([])
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[] | null>(initialDatasetIds !== undefined ? initialDatasetIds ?? null : null)
  const [datasetModalOpen, setDatasetModalOpen] = useState(false)

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
  const [sidebarTab, setSidebarTab] = useState<'plans' | 'files'>('plans')
  const [projectFiles, setProjectFiles] = useState<any[]>([])
  const [filePreviewTarget, setFilePreviewTarget] = useState<{ name: string; path: string } | null>(null)

  // MLflow modal
  const [mlflowModalOpen, setMlflowModalOpen] = useState(false)
  const [mlflowRuns, setMlflowRuns] = useState<any[]>([])
  const [mlflowLoading, setMlflowLoading] = useState(false)
  const [mlflowSessionId, setMlflowSessionId] = useState('')

  // Resizable sidebar
  const [sidebarWidth, setSidebarWidth] = useState(320)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const resizingRef = useRef(false)

  const { messages, toolCalls, timeline, isRunning, reconnecting, error, sendMessage, cancelRun, checkAndReconnect, reset, setMessages, setToolCalls, setInitialOrder } = useAGUI()

  // Check plugins
  useEffect(() => {
    fetch(`${API}/plugins`).then(r => r.ok ? r.json() : []).then(plugins => {
      setHasPlansPlugin(plugins.some((p: any) => p.id === 'plans'))
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

  // Load session messages
  useEffect(() => {
    if (!activeSessionId) return
    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false
      return
    }
    reset()
    fetch(`${API}/chat/sessions/${activeSessionId}`)
      .then(r => r.ok ? r.json() : null)
      .then(session => {
        if (!session) return
        // Restore session-level dataset filter
        if (session.datasetIds !== undefined) {
          setSelectedDatasetIds(session.datasetIds)
        }
        if (!session.messages) return
        const sorted = [...session.messages].sort(
          (a: any, b: any) => (a.timestamp || '').localeCompare(b.timestamp || '')
        )
        let order = 0
        const msgs: AGUIMessage[] = []
        const tcs: ToolCallState[] = []
        for (const m of sorted) {
          order++
          if (m.role === 'tool_call') {
            tcs.push({
              id: m.toolCallId || `tc-hist-${order}`,
              name: m.toolName || 'unknown',
              args: m.args || '',
              result: m.result ?? null,
              status: m.status || 'complete',
              order,
            })
          } else if (m.role === 'user' || m.role === 'assistant') {
            msgs.push({
              id: m.messageId || `hist-${order}`,
              role: m.role,
              content: typeof m.content === 'string' ? m.content : '',
              order,
            })
          }
        }
        setMessages(msgs)
        setToolCalls(tcs)
        setInitialOrder(order)
      }).catch(() => {})
  }, [activeSessionId, reset, setMessages, setToolCalls, setInitialOrder])

  // Load plans for session
  useEffect(() => {
    if (!hasPlansPlugin || !activeSessionId) { setPlans([]); setExpandedPlanKeys([]); prevPlanIdsRef.current = new Set(); return }
    const load = () => {
      fetch(`${API}/plans?session_id=${activeSessionId}`)
        .then(r => r.ok ? r.json() : []).then(setPlans).catch(() => {})
    }
    load()
    const interval = setInterval(load, 5000)
    return () => clearInterval(interval)
  }, [hasPlansPlugin, activeSessionId])

  // Auto-expand new plans, collapse old ones
  useEffect(() => {
    const currentIds = new Set(plans.map(p => p.id))
    const newIds = plans.filter(p => !prevPlanIdsRef.current.has(p.id)).map(p => p.id)
    if (newIds.length > 0) {
      setExpandedPlanKeys(newIds)
    } else if (prevPlanIdsRef.current.size === 0 && plans.length > 0) {
      // Initial load — expand pending plans
      setExpandedPlanKeys(plans.filter(p => p.status === 'pending' || p.status === 'running').map(p => p.id))
    }
    prevPlanIdsRef.current = currentIds
  }, [plans])

  // Load datasets for filter
  useEffect(() => {
    if (!hasDataPlugin) return
    fetch(`${API}/data/datasets`).then(r => r.ok ? r.json() : []).then(setAllDatasets).catch(() => {})
  }, [hasDataPlugin])

  // Load project files for explorer
  const loadProjectFiles = useCallback(() => {
    if (!hasWorkspacePlugin || !projectId) { setProjectFiles([]); return }
    fetch(`${API}/projects/${projectId}/files`)
      .then(r => r.ok ? r.json() : { project: [] })
      .then(d => setProjectFiles(d.project || []))
      .catch(() => setProjectFiles([]))
  }, [hasWorkspacePlugin, projectId])
  useEffect(() => { loadProjectFiles() }, [loadProjectFiles])

  // Check for active agent run on session change (handles page refresh)
  useEffect(() => {
    if (!activeSessionId) return
    checkAndReconnect(activeSessionId)
  }, [activeSessionId, checkAndReconnect])

  // Auto-scroll
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, toolCalls])

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
      setSidebarWidth(Math.max(200, Math.min(600, startWidth + delta)))
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

  const submitDecision = async (planId: string, status: string, feedback: string = '') => {
    await fetch(`${API}/plans/${planId}/decision`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, feedback }),
    })
    // Refresh plans
    if (activeSessionId) {
      fetch(`${API}/plans?session_id=${activeSessionId}`).then(r => r.ok ? r.json() : []).then(setPlans).catch(() => {})
    }
    // Auto-send a chat message so the agent knows the decision
    if (!isRunning && activeSessionId) {
      const labels: Record<string, string> = { approved: 'approved', denied: 'denied', changes_requested: 'needs changes' }
      let text = `Plan ${planId} is ${labels[status] || status}.`
      if (feedback) text += ` Feedback: ${feedback}`
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      sendMessage(activeSessionId, history, text)
    }
  }

  const showPlansSidebar = hasPlansPlugin
  const showFilesSidebar = hasWorkspacePlugin && !!projectId
  const showSidebar = showPlansSidebar || showFilesSidebar

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* Main chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Top bar */}
        <div style={{ padding: '10px 20px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8, background: '#fff' }}>
          <Select value={activeSessionId} onChange={id => setActiveSessionId(id)} placeholder="Select session" style={{ width: 240 }}
            options={sessions.map(s => ({ value: s.id, label: s.title || s.id.slice(0, 8) }))} allowClear onClear={() => { setActiveSessionId(null); reset() }} />
          <Button icon={<PlusOutlined />} onClick={createSession} size="small">New</Button>
          {activeSessionId && <Popconfirm title="Delete this session?" onConfirm={deleteSession}><Button icon={<DeleteOutlined />} danger size="small" /></Popconfirm>}

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
            {/* Dataset filter */}
            {hasDataPlugin && (
              <Tooltip title="Manage datasets">
                <Tag icon={<DatabaseOutlined />} color={selectedDatasetIds !== null ? 'blue' : 'green'}
                  style={{ cursor: 'pointer', margin: 0 }} onClick={() => setDatasetModalOpen(true)}>
                  {selectedDatasetIds !== null ? `${selectedDatasetIds.length} datasets` : 'All datasets'}
                </Tag>
              </Tooltip>
            )}

            {/* Tool toggle */}
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
        <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
          {messages.length === 0 && !isRunning ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              <Empty description="Start a conversation" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            <div style={{ maxWidth: 800, margin: '0 auto' }}>
              {timeline.map(entry => (
                entry.type === 'message'
                  ? <MessageBubble key={entry.item.id} message={entry.item as AGUIMessage} onFileClick={previewFile} />
                  : showTools ? <ToolCallCard key={entry.item.id} toolCall={entry.item as any} onFileClick={previewFile} onDecision={submitDecision} /> : null
              ))}
              {/* Typing indicator */}
              {isRunning && !timeline.some(e => e.type === 'message' && e.item.role === 'assistant' && (e.item as AGUIMessage).content === '') && (
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
          <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', gap: 10, alignItems: 'flex-end' }}>
            <Input.TextArea value={input} onChange={e => setInput(e.target.value)}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder="Send a message..." autoSize={{ minRows: 1, maxRows: 6 }}
              style={{ borderRadius: 10 }} disabled={isRunning} />
            {isRunning ? (
              <Button danger icon={<StopOutlined />} onClick={() => activeSessionId && cancelRun(activeSessionId)}
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
        <div style={{ display: 'flex', flexShrink: 0 }}>
          {/* Resize handle */}
          <div onMouseDown={startResize} style={{
            width: 4, cursor: 'col-resize', background: 'transparent', flexShrink: 0,
            borderLeft: '1px solid #f0f0f0',
          }}
            onMouseEnter={e => (e.currentTarget.style.background = '#ddd')}
            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          />
        <div style={{ width: sidebarCollapsed ? 36 : sidebarWidth, overflow: 'auto', background: '#fafafa', transition: sidebarCollapsed ? 'width 0.2s' : 'none', position: 'relative' }}>
          {/* Collapse toggle */}
          <div onClick={() => setSidebarCollapsed(!sidebarCollapsed)} style={{
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
              <div onClick={() => setSidebarTab('files')} style={{
                flex: 1, padding: '8px 12px', textAlign: 'center', cursor: 'pointer', fontSize: 12, fontWeight: 600,
                color: sidebarTab === 'files' ? '#1677ff' : '#999',
                borderBottom: sidebarTab === 'files' ? '2px solid #1677ff' : '2px solid transparent',
              }}>Files</div>
            )}
          </div>

          <div style={{ padding: 12 }}>
            {/* Plans tab */}
            {sidebarTab === 'plans' && showPlansSidebar && (
              <Collapse size="small" activeKey={expandedPlanKeys} onChange={keys => setExpandedPlanKeys(keys as string[])}
                items={plans.map(plan => ({
                  key: plan.id,
                  label: (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontWeight: 500, fontSize: 13 }}>{plan.name}</span>
                      <PlanStatusTag status={plan.status} />
                    </div>
                  ),
                  children: (
                    <div style={{ fontSize: 12 }}>
                      {plan.steps?.map((step: any, i: number) => (
                        <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid #eee' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <StepStatusIcon status={step.status} />
                            <span style={{ fontWeight: 500 }}>{step.name}</span>
                          </div>
                          {step.description && <div style={{ color: '#888', marginTop: 2, paddingLeft: 18, fontSize: 11 }}>{step.description}</div>}
                          {step.summary && <div style={{ color: '#666', marginTop: 2, paddingLeft: 18 }}>{step.summary}</div>}
                          {step.outputs?.length > 0 && (
                            <div style={{ paddingLeft: 18, marginTop: 2, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                              {step.outputs.map((p: string, j: number) => (
                                <span key={j} onClick={() => previewFile(p)} style={{
                                  cursor: 'pointer', color: '#1677ff', fontSize: 10,
                                  background: '#f0f5ff', padding: '1px 6px', borderRadius: 3,
                                }}>{p.split('/').pop()}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                      {plan.progress_summary && (
                        <div style={{ marginTop: 8, padding: 6, background: '#f0f5ff', borderRadius: 4, fontSize: 11 }}>{plan.progress_summary}</div>
                      )}
                      {plan.status === 'pending' && (
                        <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                          <Button size="small" type="primary" onClick={() => submitDecision(plan.id, 'approved')}>Approve</Button>
                          <Button size="small" onClick={() => { setFeedbackModal(plan.id); setFeedbackText('') }}>Suggest Edits</Button>
                          <Button size="small" danger onClick={() => submitDecision(plan.id, 'denied')}>Deny</Button>
                        </div>
                      )}
                      {plan.feedback && <div style={{ marginTop: 6, fontSize: 11, color: '#888' }}>Feedback: {plan.feedback}</div>}
                      {plan.mlflow_experiment_id && activeSessionId && (
                        <Button size="small" icon={<ExperimentOutlined />}
                          style={{ marginTop: 8, fontSize: 11 }}
                          onClick={() => openMlflowModal(activeSessionId!)}>
                          View Experiments
                        </Button>
                      )}
                    </div>
                  ),
                }))}
              />
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

      {/* Feedback modal */}
      <Modal title="Suggest Edits" open={!!feedbackModal} onCancel={() => setFeedbackModal(null)}
        onOk={() => { submitDecision(feedbackModal!, 'changes_requested', feedbackText); setFeedbackModal(null) }}
        okText="Submit Feedback">
        <Input.TextArea value={feedbackText} onChange={e => setFeedbackText(e.target.value)}
          rows={4} placeholder="Describe what should be changed..." />
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
    </div>
  )
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

function PlanStatusTag({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'orange', approved: 'blue', running: 'processing', completed: 'green', denied: 'red', changes_requested: 'purple',
  }
  return <Tag color={colors[status] || 'default'} style={{ fontSize: 10 }}>{status}</Tag>
}

function StepStatusIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 12 }} />
  if (status === 'in_progress') return <ClockCircleOutlined style={{ color: '#1677ff', fontSize: 12 }} />
  if (status === 'error') return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 12 }} />
  if (status === 'blocked') return <CloseCircleOutlined style={{ color: '#faad14', fontSize: 12 }} />
  return <span style={{ width: 12, height: 12, borderRadius: '50%', border: '1px solid #d9d9d9', display: 'inline-block' }} />
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
