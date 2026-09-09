// @vitest-environment node
//
// Same reason as staticHead.build.test.js: esbuild (which Vite's build()
// uses internally) can't run inside a jsdom environment. This file runs
// Node-side builds and reads their output, so the real DOM is never
// needed here.
/**
 * The screenshot harness (screenshot-harness/) is dev-only, and this file
 * is what makes "dev-only" a fact rather than an intention.
 *
 * The harness renders CreateStudyModal on its own against STUBBED api.js
 * and truesyncApi.js modules. Those stubs return canned constraints and a
 * fixture catalog; a bundle carrying them would be an app whose API
 * client silently answers from a fixture. That is the failure this
 * guards against, and it is the kind that ships quietly.
 *
 * Two assertions, and only the second one proves anything:
 *
 *   1. a real production build produces no harness code — necessary, but
 *      it would also pass if the harness simply happened to be
 *      unreferenced, which is today's state and not a guarantee;
 *
 *   2. a build that DOES reach for the harness FAILS — which is the
 *      guarantee. Without this, the guard could be deleted from
 *      vite.config.js and assertion 1 would keep passing.
 *
 * The mechanism under test is the forbid-screenshot-harness rollup plugin
 * in vite.config.js, which throws on resolving any module under
 * screenshot-harness/. It is deliberately absent from vitest.config.js:
 * the test suite renders components in isolation and has no business
 * being told what it may import; the production bundle does.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { build } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const WEB_ROOT = path.resolve(__dirname, '../..')
const HARNESS_DIR = path.join(WEB_ROOT, 'screenshot-harness')

// Strings that appear in the harness stubs and nowhere in the real app.
// Grepping the built bundle for these is the crude check that backs the
// structural one.
const HARNESS_FINGERPRINTS = [
  'screenshot-harness',
  'stub-truesync',
  'stub-api',
]

let outDir
let bundledSource

beforeAll(async () => {
  outDir = fs.mkdtempSync(path.join(os.tmpdir(), 'soa-harness-build-'))
  await build({
    root: WEB_ROOT,
    logLevel: 'silent',
    build: { outDir, emptyOutDir: true },
  })

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
    .filter((f) => /\.(js|css|html)$/.test(f))
    .map((f) => fs.readFileSync(f, 'utf8'))
    .join('\n')
}, 240_000)

afterAll(() => {
  if (outDir) fs.rmSync(outDir, { recursive: true, force: true })
})

describe('the screenshot harness exists and is dev-only', () => {
  it('is present in the repo — this guard is not guarding nothing', () => {
    expect(fs.existsSync(path.join(HARNESS_DIR, 'stub-api.js'))).toBe(true)
    expect(fs.existsSync(path.join(HARNESS_DIR, 'stub-truesync.js'))).toBe(true)
    expect(fs.existsSync(path.join(WEB_ROOT, 'vite.shot.config.js'))).toBe(true)
  })

  it('has its own dev-only npm script, separate from build', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.join(WEB_ROOT, 'package.json'), 'utf8'),
    )
    expect(pkg.scripts.shot).toContain('vite.shot.config.js')
    expect(pkg.scripts.build).toBe('vite build')
    expect(pkg.scripts.build).not.toContain('shot')
  })

  it('stubs the real API clients — which is why it must not ship', () => {
    const stub = fs.readFileSync(path.join(HARNESS_DIR, 'stub-api.js'), 'utf8')
    expect(stub).toContain('export const api')
    expect(stub).toContain('getQueryConstraints')
  })
})

describe('a production build', () => {
  it('carries no harness code', () => {
    for (const fingerprint of HARNESS_FINGERPRINTS) {
      expect(bundledSource).not.toContain(fingerprint)
    }
  })

  it('carries the real API client, not the stub', () => {
    // The stub's canned merchant list would be the tell. The real client
    // reads TrueSync over HTTP.
    expect(bundledSource).toContain('/api/truesync/merchants')
    expect(bundledSource).not.toContain('wiggle-and-snug')
  })

  it('emits only the three real entry documents', () => {
    const html = fs.readdirSync(outDir).filter((f) => f.endsWith('.html'))
    expect(html.sort()).toEqual(['audit-report.html', 'audit.html', 'index.html'])
  })
})

describe('the guard is live, not decorative', () => {
  it('fails the build when anything reaches into the harness', async () => {
    // The assertion that actually holds. Without it, someone could delete
    // forbid-screenshot-harness from vite.config.js and every other test
    // in this file would keep passing.
    const entry = path.join(WEB_ROOT, 'src', '__harness_guard_probe__.js')
    const probeOut = fs.mkdtempSync(path.join(os.tmpdir(), 'soa-harness-probe-'))
    fs.writeFileSync(
      entry,
      "export { api } from '../screenshot-harness/stub-api.js'\n",
    )

    try {
      await expect(build({
        root: WEB_ROOT,
        logLevel: 'silent',
        build: {
          outDir: probeOut,
          emptyOutDir: true,
          rollupOptions: { input: { probe: entry } },
        },
      })).rejects.toThrow(/screenshot harness/i)
    } finally {
      fs.rmSync(entry, { force: true })
      fs.rmSync(probeOut, { recursive: true, force: true })
    }
  }, 240_000)

  it('names the harness and says how to run it instead', async () => {
    const entry = path.join(WEB_ROOT, 'src', '__harness_guard_message__.js')
    const probeOut = fs.mkdtempSync(path.join(os.tmpdir(), 'soa-harness-msg-'))
    fs.writeFileSync(
      entry,
      "export { truesyncApi } from '../screenshot-harness/stub-truesync.js'\n",
    )

    try {
      await expect(build({
        root: WEB_ROOT,
        logLevel: 'silent',
        build: {
          outDir: probeOut,
          emptyOutDir: true,
          rollupOptions: { input: { probe: entry } },
        },
      })).rejects.toThrow(/npm run shot/)
    } finally {
      fs.rmSync(entry, { force: true })
      fs.rmSync(probeOut, { recursive: true, force: true })
    }
  }, 240_000)
})
