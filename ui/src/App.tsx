import { useState, useEffect } from 'react'
import { Routes, Route, Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, ConfigProvider, theme } from 'antd'
import {
  MessageOutlined, BulbOutlined, SettingOutlined,
  DatabaseOutlined, FolderOutlined, PlusOutlined, EllipsisOutlined,
} from '@ant-design/icons'
import { API } from './api'
import ChatPage from './pages/ChatPage'
import SkillsPage from './pages/SkillsPage'
import ConfigPage from './pages/ConfigPage'
import DataPage from './pages/DataPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectPage from './pages/ProjectPage'
// import SubagentsPage from './pages/SubagentsPage'

const { Sider, Content } = Layout

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

export default function App() {
  const { pathname } = useLocation()
  const [plugins, setPlugins] = useState<PluginInfo[]>([])

  useEffect(() => {
    fetch(`${API}/plugins`).then(r => r.ok ? r.json() : []).then(setPlugins).catch(() => {})
  }, [])

  const pluginIds = new Set(plugins.map(p => p.id))
  const hasData = pluginIds.has('data')
  const hasProjects = pluginIds.has('projects')

  const nav = [
    { key: '/chat', icon: <MessageOutlined />, label: <Link to="/chat">Chat</Link> },
    ...(hasData ? [{ key: '/data', icon: <DatabaseOutlined />, label: <Link to="/data">Data</Link> }] : []),
    // Subagents tab hidden — not ready for release
    // ...(hasProjects ? [
    //   { key: '/subagents', icon: <TeamOutlined />, label: <Link to="/subagents">Subagents</Link> },
    // ] : []),
    { key: '/skills', icon: <BulbOutlined />, label: <Link to="/skills">Skills</Link> },
    { key: '/config', icon: <SettingOutlined />, label: <Link to="/config">Config</Link> },
  ]

  const selected = nav.map(n => n.key).filter(k => pathname.startsWith(k)).at(-1) ?? ''

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#2563eb', borderRadius: 8, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif" }, algorithm: theme.defaultAlgorithm }}>
      <Layout style={{ height: '100vh' }}>
        <Sider theme="dark" width={200} style={{ overflow: 'auto', background: '#111827' }}>
          <div style={{ padding: '20px 20px 16px', color: '#f9fafb', fontWeight: 700, fontSize: 17, letterSpacing: '-0.3px', display: 'flex', alignItems: 'center', gap: 8 }}>
            <img src="/logo_transparent.png" alt="Dataclaw" style={{ height: 28 }} />
            Dataclaw
          </div>
          {hasProjects && <SidebarProjects />}
          <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={nav}
            style={{ background: 'transparent', borderInlineEnd: 'none', marginTop: hasProjects ? 4 : 0 }} />
        </Sider>
        <Content style={{ overflow: 'auto', background: '#fff' }}>
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/skills" element={<SkillsPage />} />
            <Route path="/config" element={<ConfigPage plugins={plugins} />} />
            {hasData && <Route path="/data" element={<DataPage />} />}
            {hasProjects && (
              <>
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/:id" element={<ProjectPage />} />
                {/* <Route path="/subagents" element={<SubagentsPage />} /> */}
              </>
            )}
          </Routes>
        </Content>
      </Layout>
    </ConfigProvider>
  )
}
