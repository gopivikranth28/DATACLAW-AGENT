import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

interface WebTerminalProps {
  wsUrl: string
  initialCommand?: string
  onConnected?: () => void
  onDisconnected?: () => void
  style?: React.CSSProperties
}

export default function WebTerminal({ wsUrl, initialCommand, onConnected, onDisconnected, style }: WebTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: {
        background: '#1a1a1a',
        foreground: '#cccccc',
        cursor: '#cccccc',
      },
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(container)
    fitAddon.fit()
    termRef.current = term

    // Connect WebSocket
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      // Send initial terminal size
      ws.send(JSON.stringify({ cols: term.cols, rows: term.rows }))
      onConnected?.()

      // Send initial command after shell has time to initialize
      if (initialCommand) {
        setTimeout(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(initialCommand + '\n')
          }
        }, 500)
      }
    }

    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(e.data))
      } else {
        term.write(e.data)
      }
    }

    ws.onclose = () => {
      term.write('\r\n\x1b[90m[Terminal disconnected]\x1b[0m\r\n')
      onDisconnected?.()
    }

    // User input → WebSocket
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    // Handle resize
    const ro = new ResizeObserver(() => {
      fitAddon.fit()
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      ws.close()
      term.dispose()
      termRef.current = null
      wsRef.current = null
    }
  }, [wsUrl]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: 320,
        borderRadius: 6,
        overflow: 'hidden',
        ...style,
      }}
    />
  )
}
