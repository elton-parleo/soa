/**
 * I1: the audit surface's robots.txt disallows /r/ and /s/ and allows
 * the landing; its sitemap contains only the landing. Served by
 * vercel.json's prefixed route at /audit/robots.txt and
 * /audit/sitemap.xml (see vercelRouting.test.js).
 *
 * Cutover caveat, asserted below: crawlers only read robots.txt at the
 * origin root, so the file that actually governs the audit surface now
 * is the MARKETING repo's /robots.txt. This copy is the source of
 * those rules; the test pins the note that says so, because a future
 * edit that quietly drops it would leave the rules looking effective
 * when they are not.
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

  it('points at the audit sitemap on the canonical address', () => {
    expect(robots).toContain('Sitemap: https://parleo.io/audit/sitemap.xml')
    expect(robots).not.toContain('audit.parleo.io')
  })

  it('says where the rules actually have to live, with the exact lines', () => {
    expect(robots).toMatch(/origin root/i)
    expect(robots).toContain('Disallow: /audit/r/')
    expect(robots).toContain('Disallow: /audit/s/')
  })

  // Part 2c: the favicon set must stay crawlable/fetchable on the
  // audit host — none of its paths fall under /r/ or /s/, but assert
  // it directly rather than relying on that being a coincidence.
  it('does not disallow the favicon set', () => {
    for (const p of ['/favicon.svg', '/favicon-32.png', '/favicon-16.png', '/apple-touch-icon.png', '/site.webmanifest']) {
      expect(robots).not.toMatch(new RegExp(`Disallow:\\s*${p.replace('.', '\\.')}`))
    }
  })
})

describe('public/audit-sitemap.xml', () => {
  const sitemap = fs.readFileSync(path.join(PUBLIC_DIR, 'audit-sitemap.xml'), 'utf8')

  it('contains only the landing page, at the canonical address', () => {
    const locs = [...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map((m) => m[1])
    expect(locs).toEqual(['https://parleo.io/audit/'])
  })

  it('lists no URL on the retired host', () => {
    expect(sitemap).not.toContain('audit.parleo.io')
  })
})

// L3: the main host (soa-app.parleo.io) gets its own robots.txt —
// /report/ and /s/ are duplicates of audit-surface content
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

  it('does not disallow the favicon set', () => {
    for (const p of ['/favicon.svg', '/favicon-32.png', '/favicon-16.png', '/apple-touch-icon.png', '/site.webmanifest']) {
      expect(robots).not.toMatch(new RegExp(`Disallow:\\s*${p.replace('.', '\\.')}`))
    }
  })
})
