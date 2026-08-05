/**
 * I1: audit.parleo.io's robots.txt disallows /r/ and /s/, allows the
 * landing page; its sitemap contains only the landing page. Served via
 * a host-conditional vercel.json rewrite (see vercelRouting.test.js) to
 * these literal files.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PUBLIC_DIR = path.join(__dirname, '../../public')

describe('public/audit-robots.txt', () => {
  const robots = fs.readFileSync(path.join(PUBLIC_DIR, 'audit-robots.txt'), 'utf8')

  it('disallows /r/ and /s/', () => {
    expect(robots).toMatch(/Disallow:\s*\/r\//)
    expect(robots).toMatch(/Disallow:\s*\/s\//)
  })

  it('does not disallow the landing page', () => {
    expect(robots).not.toMatch(/Disallow:\s*\/\s*$/m)
  })

  it('points at the audit host sitemap', () => {
    expect(robots).toContain('Sitemap: https://audit.parleo.io/sitemap.xml')
  })
})

describe('public/audit-sitemap.xml', () => {
  const sitemap = fs.readFileSync(path.join(PUBLIC_DIR, 'audit-sitemap.xml'), 'utf8')

  it('contains only the landing page', () => {
    const locs = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map((m) => m[1])
    expect(locs).toEqual(['https://audit.parleo.io/'])
  })
})

// L3: the main host (everything but audit.parleo.io) gets its own
// robots.txt — /report/ and /s/ are duplicates of audit-host content
// and disallowed; /lite is deliberately left crawlable, since L2's
// canonical tag is the correct way to consolidate its ranking onto the
// audit host without sending crawlers a conflicting disallow signal.
describe('public/robots.txt (main host, L3)', () => {
  const robots = fs.readFileSync(path.join(PUBLIC_DIR, 'robots.txt'), 'utf8')

  it('disallows /report/ and /s/', () => {
    expect(robots).toMatch(/Disallow:\s*\/report\//)
    expect(robots).toMatch(/Disallow:\s*\/s\//)
  })

  it('does not disallow /lite', () => {
    expect(robots).not.toMatch(/Disallow:\s*\/lite/)
  })
})
