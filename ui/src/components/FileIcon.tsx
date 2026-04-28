import {
  FileOutlined, FileTextOutlined, CodeOutlined,
  BookOutlined, TableOutlined, PictureOutlined,
  DatabaseOutlined, SettingOutlined,
} from '@ant-design/icons'

const EXT_MAP: Record<string, { icon: typeof FileOutlined; color: string }> = {
  '.py': { icon: CodeOutlined, color: '#3572A5' },
  '.js': { icon: CodeOutlined, color: '#f1e05a' },
  '.ts': { icon: CodeOutlined, color: '#3178c6' },
  '.tsx': { icon: CodeOutlined, color: '#3178c6' },
  '.jsx': { icon: CodeOutlined, color: '#f1e05a' },
  '.ipynb': { icon: BookOutlined, color: '#e37933' },
  '.csv': { icon: TableOutlined, color: '#52c41a' },
  '.tsv': { icon: TableOutlined, color: '#52c41a' },
  '.parquet': { icon: DatabaseOutlined, color: '#52c41a' },
  '.md': { icon: FileTextOutlined, color: '#888' },
  '.txt': { icon: FileTextOutlined, color: '#888' },
  '.log': { icon: FileTextOutlined, color: '#888' },
  '.json': { icon: FileOutlined, color: '#8b5cf6' },
  '.yaml': { icon: SettingOutlined, color: '#8b5cf6' },
  '.yml': { icon: SettingOutlined, color: '#8b5cf6' },
  '.toml': { icon: SettingOutlined, color: '#8b5cf6' },
  '.sql': { icon: DatabaseOutlined, color: '#e38c00' },
  '.r': { icon: CodeOutlined, color: '#276DC3' },
  '.html': { icon: CodeOutlined, color: '#e34c26' },
  '.css': { icon: CodeOutlined, color: '#563d7c' },
  '.png': { icon: PictureOutlined, color: '#eb2f96' },
  '.jpg': { icon: PictureOutlined, color: '#eb2f96' },
  '.jpeg': { icon: PictureOutlined, color: '#eb2f96' },
  '.svg': { icon: PictureOutlined, color: '#eb2f96' },
  '.gif': { icon: PictureOutlined, color: '#eb2f96' },
  '.sh': { icon: CodeOutlined, color: '#89e051' },
  '.bash': { icon: CodeOutlined, color: '#89e051' },
}

export default function FileIcon({ name, size = 11 }: { name: string; size?: number }) {
  const ext = name.match(/\.[^.]+$/)?.[0]?.toLowerCase() || ''
  const match = EXT_MAP[ext]
  if (match) {
    const Icon = match.icon
    return <Icon style={{ fontSize: size, color: match.color }} />
  }
  return <FileOutlined style={{ fontSize: size, color: '#bbb' }} />
}
