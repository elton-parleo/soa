/**
 * fix/full-analysis-mobile: regression guard for the actual bug — not
 * "does a mobile breakpoint exist" (grepping the source for `@media`
 * would have said yes even when this file was broken), but "does this
 * file's CSS actually PARSE into real rules a browser will apply."
 *
 * The live bug: a prose comment describing two class-name prefixes
 * placed a "*" directly before a "/" mid-sentence — CSS comments have
 * no escaping, so that closed the comment early, and everything from
 * there to the file's real closing marker parsed as garbage CSS,
 * dropping every rule in the file to 0 (confirmed live in a real
 * browser). A plain "the @media text exists in the file" test would
 * have passed on the broken file just as it does on the fixed one —
 * only actually parsing the stylesheet catches this class of bug.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const CSS_PATH = join(__dirname, '../fullAnalysis.css')

// Every selector this file is expected to declare. If the file's CSS
// silently fails to parse (the exact shape of the original bug), one
// or more of these goes missing from the walk below — the count check
// alone isn't enough, since a partial parse can still produce a
// nonzero rule count (confirmed live: jsdom recovers 1 rule from a
// reconstructed broken version of this file that should carry 2).
const EXPECTED_SELECTORS = [
  '.fa-report-shell',
  '.fa-report-rail',
  '.fa-report-content',
  '.fa-hero-lanes',
  '.fa-hero-headline',
  '.fa-analyst-tabs',
]

function parseSelectors(css) {
  const style = document.createElement('style')
  style.textContent = css
  document.head.appendChild(style)
  const selectors = []
  ;(function walk(rules) {
    for (const rule of rules) {
      if (rule.selectorText) selectors.push(rule.selectorText)
      if (rule.cssRules) walk(rule.cssRules)
    }
  })(style.sheet ? style.sheet.cssRules : [])
  document.head.removeChild(style)
  return selectors
}

describe('fullAnalysis.css — actually parses (not just "contains the text")', () => {
  let consoleErrorSpy

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    consoleErrorSpy.mockRestore()
  })

  it('declares every expected fa- selector as a real, parsed CSS rule', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const selectors = parseSelectors(css)
    const joined = selectors.join(' | ')
    for (const expected of EXPECTED_SELECTORS) {
      expect(joined).toContain(expected)
    }
  })

  it('logs no CSS parse error while loading the file', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    parseSelectors(css)
    expect(consoleErrorSpy).not.toHaveBeenCalled()
  })
})

describe('fullAnalysis.css — the shell/rail split moved to 768px', () => {
  it('.fa-report-shell/.fa-report-rail/.fa-report-content live inside a max-width:768px media query, matching theme.css\'s widened RM1 split', () => {
    const css = readFileSync(CSS_PATH, 'utf8')
    const style = document.createElement('style')
    style.textContent = css
    document.head.appendChild(style)
    let mediaParams = null
    for (const rule of style.sheet.cssRules) {
      if (rule.media && [...rule.cssRules].some((r) => r.selectorText === '.fa-report-shell')) {
        mediaParams = rule.media.mediaText
      }
    }
    document.head.removeChild(style)
    expect(mediaParams).toContain('768px')
  })
})
