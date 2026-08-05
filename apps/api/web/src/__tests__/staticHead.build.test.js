// @vitest-environment node
//
// esbuild (which Vite's build() uses internally) can't run inside a
// jsdom test environment — jsdom's globals break one of esbuild's
// startup invariants. This file only reads files and runs a Node-side
// build, so the real DOM never needs to exist here.
/**
 * S1: the audit host's landing/report documents must have their head
 * tags already present in the SERVED HTML, not just assembled by a
 * client effect after hydration. A source-level check can't prove
 * that — it has to run a real production build and read the actual
 * output, which is what this file does (once, in beforeAll, since a
 * full Vite build takes real wall-clock time).
 *
 * S1's other requirement — one metadata source shared with
 * useLandingMeta — is asserted by comparing the built output's tag
 * content against landingMeta.js's exported constants directly: if
 * someone edits the client copy without touching vite.config.js's
 * plugin (or vice versa), these assertions catch the drift rather
 * than two hand-written literals silently disagreeing.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { build } from 'vite'

import {
  LANDING_META_TITLE, LANDING_META_DESCRIPTION, REPORT_META_TITLE, OG_IMAGE_URL,
} from '../lite/landingMeta.js'
import { PUBLIC_AUDIT_BASE_URL } from '../lite/publicUrls.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(__dirname, '../..')

let outDir
let auditHtml
let auditReportHtml
let indexHtml

beforeAll(async () => {
  outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'audit-head-build-'))
  await build({
    root: WEB_ROOT,
    configFile: path.join(WEB_ROOT, 'vite.config.js'),
    logLevel: 'silent',
    build: { outDir, write: true, emptyOutDir: true, sourcemap: false },
  })
  auditHtml = fs.readFileSync(path.join(outDir, 'audit.html'), 'utf8')
  auditReportHtml = fs.readFileSync(path.join(outDir, 'audit-report.html'), 'utf8')
  indexHtml = fs.readFileSync(path.join(outDir, 'index.html'), 'utf8')
}, 60_000)

afterAll(() => {
  if (outDir) fs.rmSync(outDir, { recursive: true, force: true })
})

describe('built audit.html (landing) — S1', () => {
  it('has the title, canonical, and OG/Twitter tags baked in', () => {
    expect(auditHtml).toContain(`<title>${LANDING_META_TITLE}</title>`)
    expect(auditHtml).toContain(`<link rel="canonical" href="${PUBLIC_AUDIT_BASE_URL}/" />`)
    expect(auditHtml).toContain(`content="${LANDING_META_DESCRIPTION}"`)
    expect(auditHtml).toMatch(/<meta property="og:title" content="[^"]*" \/>/)
    expect(auditHtml).toContain(`<meta property="og:url" content="${PUBLIC_AUDIT_BASE_URL}/" />`)
    expect(auditHtml).toContain('<meta property="og:type" content="website" />')
    expect(auditHtml).toContain('<meta name="twitter:card" content="summary" />')
  })

  it('metadata-source equality: built title/description exactly match landingMeta.js', () => {
    const titleMatch = auditHtml.match(/<title>([^<]*)<\/title>/)
    expect(titleMatch[1]).toBe(LANDING_META_TITLE)

    const descMatch = auditHtml.match(/<meta name="description" content="([^"]*)"/)
    expect(descMatch[1]).toBe(LANDING_META_DESCRIPTION)
  })

  it('S4: omits og:image/twitter:image while OG_IMAGE_URL is null, never a fabricated path', () => {
    expect(OG_IMAGE_URL).toBeNull()
    expect(auditHtml).not.toMatch(/og:image|twitter:image/)
  })

  it('placeholder is fully consumed — no leftover marker in the built output', () => {
    expect(auditHtml).not.toContain('<!--AUDIT_HEAD-->')
  })
})

describe('built audit-report.html (/r/, /s/) — S3', () => {
  it('has a neutral title and noindex, and nothing from the landing head', () => {
    expect(auditReportHtml).toContain(`<title>${REPORT_META_TITLE}</title>`)
    expect(auditReportHtml).toContain('<meta name="robots" content="noindex" />')
    expect(auditReportHtml).not.toContain(LANDING_META_TITLE)
    expect(auditReportHtml).not.toMatch(/rel="canonical"|property="og:|name="twitter:/)
  })

  it('placeholder is fully consumed', () => {
    expect(auditReportHtml).not.toContain('<!--AUDIT_HEAD-->')
  })
})

describe('built index.html (main host) — unaffected', () => {
  it('keeps its generic title, no audit-specific tags', () => {
    expect(indexHtml).toContain('<title>SoA Platform</title>')
    expect(indexHtml).not.toContain(LANDING_META_TITLE)
    expect(indexHtml).not.toMatch(/rel="canonical"|property="og:/)
  })
})
