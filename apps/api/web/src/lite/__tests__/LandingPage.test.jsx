import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import LandingPage from '../LandingPage.jsx'
import { liteApi } from '../liteApi.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'
import { PUBLIC_AUDIT_BASE_URL } from '../publicUrls.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { submit: vi.fn() },
}))

let navigate

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  navigate = vi.fn()
})

describe('LandingPage — sections render', () => {
  it('renders the nav, all seven sections, and the footer', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByRole('navigation', { name: 'Parleo Audit' })).toBeInTheDocument()
    expect(screen.getByText(/THE PARLEO AUDIT/)).toBeInTheDocument()
    expect(screen.getByText('METHODOLOGY')).toBeInTheDocument()
    expect(screen.getByText('WHAT YOU GET')).toBeInTheDocument()
    expect(screen.getByText('FIELD EVIDENCE')).toBeInTheDocument()
    expect(screen.getByText('THE STAKES')).toBeInTheDocument()
    expect(screen.getByText('THE PATH')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Get your visibility report/ })).toBeInTheDocument()
    expect(screen.getByText(/Parleo scores, tracks, and optimizes/)).toBeInTheDocument()
  })
})

describe('LandingPage — hero form submits through the existing flow', () => {
  it('calls liteApi.submit, stores the token, and navigates to the canonical report URL', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-landing', status: 'pending' })

    render(<LandingPage navigate={navigate} />)

    const primaryInputs = screen.getAllByLabelText('Your brand or store URL')
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })

    const submitButtons = screen.getAllByText('Get your visibility report')
    fireEvent.click(submitButtons[0])

    await waitFor(() => expect(liteApi.submit).toHaveBeenCalledWith({
      brand_name: 'Acme Co',
      competitor_names: [],
      captcha_token: expect.any(String),
    }))
    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-landing'))
    // Stage 9 (U2), audit.parleo.io migration: history-push navigation,
    // not a full reload — the token in the URL matches the POST
    // response's token exactly, using the '/r/' prefix this page (only
    // ever rendered on the audit host) always navigates with.
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/r/tok-landing'))
  })
})

describe('LandingPage — hero and final-CTA share one form component', () => {
  it('renders two independent instances of the same compact LiteForm', () => {
    render(<LandingPage navigate={navigate} />)

    const primaryInputs = screen.getAllByLabelText('Your brand or store URL')
    expect(primaryInputs).toHaveLength(2)

    const submitButtons = screen.getAllByText('Get your visibility report')
    expect(submitButtons).toHaveLength(2)

    // Independent state: typing in one does not affect the other.
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })
    expect(primaryInputs[1]).toHaveValue('')
  })
})

describe('LandingPage — truth-rule copy regression guards', () => {
  it('never says the score is instant — only that it streams live', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText(/Results in minutes, streamed live/)).toBeInTheDocument()
    expect(screen.getByText(/Your score streams live in a few minutes/)).toBeInTheDocument()
    expect(screen.queryByText(/instantly/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/about a minute/i)).not.toBeInTheDocument()
  })

  it('marks exposure figures as modeled, not measured', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText('● Modeled')).toBeInTheDocument()
    expect(screen.getByText(/A modeled range with a deliberate haircut, not a measurement/)).toBeInTheDocument()
  })

  it('carries the exact methodology stamp', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText(`${LITE_QUERY_COUNT} queries · ChatGPT only · deterministic · sample, not a category study`)).toBeInTheDocument()
  })

  it('scopes the four-agent claim to the crawl, not the ChatGPT-only score', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText(/VISIBILITY ON CHATGPT · STORE READ ACROSS THE FOUR AGENTS/i)).toBeInTheDocument()
  })
})

describe('LandingPage — I2/I3: canonical + OG/Twitter meta on the one indexable page', () => {
  it('sets a canonical link and OG/Twitter meta pointed at PUBLIC_AUDIT_BASE_URL, cleaned up on unmount', () => {
    const { unmount } = render(<LandingPage navigate={navigate} />)

    const canonical = document.querySelector('link[rel="canonical"]')
    expect(canonical).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/`)
    expect(document.querySelector('meta[property="og:url"]')).toHaveAttribute('content', `${PUBLIC_AUDIT_BASE_URL}/`)
    expect(document.querySelector('meta[property="og:title"]')).toBeInTheDocument()
    expect(document.querySelector('meta[name="twitter:card"]')).toHaveAttribute('content', 'summary')
    expect(document.title).toContain('Parleo Audit')

    unmount()
    expect(document.querySelector('link[rel="canonical"]')).not.toBeInTheDocument()
    expect(document.querySelector('meta[property="og:title"]')).not.toBeInTheDocument()
  })
})
