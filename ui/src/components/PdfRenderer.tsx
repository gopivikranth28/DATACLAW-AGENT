import { useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import 'react-pdf/dist/Page/TextLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface PdfRendererProps {
  url: string
  maxPages?: number
}

export default function PdfRenderer({ url, maxPages }: PdfRendererProps) {
  const [numPages, setNumPages] = useState(0)

  const pagesToShow = maxPages ? Math.min(numPages, maxPages) : numPages

  return (
    <div>
      <Document
        file={url}
        onLoadSuccess={({ numPages: n }) => setNumPages(n)}
        loading={<div style={{ textAlign: 'center', padding: 32, color: '#999' }}>Loading PDF...</div>}
        error={<div style={{ textAlign: 'center', padding: 32, color: '#ff4d4f' }}>Failed to load PDF</div>}
      >
        {Array.from({ length: pagesToShow }, (_, i) => (
          <Page
            key={i}
            pageNumber={i + 1}
            width={600}
            renderAnnotationLayer={false}
          />
        ))}
      </Document>
      {maxPages && numPages > maxPages && (
        <div style={{ textAlign: 'center', padding: 8, color: '#888', fontSize: 11 }}>
          Showing {maxPages} of {numPages} pages
        </div>
      )}
    </div>
  )
}
