import type { CSSProperties } from 'react'

interface CellDiffData {
  cell_index?: number
  diff?: string
}

type LineKind = 'add' | 'remove' | 'hunk' | 'context'

const LINE_STYLE: Record<LineKind, CSSProperties> = {
  add:     { background: '#e6ffed', color: '#22863a' },
  remove:  { background: '#ffeef0', color: '#b31d28' },
  hunk:    { background: '#f1f8ff', color: '#005cc5', fontStyle: 'italic' },
  context: { color: '#444' },
}

function classify(line: string): LineKind | null {
  // Suppress the file-header lines from `difflib.unified_diff` — they say
  // "before"/"after" which adds no information for cell edits.
  if (line.startsWith('+++') || line.startsWith('---')) return null
  if (line.startsWith('@@')) return 'hunk'
  if (line.startsWith('+')) return 'add'
  if (line.startsWith('-')) return 'remove'
  return 'context'
}

/**
 * Renderer for `edit_cell` / `edit_cell_source` tool results. The backend
 * already produces a unified diff via difflib.unified_diff; this renders it
 * with line-level coloring without bringing in a diff library.
 *
 * Accepts (but ignores) `args` for parity with the other cell renderers
 * routed from ToolResultRenderer.
 */
export default function CellDiffRenderer({ data }: { data: CellDiffData; args?: unknown }) {
  const index = data.cell_index
  const diff = (data.diff || '').replace(/\n$/, '')

  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>
        Edited cell{index !== undefined ? ` [${index}]` : ''}
      </div>
      {diff ? (
        <pre style={{
          fontSize: 11, background: '#fafafa', padding: 6, borderRadius: 4,
          border: '1px solid #e8e8e8', overflow: 'auto', margin: 0,
          fontFamily: 'monospace', lineHeight: 1.5,
        }}>
          {diff.split('\n').map((line, i) => {
            const kind = classify(line)
            if (kind === null) return null
            return (
              <div key={i} style={{ ...LINE_STYLE[kind], padding: '0 4px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {line || ' '}
              </div>
            )
          })}
        </pre>
      ) : (
        <div style={{ fontSize: 11, color: '#999', fontStyle: 'italic' }}>
          (no diff available)
        </div>
      )}
    </div>
  )
}
