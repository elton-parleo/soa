import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { LiteForm } from '../LiteForm.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { submit: vi.fn() },
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
