import { lazy, Suspense, useState, useEffect } from 'react'
import { Routes, Route, Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, ConfigProvider, theme } from 'antd'
import {
  MessageOutlined, BulbOutlined, SettingOutlined, TeamOutlined,
  DatabaseOutlined, FolderOutlined, PlusOutlined, EllipsisOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { API } from './api'

const { Sider, Content } = Layout

const ChatPage = lazy(() => import('./pages/ChatPage'))
const SkillsPage = lazy(() => import('./pages/SkillsPage'))
const ConfigPage = lazy(() => import('./pages/ConfigPage'))
const DataPage = lazy(() => import('./pages/DataPage'))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage'))
const ProjectPage = lazy(() => import('./pages/ProjectPage'))
const SubagentsPage = lazy(() => import('./pages/SubagentsPage'))
const ToolsPage = lazy(() => import('./pages/ToolsPage'))
const AppPage = lazy(() => import('./pages/AppPage'))

const THEME = {
  token: { colorPrimary: '#2563eb', borderRadius: 8, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif" },
  algorithm: theme.defaultAlgorithm,
}

interface PluginInfo {
  id: string; name: string; label: string; icon: string
  pages: { path: string; label: string }[]
  config_schema: { title: string; fields: any[] } | null
}

interface Project { id: string; name: string; created_at: string }

function SidebarProjects() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [projects, setProjects] = useState<Project[]>([])
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    fetch(`${API}/projects/`).then(r => r.ok ? r.json() : [])
      .then((all: Project[]) => setProjects([...all].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())))
      .catch(() => {})
  }, [pathname])

  const recent = projects.slice(0, 5)
  const activeId = pathname.match(/^\/projects\/([^/]+)/)?.[1]

  return (
    <div style={{ padding: '0 4px' }}>
      <div onClick={() => setExpanded(!expanded)} style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', cursor: 'pointer',
        color: pathname.startsWith('/projects') ? '#fff' : 'rgba(255,255,255,0.65)',
        fontWeight: 600, fontSize: 13, userSelect: 'none',
      }}>
        <FolderOutlined style={{ fontSize: 13 }} />
        <span style={{ flex: 1 }}>Projects</span>
        <span style={{ fontSize: 10, transition: 'transform 0.2s', transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
      </div>
      {expanded && (
        <div style={{ paddingLeft: 20 }}>
          {recent.map(p => (
            <div key={p.id} onClick={() => navigate(`/projects/${p.id}`)} style={{
              padding: '4px 12px', cursor: 'pointer', fontSize: 12, borderRadius: 4,
              color: activeId === p.id ? '#fff' : 'rgba(255,255,255,0.55)',
              background: activeId === p.id ? 'rgba(255,255,255,0.08)' : 'transparent',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: 1,
            }} title={p.name}>{p.name}</div>
          ))}
          <div onClick={() => navigate('/projects')} style={{ padding: '4px 12px', cursor: 'pointer', fontSize: 11, color: 'rgba(255,255,255,0.4)', display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
            <EllipsisOutlined /> All Projects
          </div>
          <div onClick={() => navigate('/projects?new=1')} style={{ padding: '4px 12px', cursor: 'pointer', fontSize: 11, color: 'rgba(255,255,255,0.4)', display: 'flex', alignItems: 'center', gap: 4 }}>
            <PlusOutlined /> New Project
          </div>
        </div>
      )}
    </div>
  )
}

function SidebarChats({ compact }: { compact: boolean }) {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const createChat = () => {
    // Confirm the dataset scope before creating anything. This makes Cancel a
    // true cancel rather than a best-effort delete of a half-created session.
    navigate('/chat?new_independent_chat=1')
  }

  return (
    <div style={{ position: 'relative', padding: '0 4px' }}>
      <Menu
        theme="dark"
        mode="inline"
        inlineCollapsed={compact}
        selectedKeys={pathname.startsWith('/chat') ? ['/chat'] : []}
        items={[{ key: '/chat', icon: <MessageOutlined />, label: <Link to="/chat">Independent chats</Link> }]}
        style={{ background: 'transparent', borderInlineEnd: 'none' }}
      />
      {!compact && (
        <button
          type="button"
          aria-label="New independent chat"
          title="New chat"
          onClick={createChat}
          style={{
            position: 'absolute', right: 12, top: 8, width: 24, height: 24,
            display: 'grid', placeItems: 'center', border: 0, borderRadius: 5,
            color: 'rgba(255,255,255,.8)', background: 'transparent', cursor: 'pointer',
          }}
        >
          <PlusOutlined style={{ fontSize: 13 }} />
        </button>
      )}
    </div>
  )
}

export default function App() {
  const { pathname } = useLocation()
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [viewportWidth, setViewportWidth] = useState(() => window.innerWidth)

  useEffect(() => {
    fetch(`${API}/plugins`).then(r => r.ok ? r.json() : []).then(setPlugins).catch(() => {})
  }, [])

  useEffect(() => {
    const updateViewport = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', updateViewport)
    return () => window.removeEventListener('resize', updateViewport)
  }, [])

  const pluginIds = new Set(plugins.map(p => p.id))
  const hasData = pluginIds.has('data')
  const hasProjects = pluginIds.has('projects')
  const hasTools = pluginIds.has('custom-tools')

  const nav = [
    // Chats is the independent-session surface. Project-scoped sessions are
    // intentionally listed only from their project pages.
    { key: '/chat', icon: <MessageOutlined />, label: <Link to="/chat">Independent chats</Link> },
    ...(hasData ? [{ key: '/data', icon: <DatabaseOutlined />, label: <Link to="/data">Data</Link> }] : []),
    ...(hasProjects ? [
      { key: '/subagents', icon: <TeamOutlined />, label: <Link to="/subagents">Subagents</Link> },
    ] : []),
    ...(hasTools ? [{ key: '/tools', icon: <ToolOutlined />, label: <Link to="/tools">Tools</Link> }] : []),
    { key: '/skills', icon: <BulbOutlined />, label: <Link to="/skills">Skills</Link> },
    { key: '/config', icon: <SettingOutlined />, label: <Link to="/config">Config</Link> },
  ]

  const selected = nav.map(n => n.key).filter(k => pathname.startsWith(k)).at(-1) ?? ''
  const resourceNav = nav.filter(item => item.key !== '/chat' && item.key !== '/config')
  const configNav = nav.filter(item => item.key === '/config')
  const compactNav = viewportWidth <= 1160
  const hiddenNav = viewportWidth <= 760

  // Legacy compatibility app view — standalone surface, no navigation chrome.
  if (pathname.startsWith('/app/')) {
    return (
      <ConfigProvider theme={THEME}>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/app/:sessionId" element={<AppPage />} />
          </Routes>
        </Suspense>
      </ConfigProvider>
    )
  }

  return (
    <ConfigProvider theme={THEME}>
      <Layout style={{ height: '100vh' }}>
        <Sider theme="dark" width={200} collapsed={compactNav} collapsedWidth={hiddenNav ? 0 : 56} trigger={null} style={{ overflow: 'hidden', background: 'var(--rail)' }}>
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {!hiddenNav && (compactNav ? (
              <div aria-label="Dataclaw" style={{ display: 'grid', placeItems: 'center', height: 54 }}><BrandMark size={28} /></div>
            ) : (
              <div style={{ padding: '18px 18px 14px', color: '#f9fafb', fontWeight: 700, fontSize: 17, letterSpacing: '-0.3px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <BrandMark />
                <span>Dataclaw</span>
              </div>
            ))}
            <SidebarChats compact={compactNav} />
            {!compactNav && hasProjects && <SidebarProjects />}
            {!compactNav && <div style={{ padding: '14px 18px 4px', color: 'var(--rail-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.06em' }}>Resources</div>}
            <Menu theme="dark" mode="inline" inlineCollapsed={compactNav} selectedKeys={[selected]} items={resourceNav}
              style={{ background: 'transparent', borderInlineEnd: 'none' }} />
            <div style={{ flex: 1 }} />
            <Menu theme="dark" mode="inline" inlineCollapsed={compactNav} selectedKeys={[selected]} items={configNav}
              style={{ background: 'transparent', borderInlineEnd: 'none', marginBottom: 8 }} />
          </div>
        </Sider>
        <Content style={{ overflow: 'auto', background: '#fff' }}>
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/config" element={<ConfigPage plugins={plugins} />} />
              {hasTools && <Route path="/tools" element={<ToolsPage />} />}
              {hasData && <Route path="/data" element={<DataPage />} />}
              {hasProjects && (
                <>
                  <Route path="/projects" element={<ProjectsPage />} />
                  <Route path="/projects/:id" element={<ProjectPage />} />
                  <Route path="/subagents" element={<SubagentsPage />} />
                </>
              )}
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </ConfigProvider>
  )
}

function BrandMark({ size = 30 }: { size?: number }) {
  // The supplied PNG includes a large black wordmark beneath the icon.  At
  // sidebar scale, rendering the whole image makes both the symbol and its
  // lettering too small—and the black strokes vanish against the dark rail.
  // Crop the icon in a light tile so the actual brand mark stays legible.
  const imageSize = Math.round(size * 5 / 4)
  return (
    <span aria-hidden="true" style={{
      position: 'relative', display: 'block', flex: '0 0 auto', width: size, height: size,
      overflow: 'hidden', border: '1px solid rgba(255,255,255,0.5)', borderRadius: Math.max(7, Math.round(size / 4)),
      background: '#f8fafc', boxShadow: '0 1px 3px rgba(0,0,0,0.28)',
    }}>
      <img src="/logo_transparent.png" alt="" style={{
        position: 'absolute', top: 0, left: '50%', width: imageSize, maxWidth: 'none', height: 'auto',
        transform: 'translateX(-50%)',
      }} />
    </span>
  )
}

function RouteFallback() {
  return (
    <div style={{ minHeight: '100%', display: 'grid', placeItems: 'center', color: '#8c8c8c', fontSize: 13 }}>
      Loading...
    </div>
  )
}
