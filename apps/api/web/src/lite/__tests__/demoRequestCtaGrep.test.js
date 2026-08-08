/**
 * Leadgen session: static guard, source-level rather than rendered-DOM
 * (that coverage is in LandingPage.test.jsx and LiteFullReportV4.test.jsx)
 * — no walkthrough/TrueSync source file should hardcode a parleo.io
 * href again. Catches a regression even before a component test
 * happens to render the offending line.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FILES = [
  '../report/FixesTable.jsx',
  '../report/ClosingFork.jsx',
  '../report/TrueSyncBand.jsx',
  '../report/FunnelGate.jsx',
  '../landing/TrueSyncSection.jsx',
  '../publicUrls.js',
  '../report/reportContent.js',
].map((p) => path.join(__dirname, p))

describe('Leadgen session: no walkthrough/TrueSync CTA hardcodes a parleo.io href', () => {
  it.each(FILES)('%s', (file) => {
    const src = fs.readFileSync(file, 'utf8')
    expect(src).not.toMatch(/href=\{?['"]?https:\/\/parleo\.io/)
  })

  it('WALKTHROUGH_URL/FULL_ANALYSIS_URL/TRUESYNC_URL are gone, not just unused', () => {
    const publicUrls = fs.readFileSync(path.join(__dirname, '../publicUrls.js'), 'utf8')
    expect(publicUrls).not.toMatch(/WALKTHROUGH_URL|FULL_ANALYSIS_URL|TRUESYNC_URL/)
  })
})
