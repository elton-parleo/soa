/**
 * Source-level grep guard for Part 1 (lemlist): the landing-only
 * guarantee holds at the raw HTML source level too, not just in the
 * real Vite build output (staticHead.build.test.js) — a fast,
 * no-build check that catches a regression even before a full build
 * runs.
 *
 * Split out of a larger file that also carried unrelated grep guards
 * for a separate, not-yet-merged demo-request backend change — those
 * land separately with that work.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

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
