"""Living report manifest compiler."""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

from dataclaw_artifacts.store import artifact_export_url, artifact_url, read_manifest_events, read_meta

PAGES = ["overview", "analyses", "models", "decisions", "log"]


def compile_living_report(artifact_id: str) -> str:
    meta = read_meta(artifact_id)
    events = read_manifest_events(artifact_id)
    title = str(meta.get("title") or "Living Report")
    latest_by_page = _latest_notes_by_page(events)

    page_html = []
    for page in PAGES:
        page_events = events if page == "log" else _events_for_page(events, page)
        page_html.append(_page(page, page_events, latest_by_page.get(page)))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    body {{ margin: 0; background: var(--dc-bg, #f7f8fb); color: var(--dc-ink, #111827); }}
    .lr-page {{ max-width: 1080px; margin: 0 auto; padding: 24px 18px 48px; }}
    .lr-hero {{ margin-bottom: 18px; }}
    .lr-kicker {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--dc-muted, #667085); font-weight: 700; }}
    h1 {{ font-size: 28px; line-height: 1.12; margin: 6px 0 8px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 22px 0 10px; letter-spacing: 0; }}
    h3 {{ font-size: 14px; margin: 0 0 8px; letter-spacing: 0; }}
    .lr-nav {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 14px 0; }}
    .lr-nav a {{ color: var(--dc-accent, #2563eb); text-decoration: none; border: 1px solid var(--dc-line, #e5e7eb); border-radius: 6px; padding: 5px 9px; background: var(--dc-surface, #fff); font-size: 12px; }}
    .lr-entry {{ border: 1px solid var(--dc-line, #e5e7eb); border-radius: 8px; background: var(--dc-surface, #fff); padding: 12px; margin: 10px 0; }}
    .lr-entry.superseded {{ opacity: .78; }}
    .lr-meta {{ display: flex; gap: 8px; flex-wrap: wrap; font-size: 11px; color: var(--dc-muted, #667085); margin-bottom: 8px; }}
    .lr-pill {{ border: 1px solid var(--dc-line, #e5e7eb); border-radius: 999px; padding: 1px 7px; background: var(--dc-surface-raised, #fff); }}
    .lr-md p {{ margin: 0 0 8px; line-height: 1.55; }}
    .lr-actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .lr-action {{ color: var(--dc-accent, #2563eb); text-decoration: none; border: 1px solid var(--dc-line, #e5e7eb); border-radius: 6px; padding: 5px 9px; background: var(--dc-surface-raised, #fff); font-size: 12px; font-weight: 600; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: var(--dc-surface-raised, #fff); border: 1px solid var(--dc-line, #e5e7eb); border-radius: 6px; padding: 8px; font-size: 11px; }}
    .lr-empty {{ color: var(--dc-muted, #667085); font-size: 13px; }}
  </style>
</head>
<body>
  <main class="lr-page">
    <section class="lr-hero">
      <div class="lr-kicker">DataClaw living report</div>
      <h1>{_esc(title)}</h1>
      <div class="lr-meta">
        <span class="lr-pill">{len(events)} events</span>
        <span class="lr-pill">{_esc(str(meta.get("session_id") or ""))}</span>
      </div>
    </section>
    <nav class="lr-nav">{''.join(f'<a href="#{p}">{p.title()}</a>' for p in PAGES)}</nav>
    {''.join(page_html)}
  </main>
</body>
</html>"""


def _events_for_page(events: list[dict[str, Any]], page: str) -> list[dict[str, Any]]:
    if page == "overview":
        return [
            e for e in events
            if e.get("page") in ("overview", None)
            or e.get("kind") in {"metric", "artifact_published", "plan_update"}
        ]
    if page == "analyses":
        return [e for e in events if e.get("page") == "analyses" or e.get("kind") in {"cell_output", "artifact_published"}]
    if page == "models":
        return [e for e in events if e.get("page") == "models" or e.get("kind") in {"mlflow_run", "mlflow_snapshot"}]
    if page == "decisions":
        return [e for e in events if e.get("page") == "decisions" or e.get("kind") in {"decision", "plan_update"}]
    return events


def _latest_notes_by_page(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("kind") != "note":
            continue
        page = str(event.get("page") or "overview")
        latest[page] = event
    return latest


def _page(page: str, events: list[dict[str, Any]], headline: dict[str, Any] | None) -> str:
    body = []
    if headline and page != "log":
        body.append(_entry(headline, headline=True))
    body.extend(_entry(e) for e in events)
    if not body:
        body.append('<p class="lr-empty">No entries yet.</p>')
    return f"""<section id="{page}">
      <h2>{page.title()}</h2>
      {''.join(body)}
    </section>"""


def _entry(event: dict[str, Any], headline: bool = False) -> str:
    raw_kind = str(event.get("kind") or "event")
    event_id = _esc(str(event.get("id") or ""))
    kind = _esc(raw_kind)
    status = str(event.get("status") or "active")
    page = _esc(str(event.get("page") or ""))
    step = _esc(str(event.get("plan_step_id") or ""))
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    classes = "lr-entry"
    if status == "superseded":
        classes += " superseded"

    title = _esc(str(payload.get("title") or payload.get("label") or kind.replace("_", " ").title()))
    md = str(payload.get("md") or payload.get("summary") or "")
    details = "" if md else f"<pre>{_esc(json.dumps(payload or event, indent=2, default=str))}</pre>"
    actions = _artifact_actions(payload) if raw_kind == "artifact_published" else ""
    return f"""<article id="{event_id}" class="{classes}">
      <div class="lr-meta">
        <span class="lr-pill">#{event_id}</span>
        <span class="lr-pill">{kind}</span>
        {f'<span class="lr-pill">{page}</span>' if page else ''}
        {f'<span class="lr-pill">step {step}</span>' if step else ''}
        {f'<span class="lr-pill">headline</span>' if headline else ''}
        {_artifact_version_pill(payload) if raw_kind == "artifact_published" else ''}
      </div>
      <h3>{title}</h3>
      {f'<div class="lr-md">{_markdownish(md)}</div>' if md else details}
      {actions}
    </article>"""


def _markdownish(markdown: str) -> str:
    blocks = [b.strip() for b in markdown.split("\n\n") if b.strip()]
    return "".join(f"<p>{_esc(block)}</p>" for block in blocks)


def _artifact_version_pill(payload: dict[str, Any]) -> str:
    version = payload.get("version")
    if not version:
        return ""
    return f'<span class="lr-pill">v{_esc(str(version))}</span>'


def _artifact_actions(payload: dict[str, Any]) -> str:
    artifact_id = str(payload.get("artifact_id") or "")
    session_id = str(payload.get("session_id") or "")
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if not artifact_id or not version or not session_id:
        return ""
    open_url = str(payload.get("url") or artifact_url(artifact_id, version, session_id))
    export_url = artifact_export_url(artifact_id, version, session_id)
    return (
        '<div class="lr-actions">'
        f'<a class="lr-action" href="{_esc(open_url)}">Open artifact</a>'
        f'<a class="lr-action" href="{_esc(export_url)}">Export HTML</a>'
        "</div>"
    )


def _esc(value: str) -> str:
    return html_lib.escape(value, quote=True)
