import React from 'react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import { AnatomyOfAnAnswer } from '../landing/AnatomyOfAnAnswer.jsx'
import {
  DIMENSIONS,
  DIMENSIONS_BY_CODE,
  PILLAR_NAMES,
  PILLAR_ORDER,
  PILLAR_WEIGHTS,
  SCORER_VERSION,
} from '../landing/scanDimensionsRegistry.js'

function contrastRatio(hex1, hex2) {
  const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  const lum = (hex) => {
    const n = parseInt(hex.replace('#', ''), 16)
    return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255)
  }
  const [l1, l2] = [lum(hex1), lum(hex2)].sort((a, b) => b - a)
  return (l1 + 0.05) / (l2 + 0.05)
}

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT_SRC = fs.readFileSync(
  path.join(__dirname, '../landing/AnatomyOfAnAnswer.jsx'), 'utf8',
)
const THEME_CSS = fs.readFileSync(path.join(__dirname, '../theme.css'), 'utf8')

// ─── P0 gate: registry totals (enforced in CI) ───────────────────────────

describe('AnatomyOfAnAnswer — P0 registry gate', () => {
  it('registry is scorer_version 3 with pillar weights summing to 40/20/40', () => {
    expect(SCORER_VERSION).toBe('3')
    expect(PILLAR_ORDER).toEqual(['visibility', 'accessibility', 'true_value'])
    expect(PILLAR_WEIGHTS.visibility).toBe(40)
    expect(PILLAR_WEIGHTS.accessibility).toBe(20)
    expect(PILLAR_WEIGHTS.true_value).toBe(40)
  })

  it('renders a hidden scorer-version marker matching the registry', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('[data-scorer-version]').getAttribute('data-scorer-version')).toBe('3')
  })
})

// ─── Registry-drivenness ──────────────────────────────────────────────

describe('AnatomyOfAnAnswer — registry-drivenness', () => {
  it('component source contains no dimension-name literals', () => {
    for (const dim of DIMENSIONS) {
      expect(COMPONENT_SRC).not.toContain(`'${dim.name}'`)
      expect(COMPONENT_SRC).not.toContain(`"${dim.name}"`)
      expect(COMPONENT_SRC).not.toContain(`>${dim.name}<`)
    }
  })

  it('component source contains no hard-coded point-value flag literals', () => {
    // The exact composed strings a hand-typed flag would produce
    // (V·25, TV·19, "19 pts", etc.) — these must only ever appear as
    // template-literal expressions reading DIM[code].weight, never as
    // source text, so none of these literal substrings may appear.
    for (const dim of DIMENSIONS) {
      expect(COMPONENT_SRC).not.toContain(`V·${dim.weight}`)
      expect(COMPONENT_SRC).not.toContain(`TV·${dim.weight}`)
      expect(COMPONENT_SRC).not.toContain(`${dim.weight} pts`)
      if (dim.seenMax !== null) expect(COMPONENT_SRC).not.toContain(`SEEN ${dim.seenMax}`)
      if (dim.saidMax !== null) expect(COMPONENT_SRC).not.toContain(`SAID ${dim.saidMax}`)
    }
  })

  it('perturbing a registry weight moves the rendered ledger flag', () => {
    const original = DIMENSIONS_BY_CODE.member_value.weight
    DIMENSIONS_BY_CODE.member_value.weight = 41
    try {
      render(<AnatomyOfAnAnswer />)
      expect(screen.getByText('41 pts')).toBeInTheDocument()
      expect(screen.queryByText(`${original} pts`)).not.toBeInTheDocument()
    } finally {
      DIMENSIONS_BY_CODE.member_value.weight = original
    }
  })

  it('perturbing a seen/said split moves the rendered SEEN/SAID line', () => {
    const dim = DIMENSIONS_BY_CODE.deal_citability
    const [origSeen, origSaid] = [dim.seenMax, dim.saidMax]
    dim.seenMax = 99
    dim.saidMax = 98
    try {
      render(<AnatomyOfAnAnswer />)
      fireEvent.click(screen.getByText(dim.name).closest('button'))
      expect(screen.getByText('SEEN 99 · SAID 98')).toBeInTheDocument()
    } finally {
      dim.seenMax = origSeen
      dim.saidMax = origSaid
    }
  })
})

// ─── Removal: old section fully gone ──────────────────────────────────

describe('AnatomyOfAnAnswer — old section removed', () => {
  it('component source contains none of the retired strings', () => {
    for (const banned of [
      'SCORE CAP', 'Score cap', 'Foundation ·', 'Foundation 35', 'Agents are already', 'Transaction Rails',
      'ANATOMY OF AN ANSWER', '12 SHOPPER QUERIES · CHATGPT',
    ]) {
      expect(COMPONENT_SRC).not.toContain(banned)
    }
  })

  it('rendered output contains none of the retired strings', () => {
    render(<AnatomyOfAnAnswer />)
    const rendered = document.body.textContent
    for (const banned of [
      'SCORE CAP', 'Score cap', 'Foundation', 'Agents are already', 'Transaction Rails',
      'ANATOMY OF AN ANSWER', '12 SHOPPER QUERIES · CHATGPT',
    ]) {
      expect(rendered).not.toContain(banned)
    }
  })

  it('preserves the #methodology anchor id for existing nav/deep links', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('#methodology')).toBeInTheDocument()
  })
})

// ─── Stage 18: eyebrow label, seam label, truth-rule stamp ───────────

describe('AnatomyOfAnAnswer — eyebrow and seam labels (Changes 3/4)', () => {
  it('renders the METHODOLOGY eyebrow, not the old label', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText('METHODOLOGY')).toBeInTheDocument()
    expect(screen.queryByText('ANATOMY OF AN ANSWER')).not.toBeInTheDocument()
  })

  it('the seam reads "SHOPPER QUERIES" with no platform/count mention', () => {
    render(<AnatomyOfAnAnswer />)
    expect(screen.getByText(/SHOPPER QUERIES/)).toBeInTheDocument()
    expect(screen.queryByText(/12 SHOPPER QUERIES/)).not.toBeInTheDocument()
    expect(screen.queryByText(/CHATGPT/, { selector: '.lite-anatomy-seam' })).not.toBeInTheDocument()
  })

  it('the closing stamp still carries the platform/query-count scoping (truth-rule guard)', () => {
    render(<AnatomyOfAnAnswer />)
    // Pinned exactly: if the seam's platform mention is ever dropped
    // further, this is the one remaining place the claim is scoped —
    // it must not silently disappear too.
    expect(screen.getByText('12 queries · 1 platform · deterministic · sample, not a category study.'))
      .toBeInTheDocument()
  })
})

// ─── Change 1: grouped ledger (three pillar cards) ────────────────────

describe('AnatomyOfAnAnswer — grouped ledger', () => {
  it('renders exactly three pillar cards, in registry pillar order', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const cards = container.querySelectorAll('.lite-anatomy-pillar-card')
    expect(cards).toHaveLength(3)

    const headerNames = Array.from(cards).map(
      (card) => card.querySelector('.lite-anatomy-pillar-header span').textContent,
    )
    expect(headerNames).toEqual(PILLAR_ORDER.map((p) => PILLAR_NAMES[p]))
  })

  it('each pillar card contains exactly its own dimensions, in registry order', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const cards = container.querySelectorAll('.lite-anatomy-pillar-card')

    for (const pillar of PILLAR_ORDER) {
      const expectedCodes = DIMENSIONS.filter((d) => d.pillar === pillar).map((d) => d.code)
      const card = Array.from(cards).find(
        (c) => c.querySelector('.lite-anatomy-pillar-header span').textContent === PILLAR_NAMES[pillar],
      )
      const rowNames = Array.from(card.querySelectorAll('.lite-anatomy-ledger-row-head span:first-child'))
        .map((el) => el.textContent)
      expect(rowNames).toEqual(expectedCodes.map((c) => DIMENSIONS_BY_CODE[c].name))
    }
  })

  it('a pillar header total is the live sum of its members\' weights (perturbation test)', () => {
    const original = DIMENSIONS_BY_CODE.deal_citability.weight
    DIMENSIONS_BY_CODE.deal_citability.weight = 20
    try {
      const { container } = render(<AnatomyOfAnAnswer />)
      const trueValueCard = container.querySelector('.lite-anatomy-pillar-card--tv')
      const total = trueValueCard.querySelector('.lite-anatomy-pillar-header span:last-child').textContent
      // price_truth(14) + member_value(19) + perturbed deal_citability(20) = 53
      expect(total).toBe('53')
    } finally {
      DIMENSIONS_BY_CODE.deal_citability.weight = original
    }
  })
})

// ─── Change 2: True Value card goes blue ──────────────────────────────

describe('AnatomyOfAnAnswer — True Value card color (Change 2)', () => {
  it('the True Value card carries the blue-card modifier class, others do not', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const cards = container.querySelectorAll('.lite-anatomy-pillar-card')
    const tvCards = container.querySelectorAll('.lite-anatomy-pillar-card--tv')
    expect(tvCards).toHaveLength(1)
    expect(cards).toHaveLength(3)
    expect(tvCards[0].querySelector('.lite-anatomy-pillar-header span').textContent).toBe('True Value')
  })

  it('the floating tag inverts to a white pill inside the blue card', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const tag = container.querySelector('.lite-anatomy-pillar-card--tv .lite-anatomy-float-tag')
    expect(tag).toBeInTheDocument()
    expect(tag).toHaveTextContent('ONLY WE SCORE THIS')
    // Only ONE tag exists, and it lives inside the blue card (not a
    // separately-styled accent-on-accent tag anywhere else).
    expect(container.querySelectorAll('.lite-anatomy-float-tag')).toHaveLength(1)
  })

  it('white text on the accent blue card clears AA with margin', () => {
    // #2E69FA is the real --accent token value (theme.css) — already
    // darkened ~1% from the nominal #2F6BFF specifically so white text
    // clears AA (see --accent's own definition comment). White is
    // still the ceiling for contrast against it: verified here so a
    // future palette change that lightens --accent back toward
    // #2F6BFF gets caught if it drops this below AA.
    const ratio = contrastRatio('#FFFFFF', '#2E69FA')
    expect(ratio).toBeGreaterThanOrEqual(4.5)
    expect(ratio).toBeGreaterThan(4.6) // documents the real margin, not just a bare pass
  })

  it('no tint darker than white is used for text on the blue card (none would clear AA)', () => {
    // Any color between white and the background has strictly lower
    // contrast than white itself, so the blue card's CSS rules must
    // not reference the ink-card's secondary-text token (--text-inv-2,
    // a gray) — that combination measures well under AA on this
    // background. Scoped to the .lite-anatomy-pillar-card--tv rule
    // block specifically (theme.css uses --text-inv-2 elsewhere, e.g.
    // the True Value marks in the ink answer bubble, which is fine).
    const tvRules = THEME_CSS.split(/(?=\.lite-anatomy-pillar-card--tv)/).filter((r) => r.startsWith('.lite-anatomy-pillar-card--tv'))
    for (const rule of tvRules) {
      expect(rule).not.toContain('text-inv-2')
    }
    expect(tvRules.length).toBeGreaterThan(0)
  })
})

// ─── JSON-LD excerpt: valid + allowlisted schema.org vocabulary ──────

const JSONLD_KEY_ALLOWLIST = new Set([
  '@context', '@type', 'name', 'gtin13', 'brand',
  'offers', 'price', 'priceCurrency', 'availability', 'priceValidUntil',
  'priceSpecification', 'membershipPointsEarned',
])

function collectKeys(node, out) {
  if (Array.isArray(node)) { node.forEach((n) => collectKeys(n, out)); return }
  if (node && typeof node === 'object') {
    for (const [k, v] of Object.entries(node)) { out.add(k); collectKeys(v, out) }
  }
}

describe('AnatomyOfAnAnswer — JSON-LD excerpt', () => {
  it('parses as valid JSON and uses only allowlisted schema.org keys', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    const panel = container.querySelector('.lite-anatomy-code-panel')
    const text = Array.from(panel.querySelectorAll('.lite-anatomy-code-line'))
      .map((el) => el.textContent)
      .join('\n')

    const parsed = JSON.parse(text)
    expect(parsed['@type']).toBe('Product')

    const keys = new Set()
    collectKeys(parsed, keys)
    for (const key of keys) {
      expect(JSONLD_KEY_ALLOWLIST.has(key), `unexpected key "${key}" in JSON-LD excerpt`).toBe(true)
    }
  })

  it('does not use the mock\'s invented "validForMemberTier" field', () => {
    render(<AnatomyOfAnAnswer />)
    expect(document.body.textContent).not.toContain('validForMemberTier')
  })
})

// ─── Activation model (I1/I2/I3) ──────────────────────────────────────

const ACTIVATABLE_CASES = [
  { code: 'share_of_mentions', otherText: 'Allbirds Wool Runners' },
  { code: 'recommendation_strength', otherText: 'a top pick' },
  { code: 'agent_access', otherText: 'robots ✓' },
  { code: 'catalog_context', otherText: '"name": "Wool Runner",' },
  { code: 'protocol_feed', otherText: 'llms.txt ✓' },
  { code: 'price_truth', otherText: 'listed at $98' },
  { code: 'member_value', otherText: 'Members save $10 and earn reward points on this pair' },
  { code: 'deal_citability', otherText: 'a seasonal discount is currently running on select colors' },
]

describe('AnatomyOfAnAnswer — activation model', () => {
  it('defaults to Member Value active on mount (I2)', () => {
    render(<AnatomyOfAnAnswer />)
    const row = screen.getByText(DIMENSIONS_BY_CODE.member_value.name).closest('button')
    expect(row).toHaveClass('lite-anatomy-ledger-row--active')
    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(DIMENSIONS_BY_CODE.member_value.name).closest('button'))
      .toHaveTextContent(/SEEN .* SAID/)
  })

  it.each(ACTIVATABLE_CASES)('clicking the $code ledger row activates its other element and opens exactly one description', ({ code, otherText }) => {
    render(<AnatomyOfAnAnswer />)
    const dim = DIMENSIONS_BY_CODE[code]
    const row = screen.getByText(dim.name).closest('button')

    fireEvent.click(row)

    expect(row).toHaveClass('lite-anatomy-ledger-row--active')
    expect(row).toHaveAttribute('aria-expanded', 'true')

    const other = screen.getByText(otherText).closest('button, span')
    expect(other).toHaveAttribute('aria-pressed', 'true')

    // Exactly one ledger row's description is open.
    const openDescriptions = screen.getAllByText(/./).filter(
      (el) => el.className === 'lite-anatomy-ledger-desc',
    )
    expect(openDescriptions).toHaveLength(1)
  })

  it('opening a second dimension closes the first (accordion, one open at a time)', () => {
    render(<AnatomyOfAnAnswer />)
    fireEvent.click(screen.getByText(DIMENSIONS_BY_CODE.price_truth.name).closest('button'))
    expect(screen.getByText(DIMENSIONS_BY_CODE.price_truth.name).closest('button'))
      .toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(screen.getByText(DIMENSIONS_BY_CODE.agent_access.name).closest('button'))
    expect(screen.getByText(DIMENSIONS_BY_CODE.agent_access.name).closest('button'))
      .toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText(DIMENSIONS_BY_CODE.price_truth.name).closest('button'))
      .toHaveAttribute('aria-expanded', 'false')
  })

  it('the ghost sentence activates all three True Value dimensions together', () => {
    render(<AnatomyOfAnAnswer />)
    fireEvent.click(screen.getByText('…the sentence most stores never get'))

    for (const code of ['price_truth', 'member_value', 'deal_citability']) {
      const row = screen.getByText(DIMENSIONS_BY_CODE[code].name).closest('button')
      expect(row).toHaveClass('lite-anatomy-ledger-row--active')
    }
    expect(screen.getByText('listed at $98').closest('button')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('a seasonal discount is currently running on select colors').closest('button'))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('…the sentence most stores never get').closest('button'))
      .toHaveClass('lite-anatomy-ghost--active')
  })

  it('marks are real buttons, keyboard-operable by native HTML semantics', () => {
    render(<AnatomyOfAnAnswer />)
    const mark = screen.getByText('listed at $98').closest('button')
    expect(mark.tagName).toBe('BUTTON')
    expect(mark).toHaveAttribute('type', 'button')
  })

  it('chrome badges (custom keyboard handling) activate on Enter and Space', () => {
    render(<AnatomyOfAnAnswer />)
    const badge = screen.getByText('llms.txt ✓')

    fireEvent.keyDown(badge, { key: 'Enter' })
    expect(badge).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByText(DIMENSIONS_BY_CODE.agent_access.name).closest('button')) // switch away
    expect(badge).toHaveAttribute('aria-pressed', 'false')

    fireEvent.keyDown(badge, { key: ' ' })
    expect(badge).toHaveAttribute('aria-pressed', 'true')
  })

  it('ledger rows expose aria-expanded for every row', () => {
    render(<AnatomyOfAnAnswer />)
    for (const dim of DIMENSIONS) {
      const row = screen.getByText(dim.name).closest('button')
      expect(row).toHaveAttribute('aria-expanded')
    }
  })
})

// ─── Responsive (360 / 768 / 1280) ────────────────────────────────────
// jsdom does not evaluate CSS media queries, so these assert the class
// hooks theme.css's actual @media rules key off of are present, rather
// than computed layout.

describe('AnatomyOfAnAnswer — responsive structure', () => {
  afterEach(() => { window.innerWidth = 1024 })

  it.each([360, 768, 1280])('renders the full walkthrough at %ipx without crashing', (width) => {
    window.innerWidth = width
    const { container } = render(<AnatomyOfAnAnswer />)
    expect(container.querySelector('.lite-anatomy-grid')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-code-panel')).toBeInTheDocument()
    expect(container.querySelector('.lite-anatomy-ledger')).toBeInTheDocument()
  })

  it('the grid collapses to one column under 860px (mobile stacking hook)', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    // .lite-anatomy-grid carries the @media (max-width: 860px) rule in
    // theme.css that collapses grid-template-columns to 1fr.
    expect(container.querySelector('.lite-anatomy-grid')).toBeInTheDocument()
  })

  it('the ledger is only sticky at >=768px (non-sticky-on-mobile hook)', () => {
    const { container } = render(<AnatomyOfAnAnswer />)
    // .lite-anatomy-ledger only gets position:sticky inside an
    // @media (min-width: 768px) block — no inline/base sticky style.
    const ledger = container.querySelector('.lite-anatomy-ledger')
    expect(ledger.style.position).not.toBe('sticky')
  })
})
