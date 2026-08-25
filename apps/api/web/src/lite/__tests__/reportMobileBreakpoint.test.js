/**
 * fix/full-analysis-mobile: RM1's rail-hide split (theme.css) widened
 * live from 640/641 to 768/769 — a real, pre-existing gap where 641-
 * 767px still showed the 222px rail (this rule hadn't fired) but the
 * content column was too narrow for the desktop grids inside it,
 * confirmed as genuine horizontal page overflow on both lite's own
 * report and Full Analysis's before the fix. Pins the new value and
 * that the three pieces stay in sync with each other (rail hides,
 * mobile-nav shows, the resolving skeleton's own wordmark swap — all
 * three "is this the phone nav or the desktop rail" decisions must
 * agree, or one range shows neither).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const CSS_PATH = join(__dirname, '../theme.css')

function loadStylesheet(css) {
  const style = document.createElement('style')
  style.textContent = css
  document.head.appendChild(style)
  return style
}

function mediaTextFor(sheet, selector) {
  for (const rule of sheet.cssRules) {
    if (rule.media && [...rule.cssRules].some((r) => r.selectorText === selector)) {
      return rule.media.mediaText
    }
  }
  return null
}

describe('theme.css — parses cleanly at real production size', () => {
  it('parses into hundreds of rules, not a handful (coarse guard against a silently-truncated file)', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const style = loadStylesheet(css)
    let count = 0
    ;(function walk(rules) {
      for (const rule of rules) {
        count++
        if (rule.cssRules) walk(rule.cssRules)
      }
    })(style.sheet.cssRules)
    document.head.removeChild(style)
    expect(count).toBeGreaterThan(300)
  })
})

describe('theme.css — RM1 rail-hide split is 768/769px, and its three pieces agree', () => {
  it('.lite-report-shell/.lite-report-rail/.lite-report-content collapse at max-width:768px', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const style = loadStylesheet(css)
    const media = mediaTextFor(style.sheet, '.lite-report-shell')
    document.head.removeChild(style)
    expect(media).toContain('768px')
  })

  it('.lite-report-mobile-nav hides again above min-width:769px — the exact complement of the 768px collapse', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const style = loadStylesheet(css)
    const media = mediaTextFor(style.sheet, '.lite-report-mobile-nav')
    document.head.removeChild(style)
    expect(media).toBe('(min-width: 769px)')
  })

  it('.lite-resolving-mark (the resolving-skeleton wordmark swap) uses the same 768px split as the rail it substitutes for', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const style = loadStylesheet(css)
    const media = mediaTextFor(style.sheet, '.lite-resolving-mark')
    document.head.removeChild(style)
    expect(media).toContain('768px')
  })
})
