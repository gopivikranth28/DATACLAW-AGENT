import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Alert, Button, Card, Input, Typography } from 'antd'
import { API } from '../api'

// When the server requires an API token (non-loopback bind, or app.auth =
// "token"), show a small token prompt instead of the app. Logging in sets an
// HttpOnly session cookie, which every later fetch, EventSource and the
// terminal WebSocket send automatically.

const UNAUTHORIZED_EVENT = 'dataclaw:unauthorized'

function isApiRequest(input: RequestInfo | URL): boolean {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, window.location.href)
  return url.origin === window.location.origin
    && url.pathname.startsWith('/api/')
    && !url.pathname.startsWith('/api/auth/')
}

let fetchPatched = false

// Any 401 from the API (e.g. the token was rotated) brings the prompt back.
function watchForUnauthorized() {
  if (fetchPatched) return
  fetchPatched = true
  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input, init) => {
    const response = await originalFetch(input, init)
    if (response.status === 401 && isApiRequest(input)) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    }
    return response
  }
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'ok' | 'login'>('checking')
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    watchForUnauthorized()
    const onUnauthorized = () => setState('login')
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    fetch(`${API}/auth/status`)
      .then(r => (r.ok ? r.json() : null))
      .then(status => setState(status?.auth_required && !status.authenticated ? 'login' : 'ok'))
      .catch(() => setState('ok'))
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim() }),
      })
      if (!r.ok) {
        setError('That token was not accepted.')
        return
      }
      // Reload so every view refetches with the new session cookie.
      window.location.reload()
    } catch {
      setError('Could not reach the Dataclaw server.')
    } finally {
      setSubmitting(false)
    }
  }

  if (state === 'checking') return null
  if (state === 'ok') return <>{children}</>

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f6f8' }}>
      <Card style={{ width: 380 }} title="Dataclaw access token">
        <form onSubmit={submit}>
          <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
            This server requires an access token. Use the login URL from the server log,
            or the token in <code>~/.dataclaw/api-token</code> (or <code>DATACLAW_TOKEN</code>).
          </Typography.Paragraph>
          <Input.Password
            autoFocus
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="Access token"
            style={{ marginBottom: 12 }}
          />
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
          <Button type="primary" htmlType="submit" block loading={submitting} disabled={!token.trim()}>
            Log in
          </Button>
        </form>
      </Card>
    </div>
  )
}
