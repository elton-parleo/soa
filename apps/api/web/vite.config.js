import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PUBLIC_AUDIT_BASE_URL } from './src/lite/audit-host.constants.js'
import {
  LANDING_META_TITLE, LANDING_META_DESCRIPTION, REPORT_META_TITLE, OG_IMAGE_URL,
} from './src/lite/landingMeta.js'

const __dirname = dirname(fileURLToPath(import.meta.url))

function escapeAttr(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function meta(attr, key, content) {
  return `<meta ${attr}="${escapeAttr(key)}" content="${escapeAttr(content)}" />`
}

// S1: builds the exact <head> block for audit.html/audit-report.html
// from landingMeta.js — the only place either the landing or the
// report/status head content is assembled, so the static output and
// LandingPage.jsx's useLandingMeta (which sources the same constants)
// can never drift into disagreement.
function auditHeadPlugin(auditBaseUrl) {
  const landingUrl = `${auditBaseUrl}/`
  const landingTags = [
    `<title>${escapeAttr(LANDING_META_TITLE)}</title>`,
    `<link rel="canonical" href="${escapeAttr(landingUrl)}" />`,
    meta('name', 'description', LANDING_META_DESCRIPTION),
    meta('property', 'og:title', LANDING_META_TITLE),
    meta('property', 'og:description', LANDING_META_DESCRIPTION),
    meta('property', 'og:url', landingUrl),
    meta('property', 'og:type', 'website'),
    meta('name', 'twitter:card', 'summary'),
    meta('name', 'twitter:title', LANDING_META_TITLE),
    meta('name', 'twitter:description', LANDING_META_DESCRIPTION),
    // S4: OG_IMAGE_URL is null until a real share-image asset exists —
    // omit the tags entirely rather than emit a path that 404s on
    // every unfurl. Flip this on by giving OG_IMAGE_URL a real value.
    ...(OG_IMAGE_URL
      ? [meta('property', 'og:image', OG_IMAGE_URL), meta('name', 'twitter:image', OG_IMAGE_URL)]
      : []),
  ].join('\n    ')

  // S3: /r/{token} and /s/{id} never inherit the landing's OG identity
  // — a shared report link must not unfurl like brand marketing.
  const reportTags = [
    `<title>${escapeAttr(REPORT_META_TITLE)}</title>`,
    meta('name', 'robots', 'noindex'),
  ].join('\n    ')

  return {
    name: 'audit-head',
    transformIndexHtml(html, ctx) {
      const filename = ctx.filename || ''
      if (filename.endsWith('audit-report.html')) {
        return html.replace('<!--AUDIT_HEAD-->', reportTags)
      }
      if (filename.endsWith('audit.html')) {
        return html.replace('<!--AUDIT_HEAD-->', landingTags)
      }
      return html
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const auditBaseUrl = (env.VITE_PUBLIC_AUDIT_BASE_URL || DEFAULT_PUBLIC_AUDIT_BASE_URL).replace(/\/$/, '')

  return {
    plugins: [react(), auditHeadPlugin(auditBaseUrl)],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          // Explicitly preserve Authorization header through the proxy.
          // Without this, some proxy configurations strip auth headers.
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq, req) => {
              const auth = req.headers['authorization']
              if (auth) {
                proxyReq.setHeader('Authorization', auth)
              }
            })
          },
        }
      }
    },
    build: {
      outDir:    'dist',
      sourcemap: false,
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'index.html'),
          audit: resolve(__dirname, 'audit.html'),
          'audit-report': resolve(__dirname, 'audit-report.html'),
        },
      },
    },
  }
})
