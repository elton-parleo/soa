// @vitest-environment node
//
// esbuild (which Vite's build() uses internally) can't run inside a
// jsdom test environment — jsdom's globals break one of esbuild's
// startup invariants. This file only runs a Node-side build and reads
// the output, so the real DOM never needs to exist here.
/**
 * parleo.io/audit migration: the SECOND Vercel project's build.
 *
 * A sibling to staticHead.build.test.js — which keeps asserting the
 * existing project's default build, unchanged — because the two need
 * different process env, and a Vite build reads that once. Here the
 * three vars that project will actually be configured with are set
 * before the build: VITE_BASE_PATH=/audit/, VITE_AUDIT_BUILD=1, and
 * VITE_PUBLIC_AUDIT_BASE_URL=https://parleo.io/audit.
 *
 * What has to hold, and is easy to get wrong: every absolute URL the
 * documents emit is rooted at parleo.io/audit (not the old host), and
 * every local asset reference resolves under /audit/ — including the
 * favicons and manifest, which are plain root-absolute hrefs in the
 * HTML sources and are rewritten by Vite's `base` rather than by hand.
 * The tracker placement rules (S3/Part 1) are asserted again here,
 * because they are a property of each document and must not quietly
 * change under a different base.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { build } from 'vite'

import { LANDING_META_TITLE, REPORT_META_TITLE, OG_IMAGE_PATH } from '../lite/landingMeta.js'
import { OPENAI_PIXEL_ID } from '../lite/openaiPixel.constants.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(__dirname, '../..')

const BASE_PATH = '/audit/'
const AUDIT_BASE_URL = 'https://parleo.io/audit'

const BUILD_ENV = {
  VITE_BASE_PATH: BASE_PATH,
  VITE_AUDIT_BUILD: '1',
  VITE_PUBLIC_AUDIT_BASE_URL: AUDIT_BASE_URL,
}

let outDir
let auditHtml
let auditReportHtml
const previousEnv = {}

beforeAll(async () => {
  for (const [key, value] of Object.entries(BUILD_ENV)) {
    previousEnv[key] = process.env[key]
    process.env[key] = value
  }
  outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'audit-base-build-'))
  await build({
    root: WEB_ROOT,
    configFile: path.join(WEB_ROOT, 'vite.config.js'),
    logLevel: 'silent',
    build: { outDir, write: true, emptyOutDir: true, sourcemap: false },
  })
  auditHtml = fs.readFileSync(path.join(outDir, 'audit.html'), 'utf8')
  auditReportHtml = fs.readFileSync(path.join(outDir, 'audit-report.html'), 'utf8')
}, 60_000)

afterAll(() => {
  for (const [key, value] of Object.entries(previousEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  if (outDir) fs.rmSync(outDir, { recursive: true, force: true })
})

describe('prefixed build — audit.html absolute URLs point at parleo.io/audit', () => {
  it('canonical and og:url are the /audit/ landing', () => {
    expect(auditHtml).toContain(`<link rel="canonical" href="${AUDIT_BASE_URL}/" />`)
    expect(auditHtml).toContain(`<meta property="og:url" content="${AUDIT_BASE_URL}/" />`)
    expect(auditHtml).toContain(`<title>${LANDING_META_TITLE}</title>`)
  })

  it('og:image is composed from the same base, not the old audit host', () => {
    expect(auditHtml).toContain(`<meta property="og:image" content="${AUDIT_BASE_URL}${OG_IMAGE_PATH}" />`)
    expect(auditHtml).toContain(`<meta name="twitter:image" content="${AUDIT_BASE_URL}${OG_IMAGE_PATH}" />`)
    expect(auditHtml).toContain('<meta name="twitter:card" content="summary_large_image" />')
    // No EMITTED url may still point at the old host. Scoped to
    // attribute values on purpose: audit.html's lemlist comment names
    // audit.parleo.io while explaining that host's routing, which is
    // still in force — this prompt adds the prefix, it does not cut
    // anything over.
    const emitted = [...auditHtml.matchAll(/(?:href|content|src)="([^"]*)"/g)].map((m) => m[1])
    expect(emitted.length).toBeGreaterThan(0)
    for (const value of emitted) {
      expect(value).not.toContain('audit.parleo.io')
    }
  })

  it('the og:image URL resolves to a real PNG in the build output', () => {
    const builtFile = path.join(outDir, OG_IMAGE_PATH)
    expect(fs.existsSync(builtFile)).toBe(true)
    const header = fs.readFileSync(builtFile).subarray(0, 8)
    expect(header.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe(true)
  })
})

// The whole point of the base option: these are plain root-absolute
// hrefs in audit.html/audit-report.html, and Vite rewrites them. If
// that ever stops being true they have to become %BASE_URL%-prefixed
// in the HTML sources instead — this is the assertion that would say so.
describe('prefixed build — every local asset reference resolves under /audit/', () => {
  const LOCAL_REF = /(?:src|href)="(\/[^"]*)"/g

  function localRefs(html) {
    return [...html.matchAll(LOCAL_REF)].map((m) => m[1])
  }

  it.each([
    ['audit.html', () => auditHtml],
    ['audit-report.html', () => auditReportHtml],
  ])('%s: script, stylesheet, icon and manifest refs all carry the prefix', (_name, getHtml) => {
    const refs = localRefs(getHtml())
    expect(refs.length).toBeGreaterThan(0)
    for (const ref of refs) {
      expect(ref.startsWith(BASE_PATH)).toBe(true)
    }
    // Spot-check the ones that matter most, by name.
    expect(refs).toEqual(expect.arrayContaining([
      '/audit/favicon.svg',
      '/audit/favicon-32.png',
      '/audit/favicon-16.png',
      '/audit/apple-touch-icon.png',
      '/audit/site.webmanifest',
    ]))
    expect(refs.some((r) => /^\/audit\/assets\/.*\.js$/.test(r))).toBe(true)
    expect(refs.some((r) => /^\/audit\/assets\/.*\.css$/.test(r))).toBe(true)
  })
})

describe('prefixed build — tracker placement is unchanged (S3, Part 1)', () => {
  it('the OpenAI pixel is on both audit documents, exactly once', () => {
    for (const html of [auditHtml, auditReportHtml]) {
      expect(html.split(OPENAI_PIXEL_ID).length - 1).toBe(1)
      expect(html).toContain('https://bzrcdn.openai.com/sdk/oaiq.min.js')
    }
  })

  it('lemlist is on the landing and nowhere near /r/ or /s/', () => {
    expect(auditHtml).toMatch(/<script async src="https:\/\/app\.lemlist\.com\/api\/visitors\/tracking\?[^"]*"><\/script>/)
    expect(auditReportHtml).not.toMatch(/lemlist/i)
  })

  it('audit-report.html keeps its neutral, noindex head', () => {
    expect(auditReportHtml).toContain(`<title>${REPORT_META_TITLE}</title>`)
    expect(auditReportHtml).toContain('<meta name="robots" content="noindex,nofollow" />')
    expect(auditReportHtml).not.toMatch(/rel="canonical"|property="og:|name="twitter:/)
  })
})
