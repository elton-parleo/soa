#!/usr/bin/env node
/**
 * Regenerates public/og/audit-landing.png from
 * scripts/og-image-design.html via headless Chrome — chosen over
 * node+satori/resvg because this card needs the real DS webfont
 * (Inter Tight, loaded from Google Fonts) shaped and rendered exactly
 * as a browser would, and over Playwright because a browser already
 * sitting on the machine is less new infra than adding a browser-
 * automation dependency to the repo. See og-image-design.html's own
 * comment for the full rationale and the numbers' provenance.
 *
 *   node scripts/generate-og-image.mjs
 *
 * Requires a local Chrome/Chromium install (checks the common per-OS
 * paths below). If none is found, open og-image-design.html in any
 * browser, size the viewport to exactly 1200x630, and screenshot the
 * page to public/og/audit-landing.png by hand.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DESIGN_HTML = path.join(__dirname, 'og-image-design.html')
const OUT_PATH = path.join(__dirname, '../public/og/audit-landing.png')

const CANDIDATE_CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', // macOS
  '/usr/bin/google-chrome', // Linux
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', // Windows
]

function findChrome() {
  for (const p of CANDIDATE_CHROME_PATHS) {
    if (fs.existsSync(p)) return p
  }
  return null
}

function main() {
  const chrome = findChrome()
  if (!chrome) {
    console.error(
      'No local Chrome/Chromium found. Open scripts/og-image-design.html in a browser,\n' +
      'size the viewport to exactly 1200x630, and screenshot it to public/og/audit-landing.png by hand.',
    )
    process.exit(1)
  }

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true })

  execFileSync(chrome, [
    '--headless',
    '--disable-gpu',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--window-size=1200,630',
    '--virtual-time-budget=4000', // give the Google Fonts request time to land before capture
    `--screenshot=${OUT_PATH}`,
    `file://${DESIGN_HTML}`,
  ])

  console.log(`wrote ${path.relative(path.join(__dirname, '..'), OUT_PATH)} (1200x630)`)
}

main()
