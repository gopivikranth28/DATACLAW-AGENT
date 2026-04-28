import { Image } from 'antd'
import { API } from '../../api'

interface ImageData {
  path?: string
  title?: string
  caption?: string
}

export default function ImageDisplay({ data }: { data: ImageData }) {
  if (!data.path) return <div style={{ color: '#999', fontSize: 12 }}>No image path</div>

  const src = `${API}/workspace/files?path=${encodeURIComponent(data.path)}`

  return (
    <div>
      {data.title && <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 4 }}>{data.title}</div>}
      <Image
        src={src}
        alt={data.caption || data.title || 'Image'}
        style={{ maxWidth: '100%', borderRadius: 4 }}
        fallback="data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI2Y1ZjVmNSIvPjx0ZXh0IHg9IjEwMCIgeT0iNTAiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIiBmaWxsPSIjOTk5IiBmb250LXNpemU9IjEyIj5JbWFnZSBub3QgZm91bmQ8L3RleHQ+PC9zdmc+"
      />
      {data.caption && <div style={{ fontSize: 11, color: '#666', fontStyle: 'italic', marginTop: 4 }}>{data.caption}</div>}
    </div>
  )
}
