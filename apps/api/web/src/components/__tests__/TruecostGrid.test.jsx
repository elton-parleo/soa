import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { TruecostGrid } from '../MetricsDashboard.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getCycleTruecostSnapshots: vi.fn(),
  },
}))

describe('TruecostGrid', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the "Run Sweep Now" action for a Planned cycle with no snapshots yet', async () => {
    api.getCycleTruecostSnapshots.mockResolvedValue({ cycle_id: 1, cycle_code: 'tc-1', skus: [] })

    render(
      <TruecostGrid
        cycleCode="tc-1"
        cycleData={{ status: 'planned' }}
        onRunSweep={() => {}}
        running={false}
      />
    )

    await waitFor(() => expect(screen.getByText('Sweep not started yet')).toBeInTheDocument())
    expect(screen.getByText('▶ Run Sweep Now')).toBeInTheDocument()
  })

  it('renders captured rows with listed_price, true_cost, and savings', async () => {
    api.getCycleTruecostSnapshots.mockResolvedValue({
      cycle_id: 1,
      cycle_code: 'tc-1',
      skus: [
        {
          scope_sku_id: 10,
          merchant_slug: 'sephora',
          display_name: 'NARS Serum',
          tiers: [
            {
              user_tier_name: null,
              listed_price: 100.0,
              true_cost: 90.0,
              total_savings: 10.0,
              applied_deals: [{ title: '10% off' }],
              status: 'captured',
              price_was_refreshed: true,
            },
          ],
          member_vs_baseline_delta: {},
        },
      ],
    })

    render(
      <TruecostGrid
        cycleCode="tc-1"
        cycleData={{ status: 'complete' }}
        onRunSweep={() => {}}
        running={false}
      />
    )

    await waitFor(() => expect(screen.getByText('NARS Serum')).toBeInTheDocument())
    expect(screen.getByText('sephora')).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
    expect(screen.getByText('$90.00')).toBeInTheDocument()
    expect(screen.getByText('$10.00 ⓘ')).toBeInTheDocument()
  })

  it('flags ground_truth_unavailable rows visibly instead of hiding them', async () => {
    api.getCycleTruecostSnapshots.mockResolvedValue({
      cycle_id: 1,
      cycle_code: 'tc-1',
      skus: [
        {
          scope_sku_id: 11,
          merchant_slug: 'target',
          display_name: 'Pampers Pack',
          tiers: [
            {
              user_tier_name: null,
              status: 'ground_truth_unavailable',
              error_message: 'Deal Engine timeout',
            },
          ],
          member_vs_baseline_delta: {},
        },
      ],
    })

    render(
      <TruecostGrid
        cycleCode="tc-1"
        cycleData={{ status: 'complete' }}
        onRunSweep={() => {}}
        running={false}
      />
    )

    await waitFor(() => expect(screen.getByText('Pampers Pack')).toBeInTheDocument())
    expect(screen.getByText('⚠ Unavailable')).toBeInTheDocument()
  })

  it('renders the baseline-only (no-deal) state with savings of $0.00 and no spurious delta column', async () => {
    api.getCycleTruecostSnapshots.mockResolvedValue({
      cycle_id: 1,
      cycle_code: 'tc-1',
      skus: [
        {
          scope_sku_id: 12,
          merchant_slug: 'walmart',
          display_name: 'Basic Widget',
          tiers: [
            {
              user_tier_name: null,
              listed_price: 25.0,
              true_cost: 25.0,
              total_savings: 0,
              applied_deals: [],
              status: 'captured',
            },
          ],
          member_vs_baseline_delta: {},
        },
      ],
    })

    render(
      <TruecostGrid
        cycleCode="tc-1"
        cycleData={{ status: 'complete' }}
        onRunSweep={() => {}}
        running={false}
      />
    )

    await waitFor(() => expect(screen.getByText('Basic Widget')).toBeInTheDocument())
    expect(screen.queryByText('Δ vs baseline')).not.toBeInTheDocument()
    expect(screen.getAllByText('$25.00')).toHaveLength(2) // listed price + true cost
    expect(screen.getByText('$0.00')).toBeInTheDocument()
  })
})
