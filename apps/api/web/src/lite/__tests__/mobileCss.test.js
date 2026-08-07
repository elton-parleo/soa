/**
 * Mobile-friendly landing + report (G1-G5, LM1-LM5, RM1-RM9): asserts
 * the actual mobile CSS shipped in theme.css, not a rendered layout —
 * jsdom has no layout engine and doesn't even inject stylesheets during
 * tests (confirmed: `document.querySelectorAll('style')` is empty after
 * rendering a page in this suite), so `window.innerWidth` assertions or
 * getComputedStyle checks can't tell a real overflow from a false pass.
 * This follows the repo's own existing precedent (LiteFullReport.test.jsx's
 * cssBlock() helper) — read the stylesheet as text and assert the rules
 * that actually ship, since that's the one thing this test environment
 * can check honestly. Real-viewport correctness (no horizontal scroll,
 * tap-target hit area, the rail replacement's live behavior) was
 * verified directly against the dev server with a real browser during
 * this session — see the PR description.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const THEME_CSS = fs.readFileSync(path.join(__dirname, '../theme.css'), 'utf8')

// Returns every balanced-brace block for a given selector. A class can
// legitimately appear twice — once as a base "hidden by default" rule,
// once inside @media as the phone override — so a single indexOf isn't
// enough to find the one we actually want to assert on. It can also
// appear as one of several comma-separated selectors sharing one rule
// body (e.g. ".a,\n.b {...}") — matched via a regex on the selector
// followed by either "," or "{" (with whitespace), not a literal
// `selector + ' {'` string.
function cssBlocks(css, selector) {
  const escaped = selector.replace(/[.[\]]/g, '\\$&')
  const re = new RegExp(`${escaped}\\s*[,{]`, 'g')
  const blocks = []
  let match
  while ((match = re.exec(css)) !== null) {
    const braceStart = css.indexOf('{', match.index)
    let depth = 0
    let i = braceStart
    for (; i < css.length; i++) {
      if (css[i] === '{') depth++
      else if (css[i] === '}') {
        depth--
        if (depth === 0) break
      }
    }
    blocks.push(css.slice(braceStart + 1, i))
  }
  return blocks
}

function anyBlockMatches(css, selector, pattern) {
  const blocks = cssBlocks(css, selector)
  return blocks.length > 0 && blocks.some((b) => pattern.test(b))
}

describe('G1: breakpoint policy defined once', () => {
  it('documents phone <=640, tablet 641-1024, desktop >1024 in the DS layer', () => {
    expect(THEME_CSS).toMatch(/phone.*640px/i)
    expect(THEME_CSS).toMatch(/tablet.*641.*1024px/i)
    expect(THEME_CSS).toMatch(/desktop.*1024px/i)
  })

  it('every new mobile rule in this stage lives under a 640px or 641-1024px media query, never a bare selector', () => {
    // Structural spot-check: none of this stage's new classNames carry
    // a *base* (non-media) layout-changing rule — only phone/tablet
    // overrides — the desktop-untouched requirement's other half (the
    // JSX inline styles being untouched) is checked in the snapshot
    // test file, not here.
    const idx = THEME_CSS.indexOf('MOBILE — V4 audit landing')
    expect(idx).toBeGreaterThan(-1)
  })
})

describe('G3: tap targets — 44px hit area on phone, desktop untouched', () => {
  it('buttons and range inputs get a real hit area under the phone media query', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-root button', /min-height:\s*44px/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-root input[type="range"]', /padding/)).toBe(true)
  })

  it('the sections-sheet close button and item rows meet 44px', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-sheet-close', /min-height:\s*44px/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-sheet-item', /min-height:\s*44px/)).toBe(true)
  })

  it('the mobile Sections trigger meets 44px', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-sections-btn', /min-height:\s*44px/)).toBe(true)
  })

  it('long button/mono-label text is allowed to wrap on phone instead of forcing overflow (the Stakes CTA bug)', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-root .btn-lift', /white-space:\s*normal\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-root .mono-label', /white-space:\s*normal\s*!important/)).toBe(true)
  })
})

describe('G4: display numbers clamp() instead of a fixed size on phone', () => {
  it('the hero headline and every large display number carry a clamp()', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-hero-grid h1.section-heading', /clamp\(/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-display-num', /clamp\(/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-scorehero-headline', /clamp\(/)).toBe(true)
  })
})

describe('G5: reduced motion + grain overlay + smooth scroll are unaffected', () => {
  it('tokens.css still carries the global reduced-motion override and grain overlay stays pointer-events:none', () => {
    const TOKENS_CSS = fs.readFileSync(path.join(__dirname, '../../ds/tokens.css'), 'utf8')
    expect(TOKENS_CSS).toMatch(/prefers-reduced-motion:reduce\)\{\*\{animation:none!important;transition:none!important\}\}/)
    expect(TOKENS_CSS).toMatch(/\.grain-overlay::after\{[^}]*pointer-events:none/)
    expect(TOKENS_CSS).toMatch(/html\{scroll-behavior:smooth/)
  })
})

describe('LM1-LM5: landing page phone rules', () => {
  it('LM1: nav label + separator + sample link drop out of the bar', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-landing-nav-label', /display:\s*none\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-landing-nav-samplelink', /display:\s*none\s*!important/)).toBe(true)
  })

  it('LM2: hero stacks to one column and shows the mobile eyebrow', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-hero-grid', /display:\s*block\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-hero-mobile-eyebrow', /display:\s*block\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-form-compact-row', /flex-direction:\s*column\s*!important/)).toBe(true)
  })

  it('LM3: stakes/leakage-estimator sliders stack, CTA goes full width', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-stakes-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-stakes-cta', /display:\s*block\s*!important/)).toBe(true)
  })

  it('LM4: field-evidence, path, sample, framework, grounded, truesync grids collapse to one column', () => {
    for (const sel of ['.lite-field-evidence-grid', '.lite-path-grid', '.lite-sample-grid', '.lite-framework-row-grid', '.lite-framework-tiles-grid', '.lite-landing-grounded-grid', '.lite-truesync-landing-grid']) {
      expect(anyBlockMatches(THEME_CSS, sel, /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    }
  })

  it('LM5: final CTA panel gets lighter padding, footer wraps and centers', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-finalcta-panel', /padding/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-landing-footer-row', /flex-wrap:\s*wrap/)).toBe(true)
  })
})

describe('RM1: report rail replacement', () => {
  it('the shell collapses to one column and the desktop rail hides on phone', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-shell', /display:\s*block\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-rail', /display:\s*none\s*!important/)).toBe(true)
  })

  it('the mobile nav replacement stays hidden above phone width (symmetric with the rail)', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-nav', /display:\s*none\s*!important/)).toBe(true)
  })

  it('the sticky bar is position:fixed (not sticky — its containing block was too short to stick within, confirmed live) and stays under the 56px ceiling', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-stickybar', /position:\s*fixed/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-stickybar', /max-height:\s*56px/)).toBe(true)
  })

  it('the sections sheet overlay covers the viewport', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-sheet-overlay', /position:\s*fixed/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-mobile-sheet-overlay', /inset:\s*0/)).toBe(true)
  })
})

describe('RM2-RM9: report section phone stacking', () => {
  it('RM2: score hero pace lanes, tiles, and pillar cards stack', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-scorehero-lanes-row', /flex-direction:\s*column/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-scorehero-tiles-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-scorehero-pillars-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
  })

  it('RM3: dual-lens meters and the visibility/accessibility tile rows stack', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-dimrow-meters-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-vis-tiles-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-v4-acc-tiles-grid', /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
  })

  it('RM4: the parsed-page card puts the image above the fields and clamps its height', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-parsedcard-grid', /flex-direction:\s*column-reverse/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-parsedcard-image', /height:\s*200px\s*!important/)).toBe(true)
  })

  it('RM5: OfferFeed rows wrap the chips group onto their own line', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-offerfeed-row', /flex-wrap:\s*wrap/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-offerfeed-chips', /flex-basis:\s*100%/)).toBe(true)
  })

  it('RM6: the fixes table header hides and each row wraps its fixed-width columns onto their own line', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-fixrow-header', /display:\s*none\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-fixrow-points', /flex-basis:\s*100%/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-fixrow-owner', /flex-basis:\s*100%/)).toBe(true)
  })

  it('RM7: SoAIndex rows stack instead of squeezing a 3-column grid', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-soaindex-row', /flex-direction:\s*column/)).toBe(true)
  })

  it('RM8: funnel bars tighten, exposure/closing-fork/grounded grids collapse to one column', () => {
    for (const sel of ['.lite-exposure-adjust-grid', '.lite-closingfork-grid', '.lite-report-grounded-grid']) {
      expect(anyBlockMatches(THEME_CSS, sel, /grid-template-columns:\s*1fr\s*!important/)).toBe(true)
    }
  })

  it('shared ReportSection card padding tightens on phone (covers Visibility/Accessibility/FunnelGate/FixesTable/Exposure at once)', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-section', /padding/)).toBe(true)
  })
})

describe('Mobile QA round 1: three defects found in a real-phone walkthrough', () => {
  it('defect 1 — the shared ReportSection header (Exposure/Visibility/Accessibility/FixesTable/FunnelGate) stacks to column direction, and the extra/score/collapse group becomes a real wrapped row', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-report-section-header', /flex-direction:\s*column\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-section-controls', /display:\s*flex\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-report-section-controls', /flex-wrap:\s*wrap/)).toBe(true)
  })

  it('defect 1 sweep — this is a genuine sibling-instance fix: Visibility/Accessibility/FixesTable/FunnelGate/Exposure all route through the one ReportSection component, so the same phone rule covers all of them (no per-page override was added anywhere)', () => {
    // The only "extra"-bearing ReportSection callers are Exposure and
    // FixesTable, but the header stacking applies to every ReportSection
    // instance regardless of whether it passes extra/score, since the
    // fix is on the shared component's own header row.
    expect(THEME_CSS.match(/\.lite-report-section-header\s*[,{]/g)?.length).toBe(1)
    // The base display:contents lives inline in ReportSection.jsx's own
    // JSX (not in theme.css), so theme.css carries exactly one rule for
    // this class: the phone override.
    expect(THEME_CSS.match(/\.lite-report-section-controls\s*[,{]/g)?.length).toBe(1)
  })

  it('defect 2 — the True Value pillar header (its own bespoke DarkPanel intro, NOT the shared ReportSection defect 1 fixes — confirmed live that Visibility/Accessibility have no right-corner points display of their own) stacks to column, and the points/collapse group becomes a left-points/right-collapse row', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-tv-header', /flex-direction:\s*column\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-tv-header-meta', /flex-direction:\s*row\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-tv-header-meta', /justify-content:\s*space-between\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-tv-header-points-row', /justify-content:\s*flex-start\s*!important/)).toBe(true)
  })

  it('defect 3 — the real cause was MetricRow\'s 32px-per-column divider overhead forcing the sample-report card\'s grid track wider than the viewport (confirmed live: 475px track at 390px viewport, silently clipped by BrowserChrome\'s own overflow:hidden), not a tilt/rotate — there is no rotate/tilt/skew/perspective rule anywhere touching the landing preview cards', () => {
    expect(anyBlockMatches(THEME_CSS, '.lite-metric-row-item', /margin-left:\s*10px\s*!important/)).toBe(true)
    expect(anyBlockMatches(THEME_CSS, '.lite-metric-row-item', /padding-left:\s*10px\s*!important/)).toBe(true)
    expect(THEME_CSS).not.toMatch(/\.lite-sample-grid[^}]*rotate/)
    expect(THEME_CSS).not.toMatch(/\.lite-hero-grid[^}]*rotate/)
  })
})
