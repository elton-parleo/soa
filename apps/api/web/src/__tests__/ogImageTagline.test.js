/**
 * The OG share card prints the audit address in its tagline, and it is
 * the one place that CANNOT import the constant: scripts/
 * og-image-design.html is rendered standalone by headless Chrome
 * (scripts/generate-og-image.mjs), outside the bundle, so there is no
 * module graph to reach through.
 *
 * That makes it exactly the kind of copy that goes stale silently —
 * and it did: the card kept advertising the retired host through the
 * whole /audit migration, and nothing failed. This asserts the two
 * agree, so the next address change has to touch the card too.
 *
 * A source-level check on purpose. Asserting the rendered PNG would
 * mean OCR; asserting the design file is what actually needs to hold,
 * since the PNG is generated from it.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

import { DEFAULT_PUBLIC_AUDIT_BASE_URL } from '../lite/audit-host.constants.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DESIGN_HTML = path.join(__dirname, '../../scripts/og-image-design.html')
const OG_PNG = path.join(__dirname, '../../public/og/audit-landing.png')

const design = fs.readFileSync(DESIGN_HTML, 'utf8')
const displayAddress = DEFAULT_PUBLIC_AUDIT_BASE_URL.replace(/^https?:\/\//, '')

describe('OG card tagline — kept in step with the canonical address', () => {
  it('prints the canonical address, scheme stripped', () => {
    const tagline = design.match(/<div class="tagline">(.*?)<\/div>/s)
    expect(tagline).not.toBeNull()
    expect(tagline[1]).toContain(displayAddress)
  })

  it('names no other parleo address anywhere in the design file', () => {
    const addresses = [...design.matchAll(/[a-z0-9.-]*parleo\.io[a-z0-9/-]*/gi)].map((m) => m[0])
    expect(addresses.length).toBeGreaterThan(0)
    for (const address of addresses) {
      expect(address).toBe(displayAddress)
    }
  })

  // The card is a generated artifact: if the design file moved and the
  // PNG did not, unfurls keep showing the old text. Nothing here can
  // prove they match, but a real 1200x630 PNG must at least be present
  // — the dimensions the og:image tags declare (landingMeta.js).
  it('has a regenerated 1200x630 PNG alongside it', () => {
    expect(fs.existsSync(OG_PNG)).toBe(true)
    const buf = fs.readFileSync(OG_PNG)
    expect(buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))).toBe(true)
    expect(buf.readUInt32BE(16)).toBe(1200)
    expect(buf.readUInt32BE(20)).toBe(630)
  })
})
