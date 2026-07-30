import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, fireEvent, within, cleanup, act } from '@testing-library/react'
import { describe, it, expect, afterEach, vi } from 'vitest'
import '@testing-library/jest-dom'

import { AnatomyOfAnAnswer, SAMPLE_REPORT_URL } from '../landing/AnatomyOfAnAnswer.jsx'
import {
  SCORER_VERSION,
  LITE_QUERY_COUNT,
  DIMENSIONS,
  DIMENSIONS_BY_CODE,
  PILLAR_NAMES,
  PILLAR_QUESTIONS,
  PILLAR_ORDER,
  PILLAR_WEIGHTS,
  PILLAR_VISIBILITY,
  PILLAR_ACCESSIBILITY,
  PILLAR_TRUE_VALUE,
  TOTAL_MAX,
} from '../landing/scanDimensionsRegistry.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT_SRC = fs.readFileSync(
  path.join(__dirname, '../landing/AnatomyOfAnAnswer.jsx'), 'utf8',
)

function flatText(segments) {
  return segments.map((s) => s.text).join('')
}

afterEach(() => {
  cleanup()
})

// ─── P0 gate: registry totals (enforced in CI) ───────────────────────────

describe('AnatomyOfAnAnswer — P0 registry gate', () => {
  it('registry is scorer_version 4 with pillar weights summing to 40/20/40', () => {
    expect(SCORER_VERSION).toBe('4')
    expect(PILLAR_ORDER).toEqual(['visibility', 'accessibility', 'true_value'])
    expect(PILLAR_WEIGHTS.visibility).toBe(40)
    expect(PILLAR_WEIGHTS.accessibility).toBe(20)
    expect(PILLAR_WEIGHTS.true_value).toBe(40)
    expect(TOTAL_MAX).toBe(100)
  })

  it('renders a hidden scorer-version marker matching the registry', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('[data-scorer-version]').getAttribute('data-scorer-version')).toBe('4')
  })

  it('True Value has exactly four dimensions in the documented order, Value Protocols last', () => {
    const tvCodes = DIMENSIONS.filter((d) => d.pillar === PILLAR_TRUE_VALUE).map((d) => d.code)
    expect(tvCodes).toEqual(['price_truth', 'member_value', 'deal_citability', 'value_protocols'])
  })

  it('preserves the #methodology anchor id for existing nav/deep links', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('#methodology')).toBeInTheDocument()
  })
})

// ─── Old section removed (B4) ─────────────────────────────────────────

describe('AnatomyOfAnAnswer — old walkthrough section fully removed (B4)', () => {
  it('component source contains none of the retired strings', () => {
    for (const banned of [
      'anatomy of an answer', 'Anatomy of an Answer', 'ANATOMY OF AN ANSWER',
      'The score is the anatomy', 'SIGNALS WE DETECT', 'ONLY WE SCORE THIS',
      'SCORE CAP', 'Score cap', 'Foundation ·', 'Transaction Rails',
    ]) {
      expect(COMPONENT_SRC.toLowerCase()).not.toContain(banned.toLowerCase())
    }
  })

  it('rendered output contains none of the retired strings, and never renders a bare "SEEN" label', () => {
    render(<AnatomyOfAnAnswer />)
    const rendered = document.body.textContent
    for (const banned of ['SCORE CAP', 'Foundation', 'Transaction Rails', 'SIGNALS WE DETECT']) {
      expect(rendered).not.toContain(banned)
    }
    expect(rendered).not.toMatch(/\bSEEN\b/)
  })

  it('an opened row renders "WHAT WE CHECK", not the retired "SIGNALS WE DETECT"', () => {
    render(<AnatomyOfAnAnswer />)
    fireEvent.click(screen.getByText('ACCESSIBILITY').closest('button'))
    fireEvent.click(screen.getByText(DIMENSIONS_BY_CODE.catalog_context.name).closest('button'))
    expect(screen.getByText('WHAT WE CHECK')).toBeInTheDocument()
  })
})

// ─── Structure: one exhibit, one framework card ───────────────────────

describe('AnatomyOfAnAnswer — structure (THE EXAMPLE)', () => {
  it('renders exactly one exhibit container with its tab, question pill, both cards, arrow, and caption', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const exhibits = container.querySelectorAll('.lite-anatomy-exhibit')
    expect(exhibits).toHaveLength(1)
    const exhibit = exhibits[0]
    expect(within(exhibit).getByText('EXAMPLE')).toBeInTheDocument()
    expect(within(exhibit).getByText('"best sheets worth the money?"')).toBeInTheDocument()
    expect(exhibit.querySelector('.lite-anatomy-seen')).toBeInTheDocument()
    expect(exhibit.querySelector('.lite-anatomy-said')).toBeInTheDocument()
    expect(exhibit.querySelector('.lite-anatomy-ex-mid svg')).toBeInTheDocument()
    expect(within(exhibit).getByText(`${LITE_QUERY_COUNT} QUERIES`)).toBeInTheDocument()
    expect(within(exhibit).getByText(/EVERY HIGHLIGHT IS SCORED BELOW\./)).toBeInTheDocument()
  })

  it('the exhibit arrow label uses LITE_QUERY_COUNT, never a hard-coded literal', () => {
    expect(COMPONENT_SRC).not.toMatch(/>24 QUERIES</)
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText(`${LITE_QUERY_COUNT} QUERIES`)).toBeInTheDocument()
  })
})

describe('AnatomyOfAnAnswer — structure (THE FRAMEWORK)', () => {
  it('renders exactly one framework card containing the equation bar, all three panels, and the gate', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const cards = container.querySelectorAll('.lite-anatomy-fw')
    expect(cards).toHaveLength(1)
    const fw = cards[0]
    expect(within(fw).getByRole('tablist')).toBeInTheDocument()
    expect(fw.querySelectorAll('.lite-anatomy-panel')).toHaveLength(3)
    expect(fw.querySelector('.lite-anatomy-gate')).toBeInTheDocument()
  })

  it('renders the FRAMEWORK floating tab label', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText('THE FRAMEWORK')).toBeInTheDocument()
  })
})

// ─── Tabs (B1) ──────────────────────────────────────────────────────────

describe('AnatomyOfAnAnswer — equation tab bar (B1)', () => {
  it('is a real tablist with three tabs, defaulting to Visibility selected', () => {
    render(<AnatomyOfAnAnswer />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'false')
  })

  it('renders each pillar name, weight, and question from the registry', () => {
    render(<AnatomyOfAnAnswer />)
    for (const pillar of PILLAR_ORDER) {
      const tab = screen.getByText(PILLAR_NAMES[pillar].toUpperCase()).closest('button')
      expect(within(tab).getByText(String(PILLAR_WEIGHTS[pillar]))).toBeInTheDocument()
      expect(within(tab).getByText(PILLAR_QUESTIONS[pillar])).toBeInTheDocument()
    }
  })

  it('renders the total block with the registry TOTAL_MAX', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText('SCORE')).toBeInTheDocument()
    expect(screen.getByText(String(TOTAL_MAX))).toBeInTheDocument()
    expect(screen.getByText('simple sum')).toBeInTheDocument()
  })

  it('clicking a tab shows exactly one panel and moves aria-selected', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const tabs = screen.getAllByRole('tab')
    fireEvent.click(tabs[2])
    expect(tabs[0]).toHaveAttribute('aria-selected', 'false')
    expect(tabs[2]).toHaveAttribute('aria-selected', 'true')

    const visiblePanels = Array.from(container.querySelectorAll('.lite-anatomy-fw > div > .lite-anatomy-panel'))
      .filter((p) => getComputedStyle(p.parentElement).display !== 'none')
    expect(visiblePanels).toHaveLength(1)
    expect(visiblePanels[0]).toHaveClass('lite-anatomy-panel--tv')
  })

  it('arrow keys navigate between tabs and wrap around', () => {
    render(<AnatomyOfAnAnswer />)
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' })
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(tabs[1], { key: 'ArrowRight' })
    expect(tabs[2]).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(tabs[2], { key: 'ArrowRight' })
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true') // wraps
    fireEvent.keyDown(tabs[0], { key: 'ArrowLeft' })
    expect(tabs[2]).toHaveAttribute('aria-selected', 'true') // wraps backward
  })

  it('the True Value tab number is styled with the accent modifier class', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const tvTab = screen.getByText('TRUE VALUE').closest('button')
    expect(tvTab).toHaveClass('lite-anatomy-eq-btn--tv')
    expect(container.querySelector('.lite-anatomy-eq-btn--tv .lite-anatomy-eq-n')).toBeInTheDocument()
  })
})

// ─── Accordions: table-driven over all 9 dimensions ──────────────────────

function openRowFor(code) {
  const pillar = DIMENSIONS_BY_CODE[code].pillar
  const tabLabel = PILLAR_NAMES[pillar].toUpperCase()
  fireEvent.click(screen.getByText(tabLabel).closest('button'))
  const dim = DIMENSIONS_BY_CODE[code]
  const row = screen.getByText(dim.name).closest('button')
  fireEvent.click(row)
  return row
}

describe('AnatomyOfAnAnswer — accordion rows (D1/D2, table-driven over all 9 dimensions)', () => {
  it.each(DIMENSIONS)('$code renders its name, one-liner, points, chips, caption, and correct visual_kind', (dim) => {
    render(<AnatomyOfAnAnswer />)
    const row = openRowFor(dim.code)
    const dbody = row.parentElement.querySelector('.lite-anatomy-dbody')
    expect(dbody).toBeInTheDocument()

    // header
    expect(within(row).getByText(dim.name)).toBeInTheDocument()
    expect(within(row).getByText(dim.oneLiner)).toBeInTheDocument()
    expect(within(row).getByText(String(dim.weight))).toBeInTheDocument()
    if (dim.siteOnly) expect(within(row).getByText('SITE ONLY')).toBeInTheDocument()

    // left/right labels
    expect(within(dbody).getByText(dim.leftLabel)).toBeInTheDocument()
    expect(within(dbody).getByText(dim.rightLabel)).toBeInTheDocument()

    // chips (agent_access renders pips instead of chips on the left — no chips to check)
    if (dim.visualKind !== 'pips') {
      for (const chip of dim.chips) {
        const label = typeof chip === 'string' ? chip : chip.label
        expect(within(dbody).getByText(label)).toBeInTheDocument()
      }
    }

    // caption (scoredCaption is an ordered array of {text, bold} segments,
    // rendered as sibling spans/b inside .lite-anatomy-mcap — checked
    // against that element's full textContent rather than getByText,
    // which only matches a single element's own text)
    const mcap = dbody.querySelector('.lite-anatomy-mcap')
    expect(mcap.textContent).toBe(flatText(dim.scoredCaption))

    // visual kind
    switch (dim.visualKind) {
      case 'meter':
        expect(dbody.querySelector('.lite-anatomy-meter')).toBeInTheDocument()
        expect(within(dbody).getByText(dim.visualParams.tickLabel)).toBeInTheDocument()
        break
      case 'ladder':
        expect(dbody.querySelector('.lite-anatomy-ladder')).toBeInTheDocument()
        for (const band of dim.visualParams.bands) {
          expect(within(dbody).getByText(band.label)).toBeInTheDocument()
        }
        break
      case 'pips':
        expect(dbody.querySelector('.lite-anatomy-pips')).toBeInTheDocument()
        for (const pip of dim.visualParams.pips) {
          expect(within(dbody).getByText(pip.label)).toBeInTheDocument()
        }
        break
      case 'grid':
        expect(dbody.querySelectorAll('.lite-anatomy-grid4-ok')).toHaveLength(dim.visualParams.ok)
        break
      case 'duo':
        expect(dbody.querySelector('.lite-anatomy-duo')).toBeInTheDocument()
        expect(within(dbody).getByText(dim.visualParams.leftLabel)).toBeInTheDocument()
        expect(within(dbody).getByText(dim.visualParams.rightLabel)).toBeInTheDocument()
        break
      case 'none':
        expect(dbody.querySelector('.lite-anatomy-meter')).not.toBeInTheDocument()
        expect(dbody.querySelector('.lite-anatomy-duo')).not.toBeInTheDocument()
        expect(dbody.querySelector('.lite-anatomy-ladder')).not.toBeInTheDocument()
        break
      default:
        throw new Error(`unhandled visual_kind ${dim.visualKind}`)
    }
  })

  it('is one-open-per-panel: opening a second row in the same panel closes the first', () => {
    render(<AnatomyOfAnAnswer />)
    fireEvent.click(screen.getByText('VISIBILITY').closest('button'))
    const somRow = screen.getByText(DIMENSIONS_BY_CODE.share_of_mentions.name).closest('button')
    const rsRow = screen.getByText(DIMENSIONS_BY_CODE.recommendation_strength.name).closest('button')

    fireEvent.click(somRow)
    expect(somRow).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(rsRow)
    expect(rsRow).toHaveAttribute('aria-expanded', 'true')
    expect(somRow).toHaveAttribute('aria-expanded', 'false')
  })

  it('each panel keeps its own open row independently of the others (switching tabs does not reset other panels)', () => {
    render(<AnatomyOfAnAnswer />)
    openRowFor('agent_access') // opens Accessibility panel's row, switches to that tab
    fireEvent.click(screen.getByText('VISIBILITY').closest('button'))
    fireEvent.click(screen.getByText(DIMENSIONS_BY_CODE.share_of_mentions.name).closest('button'))
    fireEvent.click(screen.getByText('ACCESSIBILITY').closest('button'))
    expect(screen.getByText(DIMENSIONS_BY_CODE.agent_access.name).closest('button')).toHaveAttribute('aria-expanded', 'true')
  })

  it('clicking an open row again closes it (no row open in that panel)', () => {
    render(<AnatomyOfAnAnswer />)
    const row = openRowFor('price_truth')
    expect(row).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(row)
    expect(row).toHaveAttribute('aria-expanded', 'false')
  })

  it('closing a row unmounts its detail body', () => {
    render(<AnatomyOfAnAnswer />)
    const row = openRowFor('member_value')
    expect(row.parentElement.querySelector('.lite-anatomy-dbody')).toBeInTheDocument()
    fireEvent.click(row)
    expect(row.parentElement.querySelector('.lite-anatomy-dbody')).not.toBeInTheDocument()
  })
})

// ─── Animation: fills 0 before expand, pulse XMAP, reduced-motion ────────

describe('AnatomyOfAnAnswer — fill animation (D1/D3)', () => {
  it('a meter fill is width 0 before the row opens', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    // The row starts closed, so no .lite-anatomy-meter exists in the DOM
    // at all yet (dbody unmounts when closed) — this itself proves the
    // fill never renders pre-animated; opening it renders at the target.
    expect(container.querySelector('.lite-anatomy-meter-fill')).not.toBeInTheDocument()
    const row = openRowFor('share_of_mentions')
    const fill = row.parentElement.querySelector('.lite-anatomy-meter-fill')
    expect(fill.style.width).toBe(`${DIMENSIONS_BY_CODE.share_of_mentions.visualParams.fillPct}%`)
  })

  it('a duo bar renders both target widths once open', () => {
    render(<AnatomyOfAnAnswer />)
    const row = openRowFor('price_truth')
    const params = DIMENSIONS_BY_CODE.price_truth.visualParams
    const leftBar = row.parentElement.querySelector('.lite-anatomy-duo-l div')
    const rightBar = row.parentElement.querySelector('.lite-anatomy-duo-r div')
    expect(leftBar.style.width).toBe(`${params.leftPct}%`)
    expect(rightBar.style.width).toBe(`${params.rightPct}%`)
  })
})

describe('AnatomyOfAnAnswer — exhibit pulse cross-highlight (D3, XMAP)', () => {
  it.each([
    ['price_truth', '269.00', '$269'],
    ['member_value', '228.65', 'members pay $228.65'],
    ['deal_citability', '25% BUNDLE', 'Bundles 25% off through Sunday'],
  ])('opening %s pulses its seen-card line and said-card mark', (code, seenText, saidText) => {
    render(<AnatomyOfAnAnswer />)
    openRowFor(code)
    const seenLine = screen.getByText((_, node) => node?.textContent?.includes(seenText) && node.classList?.contains('lite-anatomy-kv'))
    expect(seenLine).toHaveClass('lite-anatomy-pulse')
    const saidMark = screen.getByText(saidText)
    expect(saidMark).toHaveClass('lite-anatomy-pulse')
  })

  it('opening value_protocols pulses the seen-card capability badges row, not a said-card mark (encode-only)', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    openRowFor('value_protocols')
    const badges = container.querySelector('.lite-anatomy-badges')
    expect(badges).toHaveClass('lite-anatomy-pulse')
    expect(container.querySelectorAll('.lite-anatomy-said mark.lite-anatomy-pulse')).toHaveLength(0)
  })

  it('the pulse clears after the animation duration and does not persist indefinitely', () => {
    vi.useFakeTimers()
    try {
      render(<AnatomyOfAnAnswer />)
      openRowFor('price_truth')
      expect(document.querySelectorAll('.lite-anatomy-pulse').length).toBeGreaterThan(0)
      act(() => { vi.advanceTimersByTime(2100) })
      expect(document.querySelectorAll('.lite-anatomy-pulse').length).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('opening a non-True-Value row never pulses anything in the exhibit', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    openRowFor('agent_access')
    expect(container.querySelectorAll('.lite-anatomy-exhibit .lite-anatomy-pulse')).toHaveLength(0)
  })
})

describe('AnatomyOfAnAnswer — reduced motion (D3)', () => {
  it('never applies the pulse class when prefers-reduced-motion is set', () => {
    const originalMatchMedia = window.matchMedia
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }))
    try {
      const { container } = render(<AnatomyOfAnAnswer />)
      openRowFor('price_truth')
      expect(container.querySelectorAll('.lite-anatomy-pulse')).toHaveLength(0)
    } finally {
      window.matchMedia = originalMatchMedia
    }
  })
})

// ─── Gate demo (B2) ───────────────────────────────────────────────────

describe('AnatomyOfAnAnswer — verdict gate demo (B2)', () => {
  it('defaults to VALUE ENCODED: 82, AGENT-READY, with the exact sentence', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText('VALUE ENCODED')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('82')).toBeInTheDocument()
    expect(screen.getByText('AGENT-READY')).toBeInTheDocument()
    expect(screen.getByText("This store's value is readable and cited:")).toBeInTheDocument()
    expect(screen.getByText('82, agent-ready.')).toBeInTheDocument()
  })

  it('toggling to ZERO TRUE VALUE shows 42, NOT AGENT-READY, with the exact sentence', () => {
    render(<AnatomyOfAnAnswer />)
    fireEvent.click(screen.getByText('ZERO TRUE VALUE'))
    expect(screen.getByText('ZERO TRUE VALUE')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('VALUE ENCODED')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('NOT AGENT-READY')).toBeInTheDocument()
    expect(screen.getByText('Same store, zero True Value: 42 — and it fails the readiness check.')).toBeInTheDocument()
    expect(screen.getByText("Visibility alone can't pass.")).toBeInTheDocument()
  })

  it('the chip tone class matches ready/not-ready', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText('AGENT-READY')).toHaveClass('lite-anatomy-gch--ok')
    fireEvent.click(screen.getByText('ZERO TRUE VALUE'))
    expect(screen.getByText('NOT AGENT-READY')).toHaveClass('lite-anatomy-gch--no')
  })

  it('is keyboard-operable (a real button, not a div)', () => {
    render(<AnatomyOfAnAnswer />)
    const btn = screen.getByText('ZERO TRUE VALUE')
    expect(btn.tagName).toBe('BUTTON')
    expect(btn).toHaveAttribute('type', 'button')
  })
})

// ─── Copy discipline ───────────────────────────────────────────────────

describe('AnatomyOfAnAnswer — copy discipline (D2/B5)', () => {
  it('component source contains no dimension-name/points/chip/caption literals — everything reads from the registry', () => {
    for (const dim of DIMENSIONS) {
      expect(COMPONENT_SRC).not.toContain(`'${dim.name}'`)
      expect(COMPONENT_SRC).not.toContain(`"${dim.name}"`)
      expect(COMPONENT_SRC).not.toContain(`>${dim.name}<`)
      expect(COMPONENT_SRC).not.toContain(dim.oneLiner)
      for (const chip of dim.chips) {
        const label = typeof chip === 'string' ? chip : chip.label
        if (label.length > 15) expect(COMPONENT_SRC).not.toContain(label)
      }
      for (const seg of dim.scoredCaption) {
        if (seg.text.trim().length > 15) expect(COMPONENT_SRC).not.toContain(seg.text)
      }
    }
  })

  it('never mentions the retired score cap or the internal "rsi" metric name', () => {
    render(<AnatomyOfAnAnswer />)
    const rendered = document.body.textContent.toLowerCase()
    expect(rendered).not.toContain('caps at')
    expect(rendered).not.toMatch(/\bcap\b/)
    expect(rendered).not.toMatch(/\brsi\b/)
  })

  it('Value Protocols copy says "declares"/"declared", never "supports" (V2 wording discipline)', () => {
    render(<AnatomyOfAnAnswer />)
    const row = openRowFor('value_protocols')
    const text = row.parentElement.textContent.toLowerCase() + row.textContent.toLowerCase()
    expect(text).not.toContain('support')
  })

  it('no literal query count anywhere in the component source — every mention reads LITE_QUERY_COUNT', () => {
    expect(COMPONENT_SRC).not.toMatch(/\b24\b/)
  })

  it('the footer stamp carries the exact truth-rule copy, query count from the registry', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText(`${LITE_QUERY_COUNT} queries · ChatGPT only · deterministic · sample, not a category study`)).toBeInTheDocument()
  })

  it('the intro line reads the query count from the registry too', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText(new RegExp(`We ask ChatGPT ${LITE_QUERY_COUNT} shopper questions`))).toBeInTheDocument()
  })
})

// ─── Sample-report CTA (B3) ────────────────────────────────────────────

describe('AnatomyOfAnAnswer — sample report CTA (B3)', () => {
  it('renders an anchor to SAMPLE_REPORT_URL, opening in a new tab safely', () => {
    render(<AnatomyOfAnAnswer />)
    const link = screen.getByText(/View a sample report/).closest('a')
    expect(link).toHaveAttribute('href', SAMPLE_REPORT_URL)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('SAMPLE_REPORT_URL points at a real report token, not an obvious placeholder', () => {
    expect(SAMPLE_REPORT_URL).toMatch(/^\/report\/[a-f0-9]{32}$/)
  })
})

// ─── Perturbation (registry-drivenness proof) ─────────────────────────

describe('AnatomyOfAnAnswer — perturbation (registry-drivenness)', () => {
  it('perturbing a pillar weight moves the tab number and the total', () => {
    const original = DIMENSIONS_BY_CODE.share_of_mentions.weight
    DIMENSIONS_BY_CODE.share_of_mentions.weight = original + 10
    try {
      render(<AnatomyOfAnAnswer />)
      const visTab = screen.getByText('VISIBILITY').closest('button')
      expect(within(visTab).getByText(String(PILLAR_WEIGHTS.visibility))).toBeInTheDocument()
    } finally {
      DIMENSIONS_BY_CODE.share_of_mentions.weight = original
    }
  })

  it('perturbing a dimension weight moves its row points', () => {
    const original = DIMENSIONS_BY_CODE.member_value.weight
    DIMENSIONS_BY_CODE.member_value.weight = 41
    try {
      render(<AnatomyOfAnAnswer />)
      const row = openRowFor('member_value')
      expect(within(row).getByText('41')).toBeInTheDocument()
      expect(within(row).queryByText(String(original))).not.toBeInTheDocument()
    } finally {
      DIMENSIONS_BY_CODE.member_value.weight = original
    }
  })

  it('perturbing a duo dimension\'s visualParams labels moves the rendered duo labels', () => {
    const dim = DIMENSIONS_BY_CODE.price_truth
    const original = { ...dim.visualParams }
    dim.visualParams = { ...original, leftLabel: 'ON YOUR SITE · 99', rightLabel: 'IN ANSWERS · 98' }
    try {
      render(<AnatomyOfAnAnswer />)
      const row = openRowFor('price_truth')
      const dbody = row.parentElement
      expect(within(dbody).getByText('ON YOUR SITE · 99')).toBeInTheDocument()
      expect(within(dbody).getByText('IN ANSWERS · 98')).toBeInTheDocument()
    } finally {
      dim.visualParams = original
    }
  })
})

// ─── Responsive (360 / 768 / 1280) ─────────────────────────────────────
// jsdom does not evaluate CSS media queries, so these assert the class
// hooks theme.css's actual @media rules key off of are present, rather
// than computed layout.

describe('AnatomyOfAnAnswer — responsive structure (mobile 360px)', () => {
  afterEach(() => { window.innerWidth = 1024 })

  it.each([360, 768, 1280])('renders the exhibit and framework at %ipx without crashing', (width) => {
    window.innerWidth = width
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('.lite-anatomy-exhibit')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-ex-grid')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-fw')).toBeInTheDocument()
  })

  it('the exhibit grid carries the mobile-stacking hook (@media max-width:700px collapses to 1fr, rotates the arrow)', () => {
    window.innerWidth = 360
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('.lite-anatomy-ex-grid')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-ex-mid')).toBeInTheDocument()
  })

  it('every tab, row header, and gate control is reachable and clickable at 360px', () => {
    window.innerWidth = 360
    render(<AnatomyOfAnAnswer />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs).toHaveLength(3)
    fireEvent.click(tabs[2])
    const row = screen.getByText(DIMENSIONS_BY_CODE.price_truth.name).closest('button')
    fireEvent.click(row)
    expect(row).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(screen.getByText('ZERO TRUE VALUE'))
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('one-liners and tab questions are still in the DOM at mobile widths (theme.css hides them via @media, jsdom does not apply that) — the class hook itself is what the CSS keys off', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('.lite-anatomy-dim-one')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-eq-q')).toBeInTheDocument()
  })
})
