import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

// Both the Hero and FinalCta LiteForm submit buttons read "Run my free
// audit", and so does LandingNav's plain #run anchor button — filter to
// the two that are actual form submit buttons.
function formSubmitButtons() {
  return screen.getAllByRole('button', { name: 'Run my free audit' }).filter((btn) => btn.closest('form'))
}

describe('LandingPage — sections render', () => {
  it('renders the nav, all V4 sections, and the footer', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByRole('navigation', { name: 'Parleo Audit' })).toBeInTheDocument()
    expect(screen.getByText(/We test ChatGPT with queries across the entire purchase funnel/)).toBeInTheDocument()
    expect(screen.getByText('STORES WE AUDIT')).toBeInTheDocument()
    expect(screen.getByText('costing you?')).toBeInTheDocument()
    expect(screen.getByText('CASE 01')).toBeInTheDocument()
    expect(screen.getByText('Find the leak')).toBeInTheDocument()
    expect(screen.getByText('MODELED EXPOSURE $4.5M / YR')).toBeInTheDocument()
    expect(screen.getByText(/The Share of Algorithm framework/)).toBeInTheDocument()
    expect(screen.getByText('Every number above is measured')).toBeInTheDocument()
    expect(screen.getByText('TRUESYNC')).toBeInTheDocument()
    expect(screen.getByText('Find out what agents are missing.')).toBeInTheDocument()
    expect(screen.getByText('© 2026 Parleo, Inc.')).toBeInTheDocument()
  })
})

describe('LandingPage — Part 4: expired-report CTA url prefill', () => {
  afterEach(() => {
    window.history.pushState(null, '', '/')
  })

  it('prefills the hero form from a ?url= query param, e.g. from the expired-report CTA', () => {
    window.history.pushState(null, '', '/?url=https%3A%2F%2Foldstore.example.com')
    render(<LandingPage navigate={navigate} />)
    const input = screen.getAllByPlaceholderText('yourstore.com')[0]
    expect(input).toHaveValue('https://oldstore.example.com')
  })

  it('leaves the hero form empty when no ?url= param is present', () => {
    render(<LandingPage navigate={navigate} />)
    const input = screen.getAllByPlaceholderText('yourstore.com')[0]
    expect(input).toHaveValue('')
  })
})

describe('LandingPage — hero form submits through the existing flow', () => {
  it('calls liteApi.submit, stores the token, and navigates to the canonical report URL', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-landing', status: 'pending' })

    render(<LandingPage navigate={navigate} />)

    const primaryInputs = screen.getAllByLabelText('Your brand or store URL')
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })

    fireEvent.click(formSubmitButtons()[0])

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
    expect(formSubmitButtons()).toHaveLength(2)

    // Independent state: typing in one does not affect the other.
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })
    expect(primaryInputs[1]).toHaveValue('')
  })
})

describe('LandingPage — truth-rule copy regression guards', () => {
  it('never says the score is instant — only gives a real time window', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText('Ready in 10–20 minutes')).toBeInTheDocument()
    expect(screen.queryByText(/instantly/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/about a minute/i)).not.toBeInTheDocument()
  })

  it('marks the stakes-widget exposure figure as modeled, not measured', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText('Modeled')).toBeInTheDocument()
    expect(screen.getByText(/Assumes agents currently find you 0% of the time/)).toBeInTheDocument()
  })

  it('carries the exact methodology provenance', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText(`${LITE_QUERY_COUNT} queries, ChatGPT only, deterministic`)).toBeInTheDocument()
  })

  it('scopes the multi-agent claim to the Full Analysis, not the free ChatGPT-only score', () => {
    render(<LandingPage navigate={navigate} />)

    expect(screen.getByText(/plus Gemini, Perplexity and Claude in the Full Analysis/)).toBeInTheDocument()
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

  it('S2: idempotent against tags the static HTML already baked in — updates in place, never duplicates', () => {
    // Simulates audit.html's build-time-injected head (S1) already
    // being in the DOM before React ever mounts.
    const staticCanonical = document.createElement('link')
    staticCanonical.rel = 'canonical'
    staticCanonical.href = 'https://audit.parleo.io/stale'
    document.head.appendChild(staticCanonical)

    const staticOgTitle = document.createElement('meta')
    staticOgTitle.setAttribute('property', 'og:title')
    staticOgTitle.content = 'stale title'
    document.head.appendChild(staticOgTitle)

    const { unmount } = render(<LandingPage navigate={navigate} />)

    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
    expect(document.querySelectorAll('meta[property="og:title"]')).toHaveLength(1)
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/`)
    expect(document.querySelector('meta[property="og:title"]').content).not.toBe('stale title')

    unmount()
    // The tags pre-existed, so unmount restores them rather than
    // removing them — the static document must still have a head.
    expect(document.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
    expect(document.querySelector('link[rel="canonical"]')).toHaveAttribute('href', 'https://audit.parleo.io/stale')
    expect(document.querySelector('meta[property="og:title"]').content).toBe('stale title')

    document.head.removeChild(document.querySelector('link[rel="canonical"]'))
    document.head.removeChild(document.querySelector('meta[property="og:title"]'))
  })
})
