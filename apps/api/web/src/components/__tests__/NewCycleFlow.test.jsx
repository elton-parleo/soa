import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import NewCycleFlow from '../NewCycleFlow.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getEntities: vi.fn(),
    getStudies: vi.fn(),
    getStudyQueries: vi.fn(),
    generateStudy: vi.fn(),
    getGenerationStatus: vi.fn(),
    checkCycleCode: vi.fn(),
    createCycle: vi.fn(),
    launchCrawl: vi.fn(),
    suggestCompetitors: vi.fn(),
    getAuditContinuation: vi.fn(),
  },
}))

const ACME = { id: 1, name: 'Acme', category: 'beauty', type: 'Brand' }
const STUDY = { id: 'retailer_sephora', name: 'Sephora Retail' }

beforeEach(() => {
  vi.clearAllMocks()
  api.getEntities.mockResolvedValue([ACME])
  api.getStudies.mockResolvedValue([STUDY])
  api.getStudyQueries.mockResolvedValue([{ query_code: 'Q1', query_text: 'Best beauty retailer?' }])
  api.checkCycleCode.mockResolvedValue({ available: true, cycle_code: 'x' })
})

async function goToStep2() {
  render(<NewCycleFlow />)
  await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Acme'))
  fireEvent.click(screen.getByText('Next: Study & Queries →'))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Study & Queries' })).toBeInTheDocument())
}

async function goToStep3() {
  await goToStep2()
  const select = screen.getByRole('combobox')
  fireEvent.change(select, { target: { value: STUDY.id } })
  await waitFor(() => expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled())
  fireEvent.click(screen.getByText('Next: Review & Launch →'))
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Review & Launch' })).toBeInTheDocument())
}

describe('NewCycleFlow — step transitions', () => {
  it('step 1 requires a primary brand before advancing', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()

    fireEvent.click(screen.getByText('Acme'))
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })

  it('advances brand -> study -> review, and back again', async () => {
    await goToStep3()
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.getByText('Sephora Retail')).toBeInTheDocument()

    fireEvent.click(screen.getByText('← Back'))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Study & Queries' })).toBeInTheDocument())
  })

  it('launches: creates the cycle, launches a crawl, and shows the post-launch status', async () => {
    api.createCycle.mockResolvedValue({ id: 99, cycle_code: '2026-08-acme-full' })
    api.launchCrawl.mockResolvedValue({ scan_id: 5, cycle_id: 99, status: 'pending' })

    await goToStep3()
    await waitFor(() => expect(screen.getByText('AVAILABLE ✓')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Launch Full Analysis'))

    await waitFor(() => expect(screen.getByText('Full Analysis launched')).toBeInTheDocument())
    expect(api.createCycle).toHaveBeenCalledTimes(1)
    const payload = api.createCycle.mock.calls[0][0]
    expect(payload.comparison_set[0]).toMatchObject({ entity_id: 1, role: 'primary' })
    expect(payload.source_lite_request_id).toBeNull()
    expect(payload.prior_cycle_id).toBeNull()
  })
})

describe('NewCycleFlow — continuation-mode pre-fill', () => {
  it('resolves brand/competitors/composite from the audit and collapses step 1 into a confirmation card', async () => {
    api.getAuditContinuation.mockResolvedValue({
      lite_request_id: 7,
      cycle_id: 42,
      brand_name: 'Acme',
      brand_entity_id: 1,
      category: 'beauty',
      competitors: [{ name: 'Rival Co', entity_id: 2, domain: null }],
      composite: 74,
      verdict: 'AGENT-READY',
      audited_at: '2026-08-01',
      store_url: 'https://acme.com',
      store_domain: 'acme.com',
    })

    render(<NewCycleFlow auditToken="tok123" />)

    await waitFor(() => expect(api.getAuditContinuation).toHaveBeenCalledWith('tok123'))
    await waitFor(() =>
      expect(screen.getByText(/Continuing from your audit of Acme, scored 74 on 2026-08-01/)).toBeInTheDocument()
    )
    expect(screen.getByText(/Competitors: Rival Co/)).toBeInTheDocument()

    // Step 1 is already satisfied — no manual brand pick required.
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })

  it('an edit click drops back to the manual picker without losing the resolved data entirely', async () => {
    api.getAuditContinuation.mockResolvedValue({
      lite_request_id: 7, cycle_id: 42, brand_name: 'Acme', brand_entity_id: 1,
      category: 'beauty', competitors: [], composite: 74, verdict: 'AGENT-READY',
      audited_at: '2026-08-01', store_url: 'https://acme.com', store_domain: 'acme.com',
    })

    render(<NewCycleFlow auditToken="tok123" />)
    await waitFor(() => expect(screen.getByText(/Continuing from your audit/)).toBeInTheDocument())

    fireEvent.click(screen.getByText('Edit brand & competitors'))
    await waitFor(() => expect(screen.getByText('Primary brand')).toBeInTheDocument())
  })
})

describe('NewCycleFlow — honest platform rendering', () => {
  it('always lists Perplexity but marks it unavailable, and never includes it in the launch payload', async () => {
    api.createCycle.mockResolvedValue({ id: 99, cycle_code: '2026-08-acme-full' })
    api.launchCrawl.mockResolvedValue({ scan_id: 5, cycle_id: 99, status: 'pending' })

    await goToStep2()
    expect(screen.getByText(/Perplexity — unavailable/)).toBeInTheDocument()

    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: STUDY.id } })
    await waitFor(() => expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled())
    fireEvent.click(screen.getByText('Next: Review & Launch →'))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Review & Launch' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('AVAILABLE ✓')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Launch Full Analysis'))
    await waitFor(() => expect(api.createCycle).toHaveBeenCalledTimes(1))

    const payload = api.createCycle.mock.calls[0][0]
    expect(payload.platforms).not.toContain('perplexity')
    expect(payload.platforms).toEqual(['chatgpt', 'gemini'])
  })
})
