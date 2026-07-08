"""Serve-time artifact wrapper."""

from __future__ import annotations

import html as html_lib
import json
import re
import secrets
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path


def new_nonce() -> str:
    return secrets.token_urlsafe(16)


def artifact_csp(nonce: str | None = None) -> str:
    script_src = f"script-src 'nonce-{nonce}'" if nonce else "script-src 'unsafe-inline'"
    return (
        "default-src 'none'; "
        f"{script_src}; "
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


ARTIFACT_CSP = artifact_csp()


TOKEN_STYLE = """
<style>
:root {
  color-scheme: light dark;
  --dc-bg: #f7f8fb;
  --dc-surface: #ffffff;
  --dc-surface-raised: #ffffff;
  --dc-surface-muted: #fbfcfe;
  --dc-ink: #111827;
  --dc-muted: #667085;
  --dc-line: #e5e7eb;
  --dc-accent: #2563eb;
  --dc-accent-soft: #e8f0ff;
  --dc-good: #15803d;
  --dc-warn: #b45309;
  --dc-danger: #b91c1c;
  --dc-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
}
:root[data-theme="dark"] {
  --dc-bg: #0f141b;
  --dc-surface: #171d26;
  --dc-surface-raised: #1f2733;
  --dc-surface-muted: #141a22;
  --dc-ink: #f2f5f8;
  --dc-muted: #a5afbd;
  --dc-line: #303846;
  --dc-accent: #7aa7ff;
  --dc-accent-soft: #1b2b46;
  --dc-good: #6dd58c;
  --dc-warn: #f3bd63;
  --dc-danger: #ff8b8b;
  --dc-shadow: none;
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
"""


def theme_runtime(nonce: str) -> str:
    safe_nonce = html_lib.escape(nonce, quote=True)
    return '<script nonce="' + safe_nonce + """">
(() => {
  const externalScheme = /^(https?:|mailto:|tel:|\\/\\/)/i;

  window.addEventListener('message', event => {
    const theme = event && event.data && event.data.theme;
    if (theme === 'light' || theme === 'dark') {
      document.documentElement.dataset.theme = theme;
    }
  });

  document.addEventListener('click', event => {
    if (!event.isTrusted) return;
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


@lru_cache(maxsize=1)
def plotly_runtime_source() -> dict[str, str]:
    vendored = _ui_plotly_bundle_path()
    if vendored.is_file():
        return {"kind": "ui_vendored", "path": str(vendored)}

    try:
        import plotly  # type: ignore

        return {"kind": "python_plotly", "path": str(Path(plotly.__file__).resolve())}
    except Exception:
        return {"kind": "fallback", "path": ""}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _ui_plotly_bundle_path() -> Path:
    return _repo_root() / "ui" / "node_modules" / "plotly.js-dist-min" / "plotly.min.js"


@lru_cache(maxsize=1)
def plotly_runtime_js() -> str:
    source = plotly_runtime_source()
    if source["kind"] == "ui_vendored":
        return Path(source["path"]).read_text(encoding="utf-8").replace("</", "<\\/")

    try:
        try:
            from plotly.offline.offline import get_plotlyjs
        except Exception:
            import plotly.io as pio

            get_plotlyjs = pio.get_plotlyjs

        return get_plotlyjs().replace("</", "<\\/")
    except Exception:
        return """window.Plotly = window.Plotly || {
  newPlot: function(target) {
    var el = typeof target === "string" ? document.getElementById(target) : target;
    if (el) {
      el.innerHTML = '<div style="padding:18px;border:1px solid var(--dc-line);border-radius:8px;color:var(--dc-muted)">Plotly is unavailable in this runtime; chart data is embedded in the report source.</div>';
    }
  },
  react: function(target, data, layout, config) {
    return this.newPlot(target, data, layout, config);
  },
  purge: function() {}
};"""


def _plotly_runtime_tag(*, nonce: str, inline: bool) -> str:
    safe_nonce = html_lib.escape(nonce, quote=True)
    if inline:
        return f'<script nonce="{safe_nonce}">\n{plotly_runtime_js()}\n</script>'
    return f'<script nonce="{safe_nonce}" src="/api/artifacts/artifact-runtime/plotly.min.js"></script>'


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


class _ScriptNonceStamper(HTMLParser):
    def __init__(self, nonce: str) -> None:
        super().__init__(convert_charrefs=False)
        self.nonce = nonce
        self.parts: list[str] = []

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.parts.append(f"<?{data}>")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self._render_tag(tag, attrs, self_closing=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self._render_tag(tag, attrs, self_closing=True))

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def _render_tag(self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool) -> str:
        next_attrs = attrs
        if tag.lower() == "script":
            next_attrs = [attr for attr in attrs if attr[0].lower() != "nonce"]
            next_attrs.insert(0, ("nonce", self.nonce))
        attr_text = "".join(
            f" {name}" if value is None else f' {name}="{html_lib.escape(value, quote=True)}"'
            for name, value in next_attrs
        )
        close = " /" if self_closing else ""
        return f"<{tag}{attr_text}{close}>"


def _stamp_script_nonces(html: str, nonce: str) -> str:
    stamper = _ScriptNonceStamper(nonce)
    stamper.feed(html)
    stamper.close()
    return "".join(stamper.parts)


def _csp_meta(nonce: str) -> str:
    return (
        '<meta http-equiv="Content-Security-Policy" content="'
        + html_lib.escape(artifact_csp(nonce), quote=True)
        + '">'
    )


def _inject_head(html: str, title: str, *, nonce: str, inline_runtime: bool = False) -> str:
    meta = (
        _csp_meta(nonce)
        + TOKEN_STYLE
        + _plotly_runtime_tag(nonce=nonce, inline=inline_runtime)
        + theme_runtime(nonce)
    )
    if "<head" in html.lower():
        injected = re.sub(r"(<head\b[^>]*>)", r"\1" + meta, html, count=1, flags=re.I)
        return _stamp_script_nonces(injected, nonce)
    injected = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html_lib.escape(title)}</title>{meta}</head><body>{html}</body></html>"
    )
    return _stamp_script_nonces(injected, nonce)


def artifact_host_shell(
    *,
    artifact_id: str,
    version: int,
    title: str,
    source: str,
    nonce: str | None = None,
    inline_runtime: bool = False,
) -> str:
    nonce = nonce or new_nonce()
    child = _inject_head(source, title, nonce=nonce, inline_runtime=inline_runtime)
    child_srcdoc = _js_string(child)
    blocked_srcdoc = _js_string(_blocked_navigation_page())
    safe_title = html_lib.escape(title)
    safe_id = html_lib.escape(artifact_id)
    safe_nonce = html_lib.escape(nonce, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_csp_meta(nonce)}
  <title>{safe_title}</title>
  <style>
    html, body {{ margin: 0; height: 100%; background: #f7f8fb; }}
    html[data-theme="dark"], html[data-theme="dark"] body {{ background: #0f141b; }}
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
  <script nonce="{safe_nonce}">
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
        document.documentElement.dataset.theme = theme;
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
        if (event.source !== frame.contentWindow) return;
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


def export_shell(
    *,
    artifact_id: str,
    version: int,
    title: str,
    source: str,
    nonce: str | None = None,
) -> str:
    return artifact_host_shell(
        artifact_id=artifact_id,
        version=version,
        title=title,
        source=source,
        nonce=nonce,
        inline_runtime=True,
    )
