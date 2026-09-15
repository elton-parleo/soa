/**
 * The drill-down had no tests at all, which is how it shipped able to go
 * unresponsive on a real cycle: the catalog-accuracy tier's panel did
 * nothing on click while the value tier's opened, and the only record of
 * why was a console entry nobody was watching.
 *
 * So these cover two different things. The first is the data — a stale
 * outcome, which is what catalog accuracy had two of and value had none,
 * rendered from a fixture shaped the way per_question_outcomes returns
 * it. The second is the failure: whatever throws, the panel has to say
 * so, and it has to keep rendering the entries that did not throw.
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

vi.mock('../../../api.js', () => ({ api: { getTierOutcomes: vi.fn() } }))
import { api } from '../../../api.js'
import { TierDrillDown, describeExpectation } from '../TierDrillDown.jsx'

// Shaped exactly as app/services/tier_accuracy.py::per_question_outcomes
// returns a row: JSON columns parsed, timestamps stringified by _iso,
// answer truncated by _excerpt.
function row(overrides = {}) {
  return {
    run_id: 101,
    query_code: 'WS_A_0007',
    query_text: 'What does the Wiggle & Snug Snug-Fit Diapers Size 3 small pack cost?',
    tier: 'catalog_accuracy',
    platform: 'chatgpt',
    run_number: 1,
    outcome: 'exact',
    outcome_reason: 'stated 17.99',
    expected_answer: {
      type: 'price', amount: '17.99', currency: 'USD',
      secondary: [{ type: 'pack_count', value: 96 }],
    },
    extraction: { prices: ['17.99'], extraction_confident: true },
    secondary_results: [{ type: 'pack_count', outcome: 'exact' }],
    source_attribution: 'brand_domain',
    domain_cited: true,
    record_published_at: '2026-09-04 20:49:38.763754+00:00',
    matched_published_at: null,
    answer_excerpt: 'The Size 3 small pack is $17.99.',
    ...overrides,
  }
}

// The two that catalog accuracy had and value did not.
const STALE = row({
  run_id: 202,
  outcome: 'stale',
  outcome_reason:
    'stated 15.99; we published that on 2026-08-21 14:02:11.123456+00:00',
  matched_published_at: '2026-08-21 14:02:11.123456+00:00',
  answer_excerpt: 'It is $15.99 for the Size 3 small pack.',
})

function mount(outcomes, props = {}) {
  api.getTierOutcomes.mockResolvedValue({ outcomes })
  return render(
    <TierDrillDown
      tier="catalog_accuracy" cycleCode="C80512"
      onClose={() => {}} {...props}
    />,
  )
}

beforeEach(() => vi.clearAllMocks())

// ─── The fixture that reproduces the reported cycle ───────────────────────

describe('a tier with stale outcomes in it', () => {
  it('renders the stale entry rather than failing', async () => {
    mount([row(), STALE])
    await waitFor(() => expect(screen.getAllByTestId('outcome-entry')).toHaveLength(2))
    expect(
      screen.getAllByTestId('outcome-entry').map((e) => e.dataset.outcome),
    ).toEqual(['exact', 'stale'])
  })

  it('says which publication the stale value matched', async () => {
    mount([STALE])
    expect(await screen.findByText(/published 2026-08-21/)).toBeInTheDocument()
  })

  it('renders a stale entry whose matched publish date arrives as a Date', async () => {
    // The field is a timestamptz; whether it reaches the browser as a
    // string depends on a cast in the service, and the panel should not.
    mount([row({ outcome: 'stale', matched_published_at: new Date('2026-08-21T14:02:11Z') })])
    expect(await screen.findByText(/published 2026-08-21/)).toBeInTheDocument()
  })

  it('renders a stale entry with no matched publish date at all', async () => {
    mount([row({ outcome: 'stale', matched_published_at: null })])
    await waitFor(() => expect(screen.getAllByTestId('outcome-entry')).toHaveLength(1))
    expect(screen.queryByText(/published /)).not.toBeInTheDocument()
  })

  it('still renders when the expectation is missing or unrecognised', async () => {
    mount([
      row({ run_id: 1, expected_answer: null }),
      row({ run_id: 2, expected_answer: { type: 'list_price', amount: '3' } }),
    ])
    await waitFor(() => expect(screen.getAllByTestId('outcome-entry')).toHaveLength(2))
  })
})

describe('describeExpectation', () => {
  it('never returns something React cannot render', () => {
    const cases = [
      null, undefined, 'a string', 42,
      { type: 'price', amount: '17.99', currency: 'USD' },
      { type: 'price', amount: { value: '17.99' }, currency: 'USD' },
      { type: 'points', rule: { kind: 'per_dollar', rate: 2 } },
      { type: 'points', rule: null },
      { type: 'brand_mention', brand: 'Wiggle & Snug' },
      { amount: '17.99' },
      [{ type: 'price' }],
    ]
    for (const input of cases) {
      const out = describeExpectation(input)
      expect(['string', 'undefined', 'object'].includes(typeof out)).toBe(true)
      if (out !== null && out !== undefined) expect(typeof out).toBe('string')
    }
  })
})

// ─── A dead click must be impossible ──────────────────────────────────────

describe('when something throws while rendering', () => {
  let spy
  beforeEach(() => { spy = vi.spyOn(console, 'error').mockImplementation(() => {}) })
  afterEach(() => spy.mockRestore())

  // A row that cannot be rendered by any amount of defensiveness: the
  // getter itself throws. It stands in for whatever the next unrenderable
  // shape turns out to be.
  function poisoned(id) {
    const bad = row({ run_id: id })
    Object.defineProperty(bad, 'query_text', {
      get() { throw new Error('bad row') },
      enumerable: true,
    })
    return bad
  }

  it('says how many entries it could not render, and why', async () => {
    mount([row({ run_id: 1 }), poisoned(2)])
    const note = await screen.findByTestId('drilldown-render-failures')
    expect(note).toHaveTextContent("Couldn't render 1 entry: bad row")
  })

  it('counts more than one failure in the same line', async () => {
    mount([row({ run_id: 1 }), poisoned(2), poisoned(3)])
    expect(await screen.findByTestId('drilldown-render-failures'))
      .toHaveTextContent("Couldn't render 2 entries: bad row")
  })

  it('keeps the entries that did render — one bad row costs one row', async () => {
    mount([row({ run_id: 1 }), poisoned(2), row({ run_id: 3 })])
    await screen.findByTestId('drilldown-render-failures')
    expect(screen.getAllByTestId('outcome-entry')).toHaveLength(2)
  })

  it('never leaves the panel empty and silent', async () => {
    mount([poisoned(1)])
    await screen.findByTestId('drilldown-render-failures')
    expect(screen.getByTestId('tier-drilldown')).toBeInTheDocument()
  })
})

describe('when the outcomes cannot be loaded', () => {
  it('says so instead of loading forever', async () => {
    api.getTierOutcomes.mockRejectedValue(new Error('GET /api/... → 500'))
    render(<TierDrillDown tier="catalog_accuracy" cycleCode="C80512" onClose={() => {}} />)
    expect(await screen.findByTestId('drilldown-error')).toHaveTextContent('500')
  })

  it('says so even when what was thrown is not an Error', async () => {
    api.getTierOutcomes.mockRejectedValue('boom')
    render(<TierDrillDown tier="catalog_accuracy" cycleCode="C80512" onClose={() => {}} />)
    expect(await screen.findByTestId('drilldown-error')).toHaveTextContent('boom')
  })

  it('does not sit on Loading when the response has no outcomes key', async () => {
    // What a 401 resolves to, among other things.
    api.getTierOutcomes.mockResolvedValue(undefined)
    render(<TierDrillDown tier="catalog_accuracy" cycleCode="C80512" onClose={() => {}} />)
    expect(await screen.findByText('Nothing scored in this tier.')).toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })
})

// ─── Filters ──────────────────────────────────────────────────────────────

describe('the outcome filters', () => {
  const MIXED = [
    row({ run_id: 1, outcome: 'exact' }),
    row({ run_id: 2, outcome: 'exact' }),
    STALE,
    row({ run_id: 4, outcome: 'wrong', outcome_reason: 'stated 21.00' }),
    row({ run_id: 5, outcome: 'absent', outcome_reason: 'no price stated' }),
    row({ run_id: 6, outcome: 'unscoreable', outcome_reason: 'run status error' }),
  ]

  it('offers all five outcomes plus all', async () => {
    mount(MIXED)
    await screen.findByTestId('outcome-filters')
    for (const key of ['all', 'exact', 'stale', 'wrong', 'absent', 'unscoreable']) {
      expect(screen.getByTestId(`outcome-filter-${key}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('outcome-filter-absent')).toHaveTextContent('Not addressed')
    expect(screen.getByTestId('outcome-filter-unscoreable')).toHaveTextContent('Unreadable')
  })

  it('counts each outcome on its chip', async () => {
    mount(MIXED)
    await screen.findByTestId('outcome-filters')
    expect(screen.getByTestId('outcome-filter-all')).toHaveTextContent('All 6')
    expect(screen.getByTestId('outcome-filter-exact')).toHaveTextContent('Exact 2')
    expect(screen.getByTestId('outcome-filter-stale')).toHaveTextContent('Stale 1')
  })

  it('narrows the list to one outcome', async () => {
    mount(MIXED)
    fireEvent.click(await screen.findByTestId('outcome-filter-exact'))
    expect(
      screen.getAllByTestId('outcome-entry').map((e) => e.dataset.outcome),
    ).toEqual(['exact', 'exact'])
  })

  it('clicking the active chip again goes back to all', async () => {
    mount(MIXED)
    const exact = await screen.findByTestId('outcome-filter-exact')
    fireEvent.click(exact)
    expect(exact).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(exact)
    expect(screen.getAllByTestId('outcome-entry')).toHaveLength(6)
  })

  it('shows an outcome with none as a zero rather than hiding it', async () => {
    // "This tier has no stale outcomes" is a finding. An absent chip
    // would leave the reader to infer it from a gap.
    mount([row({ outcome: 'exact' })])
    const stale = await screen.findByTestId('outcome-filter-stale')
    expect(stale).toHaveTextContent('Stale 0')
    expect(stale).toBeDisabled()
  })

  it('does not offer filters when there is nothing to filter', async () => {
    mount([])
    await screen.findByText('Nothing scored in this tier.')
    expect(screen.queryByTestId('outcome-filters')).not.toBeInTheDocument()
  })

  it('resets to all when the tier changes', async () => {
    const { rerender } = mount(MIXED)
    fireEvent.click(await screen.findByTestId('outcome-filter-exact'))
    api.getTierOutcomes.mockResolvedValue({ outcomes: MIXED })
    rerender(
      <TierDrillDown tier="value_incentives" cycleCode="C80512" onClose={() => {}} />,
    )
    await waitFor(() =>
      expect(screen.getByTestId('outcome-filter-all')).toHaveAttribute('aria-pressed', 'true'))
  })
})
