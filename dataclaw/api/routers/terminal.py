"""WebSocket terminal — PTY-backed interactive shell over WebSocket.

Used by the Config page for interactive OpenClaw commands like
`openclaw models auth login --set-default` that require user input.

Protocol:
1. Client sends initial JSON: {"cols": 80, "rows": 24}
2. Client sends text frames with user keystrokes.
3. Client may send JSON frames: {"type": "resize", "cols": N, "rows": N}
4. Server sends binary frames with terminal output.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Set the terminal window size on a PTY file descriptor."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


@router.websocket("/ws")
async def terminal_ws(ws: WebSocket):
    """Spawn an interactive shell over a PTY, relay I/O via WebSocket."""
    await ws.accept()

    # Receive initial size message
    try:
        init_raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        init = json.loads(init_raw)
        cols = int(init.get("cols", 80))
        rows = int(init.get("rows", 24))
    except Exception:
        await ws.close(code=1002, reason="Expected initial JSON {cols, rows}")
        return

    # Create PTY pair and spawn shell
    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, rows, cols)

    shell = os.environ.get("SHELL", "/bin/bash")
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    # Prevent OpenClaw from detecting a headless environment.
    # The embedded terminal IS the user's local UI.
    env.setdefault("DISPLAY", ":0")

    proc = subprocess.Popen(
        [shell, "-l"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        env=env,
    )
    os.close(slave_fd)

    loop = asyncio.get_event_loop()

    async def _read_pty():
        """Read from PTY master and forward to WebSocket."""
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
                if not data:
                    break
                await ws.send_bytes(data)
        except (OSError, WebSocketDisconnect):
            pass

    async def _write_pty():
        """Read from WebSocket and forward to PTY master."""
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break

                raw = msg.get("text") or msg.get("bytes", b"")
                if not raw:
                    continue

                # Check for JSON control messages
                if isinstance(raw, str):
                    try:
                        ctrl = json.loads(raw)
                        if isinstance(ctrl, dict) and ctrl.get("type") == "resize":
                            _set_winsize(master_fd, int(ctrl["rows"]), int(ctrl["cols"]))
                            continue
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
                    raw = raw.encode()

                await loop.run_in_executor(None, os.write, master_fd, raw)
        except (OSError, WebSocketDisconnect):
            pass

    try:
        done, pending = await asyncio.wait(
            [asyncio.ensure_future(_read_pty()), asyncio.ensure_future(_write_pty())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        proc.kill()
        proc.wait()
        try:
            os.close(master_fd)
        except OSError:
            pass
