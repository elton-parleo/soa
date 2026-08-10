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
const ZETA = { id: 2, name: 'Zeta Co', category: 'grooming', type: 'Brand' }
const STUDY = { id: 'retailer_sephora', name: 'Sephora Retail' }

beforeEach(() => {
  vi.clearAllMocks()
  api.getEntities.mockResolvedValue([ACME])
  api.getStudies.mockResolvedValue([STUDY])
  api.getStudyQueries.mockResolvedValue([{ query_code: 'Q1', query_text: 'Best beauty retailer?' }])
  api.checkCycleCode.mockResolvedValue({ available: true, cycle_code: 'x' })
})

function brandInput() {
  return screen.getByPlaceholderText(/Search entities/)
}

// Opens the dropdown (focus) and clicks an already-rendered option —
// the real combobox UX: nothing is selectable until the field has focus.
async function selectBrand(name) {
  fireEvent.focus(brandInput())
  await waitFor(() => expect(screen.getByText(name)).toBeInTheDocument())
  fireEvent.mouseDown(screen.getByText(name))
}

async function goToStep2() {
  render(<NewCycleFlow />)
  await waitFor(() => expect(brandInput()).toBeInTheDocument())
  await selectBrand('Acme')
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
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()

    await selectBrand('Acme')
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })

  it('does not crash when the entity fetch resolves undefined (api.js\'s 401 handler resolves instead of rejecting) — the picker still renders and stays usable', async () => {
    // Regression for the real bug: api.js's request() calls
    // supabase.auth.signOut() + window.location.reload() and returns
    // (not throws) on a 401, so .then(setEntities) — not .catch() — is
    // what receives this. Before the fix, entities.filter(...) on this
    // undefined threw and unmounted the whole step with no error
    // boundary above it, making brand selection permanently impossible.
    api.getEntities.mockResolvedValue(undefined)
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.focus(brandInput())
    await waitFor(() => expect(screen.getByText('No matches — try a different search.')).toBeInTheDocument())
    // The rest of step 1 must still be fully interactive — proves this
    // didn't silently unmount/crash the component.
    expect(screen.getByPlaceholderText('https://example.com')).toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()
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

describe('NewCycleFlow — brand combobox', () => {
  beforeEach(() => {
    api.getEntities.mockResolvedValue([ACME, ZETA])
  })

  it('selecting an option fills the input, closes the dropdown, and enables Next', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.change(brandInput(), { target: { value: 'ac' } })
    expect(screen.getByText('Acme')).toBeInTheDocument()
    expect(screen.queryByText('Zeta Co')).not.toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()

    fireEvent.mouseDown(screen.getByText('Acme'))

    expect(brandInput()).toHaveValue('Acme')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })

  it('editing the text after a selection clears the stored selection and disables Next', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    await selectBrand('Acme')
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()

    fireEvent.change(brandInput(), { target: { value: 'Acme X' } })

    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()
    // Typed text alone is never treated as a selection, even if it
    // happens to match — the dropdown must reopen, not silently commit.
    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('Escape closes the dropdown', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    fireEvent.focus(brandInput())
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.keyDown(brandInput(), { key: 'Escape' })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('click-outside closes the dropdown', async () => {
    render(
      <div>
        <div data-testid="outside">outside</div>
        <NewCycleFlow />
      </div>
    )
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    fireEvent.focus(brandInput())
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByTestId('outside'))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('arrow keys move the highlight and Enter selects the highlighted option', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    fireEvent.focus(brandInput())
    await waitFor(() => expect(screen.getByText('Zeta Co')).toBeInTheDocument())

    fireEvent.keyDown(brandInput(), { key: 'ArrowDown' }) // highlight Acme (index 0)
    fireEvent.keyDown(brandInput(), { key: 'ArrowDown' }) // highlight Zeta Co (index 1)
    fireEvent.keyDown(brandInput(), { key: 'Enter' })

    expect(brandInput()).toHaveValue('Zeta Co')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
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

  it('an edit click drops back to the manual picker with the pre-filled brand as a committed selection, not an open dropdown', async () => {
    api.getAuditContinuation.mockResolvedValue({
      lite_request_id: 7, cycle_id: 42, brand_name: 'Acme', brand_entity_id: 1,
      category: 'beauty', competitors: [], composite: 74, verdict: 'AGENT-READY',
      audited_at: '2026-08-01', store_url: 'https://acme.com', store_domain: 'acme.com',
    })

    render(<NewCycleFlow auditToken="tok123" />)
    await waitFor(() => expect(screen.getByText(/Continuing from your audit/)).toBeInTheDocument())

    fireEvent.click(screen.getByText('Edit brand & competitors'))
    await waitFor(() => expect(screen.getByText('Primary brand')).toBeInTheDocument())

    // Committed selection: input pre-filled with the audit's brand name,
    // dropdown closed, Next already enabled — never an open/blank query.
    expect(brandInput()).toHaveValue('Acme')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })
})

describe('NewCycleFlow — degraded competitor suggestions', () => {
  async function selectAcme() {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    await selectBrand('Acme')
  }

  it('a backend-reported degraded response renders the notice, and manual add still works', async () => {
    api.suggestCompetitors.mockResolvedValue({ status: 'degraded', reason: 'suggestions_unavailable', competitors: [], source: 'none' })
    await selectAcme()

    fireEvent.click(screen.getByText('✦ Auto-suggest'))
    await waitFor(() => expect(screen.getByText('Suggestions are unavailable — add competitors manually.')).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText('Add a competitor by name'), { target: { value: 'Rival Co' } })
    fireEvent.click(screen.getByText('Add'))
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
  })

  it('a request that errors gets the same honest notice, not a silent no-op', async () => {
    api.suggestCompetitors.mockRejectedValue(new Error('network error'))
    await selectAcme()

    fireEvent.click(screen.getByText('✦ Auto-suggest'))
    await waitFor(() => expect(screen.getByText('Suggestions are unavailable — add competitors manually.')).toBeInTheDocument())
  })

  it('an ok status with real suggestions never shows the degraded notice', async () => {
    api.suggestCompetitors.mockResolvedValue({
      status: 'ok', reason: null,
      competitors: [{ name: 'Rival Co', domain: null }], source: 'generated',
    })
    await selectAcme()

    fireEvent.click(screen.getByText('✦ Auto-suggest'))
    await waitFor(() => expect(screen.getByText('Rival Co')).toBeInTheDocument())
    expect(screen.queryByText('Suggestions are unavailable — add competitors manually.')).not.toBeInTheDocument()
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
