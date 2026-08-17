import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import NewCycleFlow from '../NewCycleFlow.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getEntities: vi.fn(),
    createEntity: vi.fn(),
    getStudies: vi.fn(),
    getQueryRows: vi.fn(),
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
  api.getQueryRows.mockResolvedValue([{ query_code: 'Q1', query_text: 'Best beauty retailer?' }])
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

describe('NewCycleFlow — create a new primary brand inline', () => {
  it('typing a name with no match offers to create it; selecting it commits the created entity', async () => {
    const NEW_BRAND = { id: 99, name: 'Allbirds', category: '', type: 'Brand' }
    api.createEntity.mockResolvedValue(NEW_BRAND)

    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.change(brandInput(), { target: { value: 'Allbirds' } })
    expect(screen.getByText('⊕ Create "Allbirds" as a new brand')).toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()

    fireEvent.mouseDown(screen.getByText('⊕ Create "Allbirds" as a new brand'))

    await waitFor(() => expect(api.createEntity).toHaveBeenCalledWith({
      name: 'Allbirds', type: 'Brand', category: '', website_url: null, aliases: [],
    }))
    // Committed exactly like picking an existing option: input filled,
    // dropdown closed, Next enabled.
    await waitFor(() => expect(brandInput()).toHaveValue('Allbirds'))
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByText('Next: Study & Queries →')).not.toBeDisabled()
  })

  it('never offers to create a name that already matches an existing entity exactly', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.change(brandInput(), { target: { value: 'Acme' } })

    expect(screen.queryByText('⊕ Create "Acme" as a new brand')).not.toBeInTheDocument()
    expect(screen.getByText('Acme')).toBeInTheDocument()
  })

  it('the dedup check is case-insensitive — "ACME" surfaces the existing Acme, never a create row', async () => {
    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.change(brandInput(), { target: { value: 'ACME' } })

    expect(screen.queryByText('⊕ Create "ACME" as a new brand')).not.toBeInTheDocument()
    fireEvent.mouseDown(screen.getByText('Acme'))

    expect(api.createEntity).not.toHaveBeenCalled()
    // Selecting the existing option commits ITS name (the canonical
    // "Acme"), not the visitor's differently-cased typed text.
    expect(brandInput()).toHaveValue('Acme')
  })

  it('a create failure shows an inline notice and never resets the typed text', async () => {
    api.createEntity.mockRejectedValue(new Error('Could not reach the entity service.'))

    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())

    fireEvent.change(brandInput(), { target: { value: 'Allbirds' } })
    fireEvent.mouseDown(screen.getByText('⊕ Create "Allbirds" as a new brand'))

    await waitFor(() => expect(screen.getByText('Could not reach the entity service.')).toBeInTheDocument())
    expect(brandInput()).toHaveValue('Allbirds')
    expect(screen.getByText('Next: Study & Queries →')).toBeDisabled()
  })

  it('the newly created brand flows into competitor auto-suggest like any other entity', async () => {
    const NEW_BRAND = { id: 99, name: 'Allbirds', category: 'footwear', type: 'Brand' }
    api.createEntity.mockResolvedValue(NEW_BRAND)
    api.suggestCompetitors.mockResolvedValue({ status: 'ok', reason: null, competitors: [{ name: 'Rothys', domain: null }], source: 'generated' })

    render(<NewCycleFlow />)
    await waitFor(() => expect(brandInput()).toBeInTheDocument())
    fireEvent.change(brandInput(), { target: { value: 'Allbirds' } })
    fireEvent.mouseDown(screen.getByText('⊕ Create "Allbirds" as a new brand'))
    await waitFor(() => expect(brandInput()).toHaveValue('Allbirds'))

    fireEvent.click(screen.getByText('✦ Auto-suggest'))

    await waitFor(() => expect(api.suggestCompetitors).toHaveBeenCalledWith(expect.objectContaining({
      brand_name: 'Allbirds', category_hint: 'footwear',
    })))
    expect(screen.getByText('Rothys')).toBeInTheDocument()
  })
})

describe('NewCycleFlow — inline study generation', () => {
  const POLL_MS = 3000 // NewCycleFlow.jsx's GENERATION_POLL_INTERVAL_MS

  // Runs under REAL timers — testing-library's waitFor polls via
  // setTimeout internally, which stalls once fake timers are active.
  // Each test switches to fake timers only after this returns, to drive
  // the setInterval-based polling loop deterministically.
  async function goToStep2AndOpenGenerateForm(name = 'Allbirds Full Analysis') {
    await goToStep2()
    fireEvent.click(screen.getByText('⊕ Generate a new study inline'))
    fireEvent.change(screen.getByPlaceholderText('Study name'), { target: { value: name } })
  }

  it('successful generation: the study appears in the selector, selected, and queries render', async () => {
    const NEW_ID = 'allbirds_full_analysis_9a4465'
    api.generateStudy.mockResolvedValue({ study_type: NEW_ID, study_name: 'Allbirds Full Analysis', job_id: 1, status: 'pending' })
    api.getGenerationStatus
      .mockResolvedValueOnce({ study_type: NEW_ID, status: 'running', target_count: 50, created_count: 0 })
      .mockResolvedValueOnce({ study_type: NEW_ID, status: 'complete', target_count: 50, created_count: 50 })
    api.getStudies
      .mockResolvedValueOnce([STUDY]) // initial mount fetch
      .mockResolvedValueOnce([STUDY, { id: NEW_ID, name: 'Allbirds Full Analysis', category: 'footwear', patterns: [], queryCount: 50, lastRun: null }])
    api.getQueryRows.mockResolvedValue([
      { query_code: 'ALL_001', query_text: 'Best sustainable sneakers?' },
      { query_code: 'ALL_002', query_text: 'Allbirds vs Rothys?' },
    ])

    await goToStep2AndOpenGenerateForm()

    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByText('Generate'))
      await vi.advanceTimersByTimeAsync(0) // flush generateStudy() + the synthesized studies update

      // Synthesized into the list immediately — the <select> shows the
      // new study selected right away, never an orphan/blank value.
      expect(screen.getByRole('combobox')).toHaveValue(NEW_ID)
      // Generation is in flight — a study id is set, but no queries
      // exist yet, so Next must stay disabled.
      expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()

      await vi.advanceTimersByTimeAsync(POLL_MS) // poll 1: running
      expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()
      await vi.advanceTimersByTimeAsync(POLL_MS) // poll 2: complete

      expect(screen.getByText(/2 queries in this study/)).toBeInTheDocument()
      fireEvent.click(screen.getByText(/2 queries in this study/))
      expect(screen.getByText('Best sustainable sneakers?')).toBeInTheDocument()
      expect(screen.getByText('Allbirds vs Rothys?')).toBeInTheDocument()
      // The real /api/studies list was refetched once generation completed.
      expect(api.getStudies).toHaveBeenCalledTimes(2)
      expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('a slow initial query-rows fetch does not clobber the terminal refetch (out-of-order response race)', async () => {
    // Regression for "count stays 0 after a successful generation":
    // the "study just generated" effect fires an initial getQueryRows
    // the instant studyType.id is set — normally empty, since the
    // worker hasn't run yet — and under real network jitter that
    // request can resolve AFTER the generation-complete refetch lands
    // its real rows, silently overwriting the count back to 0.
    const NEW_ID = 'allbirds_full_analysis_9a4465'
    api.generateStudy.mockResolvedValue({ study_type: NEW_ID, study_name: 'Allbirds Full Analysis', job_id: 1, status: 'pending' })
    api.getGenerationStatus
      .mockResolvedValueOnce({ study_type: NEW_ID, status: 'running', target_count: 50, created_count: 0 })
      .mockResolvedValueOnce({ study_type: NEW_ID, status: 'complete', target_count: 50, created_count: 50 })
    api.getStudies.mockResolvedValue([STUDY])

    let resolveInitialFetch
    const initialFetch = new Promise(resolve => { resolveInitialFetch = resolve })
    api.getQueryRows
      .mockReturnValueOnce(initialFetch) // the "just selected/generated" effect's fetch — stays pending
      .mockResolvedValueOnce([ // the generation-complete refetch — resolves normally
        { query_code: 'ALL_001', query_text: 'Best sustainable sneakers?' },
      ])

    await goToStep2AndOpenGenerateForm()

    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByText('Generate'))
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(POLL_MS) // poll 1: running
      await vi.advanceTimersByTimeAsync(POLL_MS) // poll 2: complete — real rows land

      expect(screen.getByText(/1 query in this study/)).toBeInTheDocument()
      expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled()

      // The slow initial fetch FINALLY resolves, late, with stale empty
      // data — it must be discarded, not applied.
      resolveInitialFetch([])
      await vi.advanceTimersByTimeAsync(0)

      expect(screen.getByText(/1 query in this study/)).toBeInTheDocument()
      expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('a failed generation status renders a notice with retry, without resetting study type or depth', async () => {
    const NEW_ID = 'allbirds_full_analysis_9a4465'
    api.generateStudy.mockResolvedValue({ study_type: NEW_ID, study_name: 'Allbirds Full Analysis', job_id: 1, status: 'pending' })
    api.getGenerationStatus.mockResolvedValueOnce({
      study_type: NEW_ID, status: 'failed', target_count: 50, created_count: 0, error_message: 'OpenAI request timed out',
    })
    // A brand-new study genuinely has zero queries until generation
    // succeeds — overrides the shared beforeEach default (which models
    // an existing, already-populated study) so this test's "zero
    // queries, Next disabled" assertion reflects a real failed job.
    api.getQueryRows.mockResolvedValue([])

    await goToStep2()
    // Pick Deep before generating — must survive the failure untouched.
    fireEvent.click(screen.getByText('Deep'))
    fireEvent.click(screen.getByText('⊕ Generate a new study inline'))
    fireEvent.change(screen.getByPlaceholderText('Study name'), { target: { value: 'Allbirds Full Analysis' } })

    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByText('Generate'))
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(POLL_MS)

      expect(screen.getByText('OpenAI request timed out')).toBeInTheDocument()
      expect(screen.getByText('Retry')).toBeInTheDocument()
      // No reset: the failed study stays selected (visible for context)
      // and the depth preset the user picked is untouched — still
      // rendered with the "selected" border color (T.navy), not reverted
      // to Standard.
      expect(screen.getByRole('combobox')).toHaveValue(NEW_ID)
      expect(screen.getByText('Deep').parentElement).toHaveStyle({ borderColor: 'rgb(13, 24, 41)' })
      // A failed generation produced zero queries — Next must stay
      // disabled, never enabled off a bare studyType id.
      expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('polling timeout renders a notice, not a silent reset', async () => {
    const NEW_ID = 'allbirds_full_analysis_9a4465'
    api.generateStudy.mockResolvedValue({ study_type: NEW_ID, study_name: 'Allbirds Full Analysis', job_id: 1, status: 'pending' })
    // Always 'running' — never reaches a terminal status.
    api.getGenerationStatus.mockResolvedValue({ study_type: NEW_ID, status: 'running', target_count: 50, created_count: 3 })

    await goToStep2AndOpenGenerateForm()

    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByText('Generate'))
      await vi.advanceTimersByTimeAsync(0)

      // GENERATION_MAX_POLLS is 40 — advance past it.
      for (let i = 0; i < 41; i++) {
        await vi.advanceTimersByTimeAsync(POLL_MS)
      }

      expect(screen.getByText('Query generation is taking longer than expected.')).toBeInTheDocument()
      expect(screen.getByText('Retry')).toBeInTheDocument()
      // Still the same study selected, not reset to the placeholder.
      expect(screen.getByRole('combobox')).toHaveValue(NEW_ID)
    } finally {
      vi.useRealTimers()
    }
  }, 10000)

  it('retry re-invokes generation with the same name after a failure', async () => {
    const FAILED_ID = 'allbirds_full_analysis_9a4465'
    const RETRY_ID = 'allbirds_full_analysis_b2c3d4'
    api.generateStudy
      .mockResolvedValueOnce({ study_type: FAILED_ID, study_name: 'Allbirds Full Analysis', job_id: 1, status: 'pending' })
      .mockResolvedValueOnce({ study_type: RETRY_ID, study_name: 'Allbirds Full Analysis', job_id: 2, status: 'pending' })
    api.getGenerationStatus.mockResolvedValueOnce({
      study_type: FAILED_ID, status: 'failed', target_count: 50, created_count: 0, error_message: 'boom',
    })

    await goToStep2AndOpenGenerateForm()

    vi.useFakeTimers()
    try {
      fireEvent.click(screen.getByText('Generate'))
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(POLL_MS)
      expect(screen.getByText('Retry')).toBeInTheDocument()

      fireEvent.click(screen.getByText('Retry'))
      await vi.advanceTimersByTimeAsync(0)

      expect(api.generateStudy).toHaveBeenCalledTimes(2)
      expect(api.generateStudy.mock.calls[1][0]).toMatchObject({ study_name: 'Allbirds Full Analysis' })
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('NewCycleFlow — Step 2 Next gating', () => {
  it('Next is disabled until a study is selected', async () => {
    await goToStep2()
    expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()
  })

  it('regression: selecting an EXISTING study (no inline generation) still fetches its queries and enables Next', async () => {
    await goToStep2()
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: STUDY.id } })

    await waitFor(() => expect(screen.getByText(/1 query in this study/)).toBeInTheDocument())
    expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled()
  })

  it('switching from a study with queries to one that resolves empty clears the stale count and disables Next again', async () => {
    api.getStudies.mockResolvedValue([STUDY, { id: 'retailer_target', name: 'Target Retail' }])
    api.getQueryRows
      .mockResolvedValueOnce([{ query_code: 'Q1', query_text: 'Best beauty retailer?' }]) // Sephora
      .mockResolvedValueOnce([]) // Target — genuinely no queries yet

    await goToStep2()
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: STUDY.id } })
    await waitFor(() => expect(screen.getByText('Next: Review & Launch →')).not.toBeDisabled())

    fireEvent.change(select, { target: { value: 'retailer_target' } })
    // Cleared immediately — never left showing Sephora's stale count/
    // enabling Next for a study that hasn't confirmed it has queries.
    expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()

    await waitFor(() => expect(screen.getByText(/0 queries in this study/)).toBeInTheDocument())
    expect(screen.getByText('Next: Review & Launch →')).toBeDisabled()
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
