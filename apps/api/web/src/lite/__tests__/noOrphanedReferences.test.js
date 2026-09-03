/**
 * Grep guards from two sessions, merged back together after their
 * PRs split apart and re-converged:
 * - Part 1c (lemlist): the landing-only guarantee holds at the raw
 *   HTML source level too, not just in the real Vite build output
 *   (staticHead.build.test.js) — a fast, no-build check.
 * - Part 2d (Formspree retarget): no `oaiq` (the OpenAI-pixel global)
 *   anywhere — it gates on a pixel that was never installed, and this
 *   session deliberately omits it rather than transplanting the
 *   vanilla-DOM snippet's call to it. The old backend is also gone
 *   from the frontend's own references: no /api/public/demo-request
 *   fetch call or docstring mention survives the retarget to
 *   Formspree (demoRequestApi.js, publicUrls.js's
 *   FORMSPREE_DEMO_ENDPOINT).
 * - the anti-spam gate fix: RequestFormModal.jsx's own submit path
 *   must never be gateable by environment (no import.meta.env/VITE_
 *   reference), so a submission can never be silently disabled in any
 *   mode.
 * - own-account Formspree form + dropped visited-page-URL field: no
 *   reference to the old shared form id anywhere, and the removed
 *   payload field (a spam-classifier signal, confirmed via dashboard
 *   access) doesn't survive in the functional modal/payload modules.
 *
 * The oaiq/demo-request walk() helper walks the whole src/ tree like
 * analytics.test.js's posthog-import-boundary test, excluding test
 * files/__tests__ dirs so this file's own assertions (which
 * necessarily contain the banned strings) don't trip themselves.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function walk(dir, offenders, pattern) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === '__tests__') continue
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      walk(full, offenders, pattern)
    } else if (/\.(js|jsx|html)$/.test(entry.name) && !/\.test\.(js|jsx)$/.test(entry.name)) {
      const src = fs.readFileSync(full, 'utf8')
      if (pattern.test(src)) offenders.push(full)
    }
  }
}

describe('Part 1c: source-level lemlist grep (fast, no build required)', () => {
  const WEB_ROOT = path.join(__dirname, '../../..')

  it('audit-report.html (/r/, /s/) source has no lemlist reference', () => {
    const src = fs.readFileSync(path.join(WEB_ROOT, 'audit-report.html'), 'utf8')
    expect(src).not.toMatch(/lemlist/i)
  })

  it('index.html source has no lemlist reference', () => {
    const src = fs.readFileSync(path.join(WEB_ROOT, 'index.html'), 'utf8')
    expect(src).not.toMatch(/lemlist/i)
  })

  it('audit.html source has it', () => {
    const src = fs.readFileSync(path.join(WEB_ROOT, 'audit.html'), 'utf8')
    expect(src).toMatch(/lemlist/i)
  })
})

// Anti-spam gate bug fix: the gate itself (RequestFormModal.jsx's
// handleSubmit — the honeypot/timing checks and the onSubmit call they
// guard) must never be gateable by environment, so a submission can
// never be silently disabled in any mode. The dev-only console warning
// (Part 2c) is deliberately NOT here — it lives in its own file,
// ds/devWarn.js, exactly so this file can stay completely free of any
// import.meta.env/VITE_ reference.
describe('the anti-spam gate / submit path has no environment reference', () => {
  it('RequestFormModal.jsx contains no import.meta.env or VITE_ reference', () => {
    const src = fs.readFileSync(path.join(__dirname, '../../ds/RequestFormModal.jsx'), 'utf8')
    expect(src).not.toMatch(/import\.meta\.env|VITE_/)
  })
})

describe('no orphaned references left behind by the Formspree retarget', () => {
  it('no file references oaiq (the un-installed OpenAI pixel)', () => {
    const srcRoot = path.join(__dirname, '../..')
    const offenders = []
    walk(srcRoot, offenders, /oaiq/i)
    expect(offenders).toEqual([])
  })

  it('no file still references /api/public/demo-request (superseded by Formspree)', () => {
    const srcRoot = path.join(__dirname, '../..')
    const offenders = []
    walk(srcRoot, offenders, /\/api\/public\/demo-request/)
    expect(offenders).toEqual([])
  })
})

// Moved off the marketing site's shared Formspree form onto our own
// account's — the old form id must not survive anywhere.
describe('no reference to the old shared Formspree form id', () => {
  it('no file references the old form id', () => {
    const srcRoot = path.join(__dirname, '../..')
    const offenders = []
    walk(srcRoot, offenders, /xyklyajq/)
    expect(offenders).toEqual([])
  })
})

// The submission payload's only URL field was a primary spam-classifier
// signal (confirmed by dashboard access — submissions were landing in
// Formspree's spam tab) and redundant besides (report_token + brand_name
// already reconstruct the report link). Scoped to the functional modal/
// payload modules, not the test files — the payload test itself is
// expected to reference the field by name in its own absence assertion.
describe('the visited-page-URL field never made it back into the modal/payload modules', () => {
  const MODULES = [
    '../../ds/RequestFormModal.jsx',
    '../demoRequestApi.js',
    '../useDemoRequestModal.js',
    '../demoRequestCtas.js',
  ].map((p) => path.join(__dirname, p))

  it.each(MODULES)('%s has no page_url reference', (file) => {
    const src = fs.readFileSync(file, 'utf8')
    expect(src).not.toMatch(/page_url/)
  })
})
