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
  LANDING_META_TITLE, LANDING_META_DESCRIPTION, REPORT_META_TITLE,
  OG_IMAGE_URL, OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT, OG_IMAGE_ALT,
} from '../lite/landingMeta.js'
import { PUBLIC_AUDIT_BASE_URL } from '../lite/publicUrls.js'
import { OPENAI_PIXEL_ID } from '../lite/openaiPixel.constants.js'

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
    expect(auditHtml).toContain('<meta name="twitter:card" content="summary_large_image" />')
  })

  it('metadata-source equality: built title/description exactly match landingMeta.js', () => {
    const titleMatch = auditHtml.match(/<title>([^<]*)<\/title>/)
    expect(titleMatch[1]).toBe(LANDING_META_TITLE)

    const descMatch = auditHtml.match(/<meta name="description" content="([^"]*)"/)
    expect(descMatch[1]).toBe(LANDING_META_DESCRIPTION)
  })

  // Part 3b: og:image + dimensions + alt, and the URL resolves to a
  // real PNG in the build output (Vite copies public/ verbatim, so
  // the absolute OG_IMAGE_URL's path always has a matching file here).
  it('Part 3b: carries og:image + width/height/alt + twitter:image, resolving to a real PNG', () => {
    expect(OG_IMAGE_URL).not.toBeNull()
    expect(auditHtml).toContain(`<meta property="og:image" content="${OG_IMAGE_URL}" />`)
    expect(auditHtml).toContain(`<meta property="og:image:width" content="${OG_IMAGE_WIDTH}" />`)
    expect(auditHtml).toContain(`<meta property="og:image:height" content="${OG_IMAGE_HEIGHT}" />`)
    expect(auditHtml).toContain(`<meta property="og:image:alt" content="${OG_IMAGE_ALT}" />`)
    expect(auditHtml).toContain(`<meta name="twitter:image" content="${OG_IMAGE_URL}" />`)

    const ogImagePath = new URL(OG_IMAGE_URL).pathname // "/og/audit-landing.png"
    const builtFile = path.join(outDir, ogImagePath)
    expect(fs.existsSync(builtFile)).toBe(true)
    const header = fs.readFileSync(builtFile).subarray(0, 8)
    expect(header.equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe(true) // PNG magic bytes
  })

  it('placeholder is fully consumed — no leftover marker in the built output', () => {
    expect(auditHtml).not.toContain('<!--AUDIT_HEAD-->')
  })
})

describe('built audit-report.html (/r/, /s/) — S3', () => {
  it('has a neutral title and noindex,nofollow, and nothing from the landing head', () => {
    expect(auditReportHtml).toContain(`<title>${REPORT_META_TITLE}</title>`)
    expect(auditReportHtml).toContain('<meta name="robots" content="noindex,nofollow" />')
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

// Part 2b/2c: the favicon set is declared identically in all three
// built entries — every host/route shows the same two-bar icon — and
// the actual files exist in the build output (Vite copies public/ to
// the dist root verbatim), so a served page's <link> tags never point
// at a 404.
describe('favicon set — declared in all three built HTML entries', () => {
  const FAVICON_TAGS = [
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />',
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />',
    '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />',
    '<link rel="manifest" href="/site.webmanifest" />',
    '<meta name="theme-color" content="#0166FF" />',
  ]

  it.each([
    ['index.html', () => indexHtml],
    ['audit.html', () => auditHtml],
    ['audit-report.html', () => auditReportHtml],
  ])('%s declares the full icon set', (_name, getHtml) => {
    for (const tag of FAVICON_TAGS) {
      expect(getHtml()).toContain(tag)
    }
  })

  it.each([
    'favicon.svg', 'favicon-32.png', 'favicon-16.png',
    'apple-touch-icon.png', 'site.webmanifest', 'icon-192.png', 'icon-512.png',
  ])('%s exists in the build output', (filename) => {
    expect(fs.existsSync(path.join(outDir, filename))).toBe(true)
  })
})

// Part 1: the lemlist visitor-tracking pixel is a static tag in
// audit.html specifically, because Vercel's routing (vercel.json)
// sends audit.parleo.io's "/" — and only "/" — to that document; /r/
// and /s/ are a wholly separate document (audit-report.html) that
// never carries this tag, so a merchant's forwarded report link stays
// tracker-free. index.html (every other host) doesn't carry it either
// — the landing (LandingPage.jsx) never renders there (see App.jsx's
// isAuditHost() gate).
describe('lemlist visitor-tracking pixel — landing document only (Part 1)', () => {
  it('audit.html loads it async', () => {
    expect(auditHtml).toMatch(/<script async src="https:\/\/app\.lemlist\.com\/api\/visitors\/tracking\?[^"]*"><\/script>/)
  })

  it('audit-report.html (/r/, /s/) carries no lemlist reference', () => {
    expect(auditReportHtml).not.toMatch(/lemlist/i)
  })

  it('index.html (every other host) carries no lemlist reference', () => {
    expect(indexHtml).not.toMatch(/lemlist/i)
  })
})

// The OpenAI (ChatGPT Ads) Measurement Pixel. Unlike lemlist, this one
// IS on audit-report.html — the single, deliberate exception to the
// "/r/ and /s/ carry no tracker" rule, because contents_viewed
// can only be observed where a score actually renders (see the comment
// above the marker in audit-report.html). What these assertions pin
// down is that it appears EXACTLY once per audit document — the ID
// lives in one constants file and is written in by one build plugin,
// so a second copy pasted into a head would be a real regression —
// that index.html (every other host) never gains it, and that the
// loader still precedes the font stylesheet, since the inline queue
// must exist before the async SDK lands.
describe('OpenAI Measurement Pixel — both audit documents (not index.html)', () => {
  const LOADER_SRC = 'https://bzrcdn.openai.com/sdk/oaiq.min.js'

  function countOf(html, needle) {
    return html.split(needle).length - 1
  }

  it.each([
    ['audit.html', () => auditHtml],
    ['audit-report.html', () => auditReportHtml],
  ])('%s carries exactly one loader and one init with the pixel ID', (_name, getHtml) => {
    const html = getHtml()
    expect(countOf(html, LOADER_SRC)).toBe(1)
    expect(countOf(html, 'oaiq("init"')).toBe(1)
    expect(countOf(html, OPENAI_PIXEL_ID)).toBe(1)
    // Shape check on top of the count: the ID has to be the init
    // call's pixelId, not merely present somewhere in the document.
    expect(html).toMatch(new RegExp(`oaiq\\("init", \\{\\s*pixelId: "${OPENAI_PIXEL_ID}",`))
  })

  it.each([
    ['audit.html', () => auditHtml],
    ['audit-report.html', () => auditReportHtml],
  ])('%s loads the pixel before the fonts.googleapis stylesheet', (_name, getHtml) => {
    const html = getHtml()
    const loaderAt = html.indexOf(LOADER_SRC)
    const fontsAt = html.indexOf('fonts.googleapis.com/css2')
    expect(loaderAt).toBeGreaterThan(-1)
    expect(fontsAt).toBeGreaterThan(-1)
    expect(loaderAt).toBeLessThan(fontsAt)
  })

  it.each([
    ['audit.html', () => auditHtml],
    ['audit-report.html', () => auditReportHtml],
  ])('%s fully consumes the marker', (_name, getHtml) => {
    expect(getHtml()).not.toContain('<!--OPENAI_PIXEL-->')
  })

  it('index.html (every other host) carries no oaiq or openai.com reference', () => {
    expect(indexHtml).not.toMatch(/oaiq/i)
    expect(indexHtml).not.toMatch(/openai\.com/i)
    expect(indexHtml).not.toContain(OPENAI_PIXEL_ID)
  })
})
