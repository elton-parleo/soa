// @vitest-environment node
//
// Node-side for the same reason as screenshotHarness.build.test.js: Vite's
// build() runs esbuild, which cannot run inside jsdom.
/**
 * The TrueSync tenant token never reaches the browser bundle.
 *
 * The token is a server-side secret: the proxy (app/routers/truesync.py)
 * attaches it, and every scoped read and write goes through that proxy so
 * the page never needs it. This builds the real production bundle with a
 * recognisable fake token present under every name it could plausibly be
 * exposed by — including VITE_-prefixed ones, which Vite WOULD inline if
 * anything referenced them — and asserts none of it comes out the other
 * side, and that the bundle never names the credential header at all.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { build } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(__dirname, '../..')

const FAKE_TOKEN = 'tst_feedfacecafebeef_BUNDLE-CANARY-do-not-ship-0123456789abcdef'
const TOKEN_NAMES = [
  'TRUESYNC_TENANT_TOKEN',
  'TRUESYNC_ADMIN_KEY',
  'VITE_TRUESYNC_TENANT_TOKEN',
  'VITE_TRUESYNC_ADMIN_KEY',
]

let outDir
let bundledSource
const saved = {}

beforeAll(async () => {
  for (const name of TOKEN_NAMES) {
    saved[name] = process.env[name]
    process.env[name] = FAKE_TOKEN
  }
  outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'soa-token-build-'))
  await build({ root: WEB_ROOT, logLevel: 'silent', build: { outDir, emptyOutDir: true } })

  const files = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else files.push(full)
    }
  }
  walk(outDir)
  bundledSource = files
    .filter((f) => /\.(js|css|html|map|json)$/.test(f))
    .map((f) => fs.readFileSync(f, 'utf8'))
    .join('\n')
}, 240_000)

afterAll(() => {
  for (const name of TOKEN_NAMES) {
    if (saved[name] === undefined) delete process.env[name]
    else process.env[name] = saved[name]
  }
  if (outDir) fs.rmSync(outDir, { recursive: true, force: true })
})

describe('the production bundle', () => {
  it('was actually built (the guard is not guarding an empty string)', () => {
    expect(bundledSource.length).toBeGreaterThan(10_000)
    // The scoped reads are in there — as same-origin paths.
    expect(bundledSource).toContain('/api/truesync/merchants')
  })

  it('does not contain the token, whatever name it was exported under', () => {
    expect(bundledSource).not.toContain(FAKE_TOKEN)
    expect(bundledSource).not.toContain('BUNDLE-CANARY')
  })

  it('never names the TrueSync credential header or the token variables', () => {
    // If the page ever set X-TrueSync-Key itself, it would have to hold a
    // token to put in it.
    expect(bundledSource.toLowerCase()).not.toContain('x-truesync-key')
    for (const name of TOKEN_NAMES) expect(bundledSource).not.toContain(name)
  })
})
