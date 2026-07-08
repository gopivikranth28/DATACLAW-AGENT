"""Serve-time artifact wrapper."""

from __future__ import annotations

import html as html_lib
import json
import re


ARTIFACT_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "font-src data:; "
    "frame-src 'self' data: blob:; "
    "child-src 'self' data: blob:; "
    "connect-src 'none'; "
    "navigate-to 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors http://localhost:* http://127.0.0.1:* http://[::1]:*"
)


TOKEN_STYLE = """
<style>
:root {
  color-scheme: light dark;
  --dc-bg: #f7f8fb;
  --dc-surface: #ffffff;
  --dc-surface-raised: #ffffff;
  --dc-ink: #111827;
  --dc-muted: #667085;
  --dc-line: #e5e7eb;
  --dc-accent: #2563eb;
  --dc-accent-soft: #e8f0ff;
  --dc-good: #15803d;
  --dc-warn: #b45309;
  --dc-danger: #b91c1c;
}
:root[data-theme="dark"] {
  --dc-bg: #0f141b;
  --dc-surface: #171d26;
  --dc-surface-raised: #1f2733;
  --dc-ink: #f2f5f8;
  --dc-muted: #a5afbd;
  --dc-line: #303846;
  --dc-accent: #7aa7ff;
  --dc-accent-soft: #1b2b46;
  --dc-good: #6dd58c;
  --dc-warn: #f3bd63;
  --dc-danger: #ff8b8b;
}
html, body {
  margin: 0;
  min-height: 100%;
  background: var(--dc-bg);
  color: var(--dc-ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
</style>
<script>
(() => {
  const externalScheme = /^(https?:|mailto:|tel:|\\/\\/)/i;

  window.addEventListener('message', event => {
    const theme = event && event.data && event.data.theme;
    if (theme === 'light' || theme === 'dark') {
      document.documentElement.dataset.theme = theme;
    }
  });

  document.addEventListener('click', event => {
    const target = event.target;
    const link = target && target.closest ? target.closest('a[href]') : null;
    if (!link) return;

    const href = link.getAttribute('href') || '';
    if (!externalScheme.test(href.trim())) return;

    event.preventDefault();
    window.parent && window.parent.postMessage({
      type: 'artifact_external_link',
      href: link.href,
    }, '*');
  }, true);
})();
</script>
"""


def _js_string(value: str) -> str:
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _blocked_navigation_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #f7f8fb;
      color: #475467;
      font: 14px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      max-width: 520px;
      padding: 24px;
      text-align: center;
    }
    h1 {
      margin: 0 0 8px;
      color: #111827;
      font-size: 18px;
      letter-spacing: 0;
    }
  </style>
</head>
<body>
  <main>
    <h1>Blocked artifact navigation</h1>
    <p>This artifact attempted to navigate away from its sandboxed document, so DataClaw replaced the frame.</p>
  </main>
</body>
</html>"""


def _inject_head(html: str, title: str) -> str:
    meta = (
        '<meta http-equiv="Content-Security-Policy" content="'
        + html_lib.escape(ARTIFACT_CSP, quote=True)
        + '">'
        + TOKEN_STYLE
    )
    if "<head" in html.lower():
        return re.sub(r"(<head\b[^>]*>)", r"\1" + meta, html, count=1, flags=re.I)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html_lib.escape(title)}</title>{meta}</head><body>{html}</body></html>"
    )


def artifact_host_shell(*, artifact_id: str, version: int, title: str, source: str) -> str:
    child = _inject_head(source, title)
    child_srcdoc = _js_string(child)
    blocked_srcdoc = _js_string(_blocked_navigation_page())
    safe_title = html_lib.escape(title)
    safe_id = html_lib.escape(artifact_id)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    html, body {{ margin: 0; height: 100%; background: #f7f8fb; }}
    body {{ overflow: hidden; }}
    .artifact-frame {{ display: block; width: 100%; height: 100vh; border: 0; background: #fff; }}
  </style>
</head>
<body data-artifact-id="{safe_id}" data-version="{version}">
  <iframe
    id="artifact-frame"
    class="artifact-frame"
    sandbox="allow-scripts"
  ></iframe>
  <script>
    const frame = document.getElementById('artifact-frame');
    const artifactSrcdoc = {child_srcdoc};
    const blockedSrcdoc = {blocked_srcdoc};
    let loadedArtifact = false;
    let blockedNavigation = false;

    const blockNavigation = () => {{
      if (blockedNavigation) return;
      blockedNavigation = true;
      frame.srcdoc = blockedSrcdoc;
    }};

    frame.addEventListener('load', () => {{
      if (!loadedArtifact) {{
        loadedArtifact = true;
        return;
      }}
      blockNavigation();
    }});

    const applyTheme = (theme) => {{
      if (theme === 'light' || theme === 'dark') {{
        frame.contentWindow && frame.contentWindow.postMessage({{ theme }}, '*');
      }}
    }};

    const openExternal = (href) => {{
      try {{
        const url = new URL(href);
        if (['http:', 'https:', 'mailto:', 'tel:'].includes(url.protocol)) {{
          window.open(url.href, '_blank', 'noopener,noreferrer');
        }}
      }} catch (_) {{}}
    }};

    window.addEventListener('message', event => {{
      const data = event && event.data;
      if (data && data.type === 'artifact_external_link' && typeof data.href === 'string') {{
        openExternal(data.href);
        return;
      }}

      const theme = data && data.theme;
      applyTheme(theme);
    }});

    frame.srcdoc = artifactSrcdoc;
    applyTheme(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  </script>
</body>
</html>"""


def export_shell(*, artifact_id: str, version: int, title: str, source: str) -> str:
    return artifact_host_shell(artifact_id=artifact_id, version=version, title=title, source=source)
