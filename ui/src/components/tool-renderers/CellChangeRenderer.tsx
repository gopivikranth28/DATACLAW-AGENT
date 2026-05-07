import CellSourceView from './CellSourceView'

interface CellChangeData {
  cell_index?: number
  inserted_at?: number
  cell_type?: string
  source?: string
  num_cells?: number
}

interface InsertCellArgs {
  source?: string
  cell_type?: string
  index?: number
}

/**
 * Renderer for `insert_cell` tool results. Shows the inserted cell's source
 * with syntax highlighting and a small header noting where it landed.
 *
 * For results that don't carry `source` (chat history persisted before the
 * backend began echoing source), we fall back to the source the LLM passed
 * in the tool call's args — same content, just a different storage slot.
 */
export default function CellChangeRenderer({ data, args }: { data: CellChangeData; args?: InsertCellArgs }) {
  const index = data.cell_index ?? data.inserted_at
  const cellType = (data.cell_type ?? args?.cell_type) === 'markdown' ? 'markdown' : 'code'
  const source = data.source ?? args?.source ?? ''

  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 4 }}>
        Inserted {cellType} cell{index !== undefined ? ` at [${index}]` : ''}
      </div>
      {source ? (
        <CellSourceView source={source} cellType={cellType} />
      ) : (
        <div style={{ fontSize: 11, color: '#999', fontStyle: 'italic' }}>
          (source not available)
        </div>
      )}
    </div>
  )
}
