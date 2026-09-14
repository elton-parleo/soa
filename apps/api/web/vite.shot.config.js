import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Alias by RESOLVED path, not by import specifier: the component imports
// '../api.js' relative to itself, which vite's `resolve.alias` never sees.
const STUBS = {
  [resolve(__dirname, 'src/api.js')]: resolve(__dirname, 'screenshot-harness/stub-api.js'),
  [resolve(__dirname, 'src/truesyncApi.js')]: resolve(__dirname, 'screenshot-harness/stub-truesync.js'),
}

function stubPlugin() {
  return {
    name: 'screenshot-stubs',
    enforce: 'pre',
    async resolveId(source, importer, options) {
      const resolved = await this.resolve(source, importer, { ...options, skipSelf: true })
      if (resolved && STUBS[resolved.id]) return STUBS[resolved.id]
      return null
    },
  }
}

export default defineConfig({
  root: resolve(__dirname, 'screenshot-harness'),
  plugins: [stubPlugin(), react()],
  server: { port: 5199, fs: { allow: [resolve(__dirname, '../../..')] } },
})
