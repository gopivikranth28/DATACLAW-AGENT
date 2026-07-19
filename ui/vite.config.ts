import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget = process.env.DATACLAW_API_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  build: {
    modulePreload: {
      resolveDependencies: (_filename, _deps, context) => context.hostType === 'html' ? [] : _deps,
    },
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('plotly.js-dist-min')) return 'vendor-plotly'
          if (id.includes('react-pdf') || id.includes('pdfjs-dist')) return 'vendor-pdf'
          if (id.includes('react-ipynb-renderer')) return 'vendor-notebook'
          if (id.includes('@tiptap')) return 'vendor-editor'
          if (id.includes('antd') || id.includes('@ant-design')) return 'vendor-antd'
          if (id.includes('@xterm')) return 'vendor-terminal'
          if (id.includes('react') || id.includes('react-dom') || id.includes('react-router-dom')) return 'vendor-react'
          return 'vendor'
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        ws: true,
      },
    },
  },
})
