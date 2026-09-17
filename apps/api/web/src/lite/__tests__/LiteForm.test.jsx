import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { LiteForm } from '../LiteForm.jsx'
import { liteApi } from '../liteApi.js'
import { track, identifyReport, getAttribution } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { submit: vi.fn() },
}))

vi.mock('../analytics.js', () => ({
  track: vi.fn(),
  identifyReport: vi.fn(),
  recordOwnedToken: vi.fn(),
  captureSrcParam: vi.fn(() => 'direct'),
  getAttribution: vi.fn(() => ({
    oppref: null, utm_source: null, utm_medium: null, utm_campaign: null,
  })),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('LiteForm — brand-only mode', () => {
  it('rejects an invalid brand name client-side without calling the API', async () => {
    render(<LiteForm onSubmitted={() => {}} />)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'A' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/2-80 characters/)).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
    expect(track).not.toHaveBeenCalled()
  })

  it('rejects a competitor matching the brand name', async () => {
    render(<LiteForm onSubmitted={() => {}} />)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.change(screen.getByLabelText(/Competitor 1/), { target: { value: 'acme co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/different from the brand/)).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('submits brand-only cleaned data with no store_url and calls onSubmitted', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-123', status: 'pending' })
    const onSubmitted = vi.fn()

    render(<LiteForm onSubmitted={onSubmitted} />)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: '  Acme Co  ' } })
    fireEvent.change(screen.getByLabelText(/Competitor 1/), { target: { value: 'Rival Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith('tok-123', { storeUrl: null }))
    expect(liteApi.submit).toHaveBeenCalledWith({
      brand_name: 'Acme Co',
      competitor_names: ['Rival Co'],
      captcha_token: expect.any(String),
    })
    // A brand-only submission has no store URL, so target_domain is an
    // explicit null rather than an absent key — "we asked and there
    // isn't one" reads differently in PostHog from "never sent".
    expect(track).toHaveBeenCalledWith(EVENTS.AUDIT_SUBMITTED, {
      report_token: 'tok-123',
      target_domain: null,
      oppref: null,
      utm_source: null,
      src: 'direct',
    })
  })

  it('shows a rate-limit message on 429', async () => {
    const err = new Error('Too many SoA Lite requests from this IP — try again in an hour.')
    err.status = 429
    liteApi.submit.mockRejectedValue(err)

    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/try again in an hour/)).toBeInTheDocument())
  })

  it('pre-fills the primary field from initialBrandName', () => {
    render(<LiteForm onSubmitted={() => {}} initialBrandName="Acme Co" />)
    expect(screen.getByLabelText('Your brand or store URL')).toHaveValue('Acme Co')
  })
})

describe('LiteForm — URL auto-detect mode', () => {
  it('detects a URL and shows an editable derived brand-name confirmation field', () => {
    render(<LiteForm onSubmitted={() => {}} />)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'allbirds.com' } })

    expect(screen.getByText(/Looks like a URL/)).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm your brand name')).toHaveValue('Allbirds')
  })

  it('keeps re-deriving the brand name as the URL changes until the user edits it', () => {
    render(<LiteForm onSubmitted={() => {}} />)
    const primary = screen.getByLabelText('Your brand or store URL')

    fireEvent.change(primary, { target: { value: 'acme.com' } })
    expect(screen.getByLabelText('Confirm your brand name')).toHaveValue('Acme')

    fireEvent.change(primary, { target: { value: 'glossier.com' } })
    expect(screen.getByLabelText('Confirm your brand name')).toHaveValue('Glossier')
  })

  it('stops auto-deriving once the visitor edits the confirmation field directly', () => {
    render(<LiteForm onSubmitted={() => {}} />)
    const primary = screen.getByLabelText('Your brand or store URL')

    fireEvent.change(primary, { target: { value: 'acme.com' } })
    fireEvent.change(screen.getByLabelText('Confirm your brand name'), { target: { value: 'My Custom Name' } })
    fireEvent.change(primary, { target: { value: 'acme.com/products' } })

    expect(screen.getByLabelText('Confirm your brand name')).toHaveValue('My Custom Name')
  })

  it('submits with store_url set and brand_name from the confirmation field', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-url', status: 'pending' })
    const onSubmitted = vi.fn()

    render(<LiteForm onSubmitted={onSubmitted} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'acme.com' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith('tok-url', { storeUrl: 'acme.com' }))
    expect(liteApi.submit).toHaveBeenCalledWith({
      brand_name: 'Acme',
      competitor_names: [],
      captcha_token: expect.any(String),
      store_url: 'acme.com',
    })
  })

  it('reverts to brand-only mode when the field no longer looks like a URL', () => {
    render(<LiteForm onSubmitted={() => {}} />)
    const primary = screen.getByLabelText('Your brand or store URL')

    fireEvent.change(primary, { target: { value: 'acme.com' } })
    expect(screen.getByLabelText('Confirm your brand name')).toBeInTheDocument()

    fireEvent.change(primary, { target: { value: 'Acme Co' } })
    expect(screen.queryByLabelText('Confirm your brand name')).not.toBeInTheDocument()
  })

  it('validates the derived/confirmed brand name, not the raw URL', async () => {
    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'a.co' } })
    fireEvent.change(screen.getByLabelText('Confirm your brand name'), { target: { value: 'X' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/2-80 characters/)).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
  })
})

// ─── Stage 13 (W1): compact mode no longer collects competitor names ────

describe('LiteForm — compact mode (Stage 6 hero/final-CTA)', () => {
  it('shows the auto-identify note instead of competitor inputs', () => {
    render(<LiteForm onSubmitted={() => {}} compact />)

    expect(screen.getByText(/We'll identify your closest competitors automatically\./)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Competitor 1/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Compare against/)).not.toBeInTheDocument()
  })

  it('submits with an empty competitor_names list — auto-generation happens worker-side', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok1', status: 'pending' })
    const onSubmitted = vi.fn()
    render(<LiteForm onSubmitted={onSubmitted} compact />)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(liteApi.submit).toHaveBeenCalledWith({
      brand_name: 'Acme Co',
      competitor_names: [],
      captcha_token: expect.any(String),
    }))
  })
})

// ─── audit_submitted's payload (paid-attribution session) ──────────────
//
// The event used to carry nothing at all — its registry entry was an
// empty array, so track() dropped every prop — which is why PostHog
// could see oppref on 88 of 130 landing views and on 4 of 14
// submissions. It now carries the run token (the id every other
// system already uses for this audit) and the attribution the session
// arrived with.
describe('LiteForm — audit_submitted carries the run token and attribution', () => {
  beforeEach(() => {
    getAttribution.mockReturnValue({
      oppref: 'ABC123', utm_source: 'chatgpt', utm_medium: 'cpc', utm_campaign: 'q4',
    })
  })

  async function submitBrandOnly(token = 'tok-attr') {
    liteApi.submit.mockResolvedValue({ token, status: 'pending' })
    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))
    await waitFor(() => expect(track).toHaveBeenCalled())
  }

  it('sends report_token, target_domain, oppref, utm_source and src', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-attr', status: 'pending' })
    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'acme.com' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(track).toHaveBeenCalledWith(EVENTS.AUDIT_SUBMITTED, {
      report_token: 'tok-attr',
      target_domain: 'acme.com',
      oppref: 'ABC123',
      utm_source: 'chatgpt',
      src: 'direct',
    }))
  })

  it('target_domain is the bare hostname, not the raw URL the visitor typed', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-domain', status: 'pending' })
    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'https://www.acme.com/collections/all' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(track).toHaveBeenCalledWith(
      EVENTS.AUDIT_SUBMITTED,
      expect.objectContaining({ target_domain: 'acme.com' }),
    ))
  })

  // Order matters: identifyReport registers report_token as a
  // super-property, and everything after it in this session — including
  // this very event — should be able to rely on it being set.
  it('calls identifyReport with the token BEFORE firing the event', async () => {
    await submitBrandOnly('tok-order')

    expect(identifyReport).toHaveBeenCalledWith('tok-order')
    expect(identifyReport.mock.invocationCallOrder[0])
      .toBeLessThan(track.mock.invocationCallOrder[0])
  })

  it('fires neither when the API rejects', async () => {
    liteApi.submit.mockRejectedValue(new Error('nope'))
    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText('nope')).toBeInTheDocument())
    expect(identifyReport).not.toHaveBeenCalled()
    expect(track).not.toHaveBeenCalled()
  })

  // The registry forbids form values, and the banned-prop test enforces
  // it — this pins the same rule at the call site, where a well-meaning
  // "just add the brand name" would actually be written.
  it('never sends an email or the brand name the visitor typed', async () => {
    await submitBrandOnly()
    const props = track.mock.calls[0][1]
    expect(Object.keys(props).sort()).toEqual(
      ['oppref', 'report_token', 'src', 'target_domain', 'utm_source'],
    )
  })
})
