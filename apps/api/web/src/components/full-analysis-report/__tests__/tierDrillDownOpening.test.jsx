/**
 * Opening the drill-down — the path from a click on a tier name to a
 * panel on the screen.
 *
 * Every test before this one rendered TierDrillDown directly, with the
 * tier handed to it. That is exactly the part that was never broken. The
 * reported failure was the wiring: on one cycle the catalog-accuracy
 * name did nothing, the request went out and came back with sixty-six
 * entries, no error reached the console, and the panel never appeared —
 * while the value tier's panel had opened in the same session minutes
 * earlier.
 *
 * So these mirror FullAnalysisReport.jsx's own wiring — the drillTier
 * state, `onDrillDown={readOnly ? undefined : setDrillTier}`, and the
 * conditional mount underneath the section — and click the name.
 */
import React, { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

vi.mock('../../../api.js', async () => {
  class AuthExpiredError extends Error {
    constructor() {
      super('Your session expired. Reloading to sign in again…')
      this.name = 'AuthExpiredError'
      this.authExpired = true
    }
  }
  return { api: { getTierOutcomes: vi.fn() }, AuthExpiredError }
})
import { api, AuthExpiredError } from '../../../api.js'
import { TierAccuracySection } from '../TierAccuracySection.jsx'
import { TierDrillDown } from '../TierDrillDown.jsx'

function outcome(i, overrides = {}) {
  return {
    run_id: i,
    query_code: `WS_A_${String(i).padStart(4, '0')}`,
    query_text: `Question ${i}`,
    tier: 'catalog_accuracy',
    platform: 'chatgpt',
    run_number: 1,
    outcome: 'exact',
    outcome_reason: 'stated 17.99',
    expected_answer: { type: 'price', amount: '17.99', currency: 'USD' },
    extraction: {}, secondary_results: [],
    source_attribution: 'brand_domain', domain_cited: true,
    record_published_at: '2026-09-04 20:49:38+00:00',
    matched_published_at: null,
    answer_excerpt: 'It costs $17.99.',
    ...overrides,
  }
}

// The reported cycle: sixty-six entries, two of them stale.
const SIXTY_SIX = [
  ...Array.from({ length: 64 }, (_, i) => outcome(i + 1)),
  outcome(65, {
    outcome: 'stale',
    outcome_reason: 'stated 15.99; we published that on 2026-08-21',
    matched_published_at: '2026-08-21 14:02:11.123456+00:00',
  }),
  outcome(66, {
    outcome: 'stale',
    outcome_reason: 'stated 15.99; we published that on 2026-07-02',
    matched_published_at: '2026-07-02 09:10:00.000000+00:00',
  }),
]

function tier(t, label, overrides = {}) {
  return {
    tier: t, label,
    counts: { exact: 64, stale: 2, wrong: 0, absent: 0, unscoreable: 0 },
    scored: 66, samples: 66, accuracy: 0.9697, staleness: 0.0303,
    wrong_rate: 0, answered_rate: 1, unscoreable_rate: 0,
    visibility: { runs: 66, mentioned: 50, rate: 0.7576 },
    source_attribution: { brand_domain: 10, retailer: 50, none: 6 },
    secondary: [], surfaces: [],
    ...overrides,
  }
}

const SECTION = {
  tiers: [
    tier('catalog_accuracy', 'Catalog accuracy'),
    tier('value_incentives', 'Value & incentives'),
  ],
  value_survival: 0.75, value_survival_samples: 8,
  study: { merchant: { brand: 'Wiggle & Snug' } },
}

/** FullAnalysisReport.jsx's wiring, and nothing else. */
function Host({ tierAccuracy = SECTION, readOnly = false }) {
  const [drillTier, setDrillTier] = useState(null)
  return (
    <>
      <TierAccuracySection
        tierAccuracy={tierAccuracy} open onToggle={() => {}}
        onDrillDown={readOnly ? undefined : setDrillTier}
      />
      {!readOnly && drillTier && (
        <TierDrillDown
          tier={drillTier} cycleCode="20260915-113207"
          onClose={() => setDrillTier(null)}
        />
      )}
    </>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  api.getTierOutcomes.mockResolvedValue({ outcomes: SIXTY_SIX })
})

describe('clicking a tier name', () => {
  it('opens the panel for catalog accuracy', async () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    expect(await screen.findByTestId('tier-drilldown')).toBeInTheDocument()
  })

  it('asks for that tier, not for all of them', async () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    await waitFor(() => expect(api.getTierOutcomes).toHaveBeenCalledWith(
      '20260915-113207', 'catalog_accuracy',
    ))
  })

  it('renders all sixty-six entries', async () => {
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    await waitFor(() =>
      expect(screen.getAllByTestId('outcome-entry')).toHaveLength(66))
  })

  it('opens catalog accuracy after value has already been opened', async () => {
    // The reported sequence. The panel is one mounted component whose
    // tier prop changes, so a second tier has to refetch and re-render
    // rather than keep the first one's rows.
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Value & incentives' }))
    await waitFor(() => expect(api.getTierOutcomes).toHaveBeenCalledWith(
      '20260915-113207', 'value_incentives',
    ))
    await screen.findByTestId('tier-drilldown')

    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    await waitFor(() => expect(api.getTierOutcomes).toHaveBeenLastCalledWith(
      '20260915-113207', 'catalog_accuracy',
    ))
    await waitFor(() =>
      expect(screen.getAllByTestId('outcome-entry')).toHaveLength(66))
  })

  it('scrolls the panel into view, since a panel below the fold reads as a dead click', async () => {
    const scroll = vi.fn()
    window.HTMLElement.prototype.scrollIntoView = scroll
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    await screen.findByTestId('tier-drilldown')
    expect(scroll).toHaveBeenCalled()
  })

  it('is not offered at all on the read-only share view', () => {
    render(<Host readOnly />)
    expect(screen.queryByRole('button', { name: 'Catalog accuracy' })).not.toBeInTheDocument()
    // The name is still there — it is a row label, not a control.
    const row = screen.getByTestId('tier-row-catalog_accuracy')
    expect(row).toHaveTextContent('Catalog accuracy')
  })
})

describe('a tier row that cannot be opened', () => {
  it('renders a name even when the tier has no label', () => {
    // TIER_LABELS.get(tier, tier) falls back to the key, but a tier of
    // None takes the fallback with it — and an empty button is a button
    // with nothing to click.
    render(<Host tierAccuracy={{ ...SECTION, tiers: [tier('catalog_accuracy', null)] }} />)
    const cell = screen.getByTestId('tier-row-catalog_accuracy')
    expect(cell).toHaveTextContent('catalog_accuracy')
  })

  it('does not offer a dead control for an untiered row', async () => {
    // A null tier cannot be drilled into: the endpoint filters on it and
    // setDrillTier(null) leaves the panel unmounted. Offering a button
    // that silently does nothing is the failure being fixed, so the row
    // states it instead.
    render(<Host tierAccuracy={{ ...SECTION, tiers: [tier(null, null)] }} />)
    expect(screen.queryByRole('button', { name: /^$/ })).not.toBeInTheDocument()
    expect(screen.getByText('Untiered')).toBeInTheDocument()
  })
})

describe('when the session has expired', () => {
  it('says so rather than vanishing', async () => {
    // api.js reloads the page on a 401. Before the reload lands there is
    // a moment with a mounted panel in it, and it used to spend that
    // moment blank: the 401 resolved to undefined, `data.outcomes` threw
    // inside .then, and the reload wiped the console on its way out.
    api.getTierOutcomes.mockRejectedValue(new AuthExpiredError())
    render(<Host />)
    fireEvent.click(screen.getByRole('button', { name: 'Catalog accuracy' }))
    expect(await screen.findByTestId('drilldown-error'))
      .toHaveTextContent('session expired')
  })
})
