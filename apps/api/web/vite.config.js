import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { DEFAULT_PUBLIC_AUDIT_BASE_URL } from './src/lite/audit-host.constants.js'
import { OPENAI_PIXEL_ID, OPENAI_PIXEL_DEBUG } from './src/lite/openaiPixel.constants.js'
import {
  LANDING_META_TITLE, LANDING_META_DESCRIPTION, REPORT_META_TITLE,
  OG_IMAGE_URL, OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT, OG_IMAGE_ALT,
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

// The OpenAI (ChatGPT Ads) Measurement Pixel loader, built once here
// and written into BOTH audit documents at the <!--OPENAI_PIXEL-->
// marker — same single-source discipline as the meta tags below, so
// the pixel ID exists as a literal in exactly one file
// (openaiPixel.constants.js) rather than being pasted into two HTML
// heads that can then drift.
//
// Inline and synchronous on purpose: the loader has to define the
// oaiq queue before the async SDK arrives, which is the documented
// pattern. Placed above the font stylesheet (marker position in the
// HTML) so init runs early enough to capture ?oppref= off the landing
// URL before any client-side navigation rewrites it.
//
// index.html carries no marker, so this string never reaches the
// marketing host's document. Asserted in staticHead.build.test.js.
const OPENAI_PIXEL_TAG = `<script>
      (function (w, d, s, u) {
        if (w.oaiq) return;
        var q = function () {
          q.q.push(arguments);
        };
        q.q = [];
        w.oaiq = q;
        var js = d.createElement(s);
        js.async = true;
        js.src = u;
        var f = d.getElementsByTagName(s)[0];
        f.parentNode.insertBefore(js, f);
      })(window, document, "script", "https://bzrcdn.openai.com/sdk/oaiq.min.js");

      oaiq("init", {
        pixelId: ${JSON.stringify(OPENAI_PIXEL_ID)},
        debug: ${OPENAI_PIXEL_DEBUG},
      });
    </script>`

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
    meta('name', 'twitter:card', OG_IMAGE_URL ? 'summary_large_image' : 'summary'),
    meta('name', 'twitter:title', LANDING_META_TITLE),
    meta('name', 'twitter:description', LANDING_META_DESCRIPTION),
    // S4: OG_IMAGE_URL is null only if reset — omit the tags entirely
    // rather than emit a path that 404s on every unfurl.
    ...(OG_IMAGE_URL
      ? [
          meta('property', 'og:image', OG_IMAGE_URL),
          meta('property', 'og:image:width', OG_IMAGE_WIDTH),
          meta('property', 'og:image:height', OG_IMAGE_HEIGHT),
          meta('property', 'og:image:alt', OG_IMAGE_ALT),
          meta('name', 'twitter:image', OG_IMAGE_URL),
        ]
      : []),
  ].join('\n    ')

  // S3: /r/{token} and /s/{id} never inherit the landing's OG identity
  // — a shared report link must not unfurl like brand marketing.
  const reportTags = [
    `<title>${escapeAttr(REPORT_META_TITLE)}</title>`,
    meta('name', 'robots', 'noindex,nofollow'),
  ].join('\n    ')

  return {
    name: 'audit-head',
    transformIndexHtml(html, ctx) {
      const filename = ctx.filename || ''
      if (filename.endsWith('audit-report.html')) {
        return html
          .replace('<!--AUDIT_HEAD-->', reportTags)
          .replace('<!--OPENAI_PIXEL-->', OPENAI_PIXEL_TAG)
      }
      if (filename.endsWith('audit.html')) {
        return html
          .replace('<!--AUDIT_HEAD-->', landingTags)
          .replace('<!--OPENAI_PIXEL-->', OPENAI_PIXEL_TAG)
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
