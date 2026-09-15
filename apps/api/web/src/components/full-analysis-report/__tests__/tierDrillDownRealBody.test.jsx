/**
 * The drill-down against the body the endpoint actually returned for the
 * cycle that failed: 20260915-113207-wiggle-snug-full, brand_direct, 66
 * populated entries.
 *
 * The fixture is that response, reconstructed field for field from the
 * captured body, with the long answer excerpts trimmed — the excerpts are
 * evidence for the scoring work, not for the renderer, and the renderer
 * has no length-dependent behaviour.
 */
import React, { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

vi.mock('../../../api.js', () => ({ api: { getTierOutcomes: vi.fn() } }))
import { api } from '../../../api.js'
import { TierAccuracySection } from '../TierAccuracySection.jsx'
import { TierDrillDown } from '../TierDrillDown.jsx'
import BODY from '../../../../../../pipeline/tests/fixtures/wiggle_and_snug_brand_direct_outcomes.json'

const SECTION = {
  tiers: [{
    tier: 'brand_direct', label: 'Brand-direct',
    counts: { exact: 63, stale: 0, wrong: 0, absent: 3, unscoreable: 0 },
    scored: 63, samples: 66, accuracy: 1, staleness: 0, wrong_rate: 0,
    answered_rate: 0.9545, unscoreable_rate: 0,
    visibility: { runs: 66, mentioned: 63, rate: 0.9545 },
    source_attribution: { brand_domain: 2, retailer: 37, none: 27 },
    secondary: [], surfaces: [],
  }],
  value_survival: null, value_survival_samples: 0,
  study: { merchant: { brand: 'Wiggle & Snug' } },
}

function Host() {
  const [drillTier, setDrillTier] = useState(null)
  return (
    <>
      <TierAccuracySection
        tierAccuracy={SECTION} open onToggle={() => {}} onDrillDown={setDrillTier}
      />
      {drillTier && (
        <TierDrillDown
          tier={drillTier} cycleCode={BODY.cycle_code}
          onClose={() => setDrillTier(null)}
        />
      )}
    </>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getTierOutcomes.mockResolvedValue(BODY)
})

describe('the body from the cycle that failed', () => {
  it('has the shape the report said it had', () => {
    expect(BODY.outcomes).toHaveLength(66)
    expect(BODY.outcomes.every((o) => o.run_id && o.query_text)).toBe(true)
    expect(new Set(BODY.outcomes.map((o) => o.run_id)).size).toBe(66)
  })

  it('opens and renders every one of the sixty-six entries', async () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Brand-direct' }))
    await waitFor(() =>
      expect(screen.getAllByTestId('outcome-entry')).toHaveLength(66))
    expect(screen.queryByTestId('drilldown-render-failures')).not.toBeInTheDocument()
  })

  it('renders the rows whose extraction carries nulls and nested objects', async () => {
    // run 10813 has a pack_count of {value: null}; 10830 has two points
    // entries and a member_price with a null amount; every row has
    // secondary_results: null rather than [].
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Brand-direct' }))
    await screen.findByTestId('tier-drilldown')
    expect(BODY.outcomes.every((o) => o.secondary_results === null)).toBe(true)
    expect(screen.queryByTestId('drilldown-render-failures')).not.toBeInTheDocument()
  })

  it('describes the brand_mention expectation every row carries', async () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Brand-direct' }))
    expect(await screen.findAllByText(/brand named, trueshopstore.com cited/))
      .toHaveLength(66)
  })

  it('filters sixty-six entries down to the three that never named the brand', async () => {
    // The reason the filters exist: 66 with no filter is already too many.
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Brand-direct' }))
    fireEvent.click(await screen.findByTestId('outcome-filter-absent'))
    expect(screen.getAllByTestId('outcome-entry')).toHaveLength(3)
    expect(screen.getByTestId('outcome-filter-absent')).toHaveTextContent('Not addressed 3')
  })

  it('offers the brand vocabulary and still the outcomes these rows carry', async () => {
    // This cycle was scored on presence, so every row says `exact` or
    // `absent`. The brand chips are what it will say once it is
    // re-scored; `exact` is kept alongside because 63 rows have it and
    // chips that all read zero would leave nothing filterable.
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Brand-direct' }))
    await screen.findByTestId('outcome-filters')
    for (const key of ['grounded', 'echoed', 'misattributed', 'fabricated',
                       'acknowledged_unknown']) {
      expect(screen.getByTestId(`outcome-filter-${key}`)).toHaveTextContent('0')
    }
    expect(screen.getByTestId('outcome-filter-exact')).toHaveTextContent('Exact 63')
  })
})
