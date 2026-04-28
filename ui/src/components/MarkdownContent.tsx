import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const FILE_EXTENSIONS = new Set([
  '.csv', '.py', '.ipynb', '.md', '.json', '.parquet', '.html', '.svg',
  '.txt', '.yaml', '.yml', '.toml', '.sql', '.r', '.rmd', '.tsv',
  '.log', '.sh', '.bash', '.xml', '.cfg', '.ini', '.env',
])

function isFilePath(href: string): boolean {
  // Skip http/https URLs
  if (/^https?:\/\//i.test(href)) return false
  const ext = href.match(/\.[a-zA-Z0-9]+$/)?.[0]?.toLowerCase()
  return ext ? FILE_EXTENSIONS.has(ext) : false
}

interface Props {
  content: string
  onFileClick?: (path: string) => void
}

export default function MarkdownContent({ content, onFileClick }: Props) {
  return (
    <ReactMarkdown
      children={content}
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const isBlock = className?.startsWith('language-')
          if (isBlock) {
            return (
              <pre style={{
                background: '#1e1e2e',
                color: '#cdd6f4',
                borderRadius: 8,
                padding: '14px 18px',
                margin: '8px 0',
                overflowX: 'auto',
                fontSize: 13,
                lineHeight: 1.5,
              }}>
                <code className={className} {...props}>{children}</code>
              </pre>
            )
          }
          // Inline code that looks like a file path
          const text = String(children).trim()
          if (onFileClick && isFilePath(text)) {
            return (
              <code onClick={() => onFileClick(text)} style={{
                background: '#f0f0f3',
                borderRadius: 4,
                padding: '1px 6px',
                fontSize: '0.88em',
                fontFamily: "'SFMono-Regular', Consolas, monospace",
                color: '#1677ff',
                cursor: 'pointer',
              }} {...props}>
                {children}
              </code>
            )
          }
          return (
            <code style={{
              background: '#f0f0f3',
              borderRadius: 4,
              padding: '1px 6px',
              fontSize: '0.88em',
              fontFamily: "'SFMono-Regular', Consolas, monospace",
            }} {...props}>
              {children}
            </code>
          )
        },
        a({ href, children }) {
          if (href && onFileClick && isFilePath(href)) {
            return (
              <span onClick={() => onFileClick(href)} style={{ color: '#1677ff', cursor: 'pointer', textDecoration: 'underline' }}>
                {children}
              </span>
            )
          }
          return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
        },
        table({ children }) {
          return (
            <div style={{ overflowX: 'auto', margin: '8px 0' }}>
              <table style={{
                borderCollapse: 'collapse',
                fontSize: 13,
                width: '100%',
              }}>
                {children}
              </table>
            </div>
          )
        },
        th({ children }) {
          return (
            <th style={{
              border: '1px solid #e0e0e0',
              padding: '6px 12px',
              background: '#fafafa',
              fontWeight: 600,
              textAlign: 'left',
            }}>
              {children}
            </th>
          )
        },
        td({ children }) {
          return (
            <td style={{
              border: '1px solid #e0e0e0',
              padding: '6px 12px',
            }}>
              {children}
            </td>
          )
        },
      }}
    />
  )
}
