import React from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import LandingPage from '../LandingPage.jsx'
import { liteApi } from '../liteApi.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'
import { PARLEO_HOME_URL, PUBLIC_AUDIT_BASE_URL } from '../publicUrls.js'
import { OG_IMAGE_PATH, OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT, OG_IMAGE_ALT } from '../landingMeta.js'

// landingMeta.js exports the share card as a root-relative path now;
// the absolute URL is composed per-consumer from the env-aware audit
// base (see LandingPage.jsx), so the expectation is composed the same
// way rather than re-hardcoding an origin here.
const OG_IMAGE_URL = `${PUBLIC_AUDIT_BASE_URL}${OG_IMAGE_PATH}`

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
    // Exposure-model fix: the ceiling this widget assumes is now stated
    // in the terms the model actually uses (True Value 0 — no value
    // readable), not the mention-gap terms it used to borrow from
    // Visibility. The figure itself is unchanged; only the claim is.
    expect(screen.getByText(/Assumes agents can currently read none of your value/)).toBeInTheDocument()
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

// ─── Stakes revenue control: $5B ceiling, log track, typed amount ──────

describe('LandingPage — the Stakes estimator reaches large brands', () => {
  const amount = () => screen.getByLabelText('Annual online revenue (exact amount)')
  const track = () => screen.getByLabelText('Annual online revenue')

  it('the revenue track carries a log position; the AI-share slider is untouched', () => {
    render(<LandingPage navigate={navigate} />)
    expect(track()).toHaveAttribute('max', '1000')
    expect(track()).toHaveAttribute('step', '1')
    const share = screen.getByLabelText('AI-assisted share of sales')
    expect(share).toHaveAttribute('min', '5')
    expect(share).toHaveAttribute('max', '40')
  })

  it('typing an amount updates the slider and the modeled figure together', () => {
    render(<LandingPage navigate={navigate} />)
    fireEvent.change(amount(), { target: { value: '1.5b' } })
    fireEvent.blur(amount())

    expect(amount()).toHaveValue('$1.5B')
    // trueValueScore 0 on the landing: 1,500,000,000 * 0.20 * 1.0 * 0.85
    expect(screen.getByText('$255,000,000')).toBeInTheDocument()
  })

  it('renders at the $5B ceiling without the panel overflowing its own width', () => {
    render(<LandingPage navigate={navigate} />)
    fireEvent.change(track(), { target: { value: '1000' } })

    expect(amount()).toHaveValue('$5B')
    // 5,000,000,000 * 0.20 * 1.0 * 0.85. The compact readout is what
    // keeps the control legible at 360px — the figure below it is the
    // only long string, and it already wrapped before this session.
    expect(screen.getByText('$850,000,000')).toBeInTheDocument()
    for (const el of [amount(), track()]) {
      expect(el.getAttribute('style') || '').not.toMatch(/width:\s*\d{3,}px/)
    }
  })

  it('rejects unreadable input without moving the figure', () => {
    render(<LandingPage navigate={navigate} />)
    const before = screen.getByText('$3,400,000')
    expect(before).toBeInTheDocument()
    fireEvent.change(amount(), { target: { value: 'abc' } })
    fireEvent.blur(amount())
    expect(screen.getByText('$3,400,000')).toBeInTheDocument()
    expect(amount()).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('LandingPage — I2/I3: canonical + OG/Twitter meta on the one indexable page', () => {
  it('sets a canonical link and OG/Twitter meta pointed at PUBLIC_AUDIT_BASE_URL, cleaned up on unmount', () => {
    const { unmount } = render(<LandingPage navigate={navigate} />)

    const canonical = document.querySelector('link[rel="canonical"]')
    expect(canonical).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/`)
    expect(document.querySelector('meta[property="og:url"]')).toHaveAttribute('content', `${PUBLIC_AUDIT_BASE_URL}/`)
    expect(document.querySelector('meta[property="og:title"]')).toBeInTheDocument()
    expect(document.querySelector('meta[name="twitter:card"]')).toHaveAttribute('content', 'summary_large_image')
    expect(document.title).toContain('Parleo Audit')

    // Part 3b: og:image + dimensions + alt, twitter:image.
    expect(document.querySelector('meta[property="og:image"]')).toHaveAttribute('content', OG_IMAGE_URL)
    expect(document.querySelector('meta[property="og:image:width"]')).toHaveAttribute('content', String(OG_IMAGE_WIDTH))
    expect(document.querySelector('meta[property="og:image:height"]')).toHaveAttribute('content', String(OG_IMAGE_HEIGHT))
    expect(document.querySelector('meta[property="og:image:alt"]')).toHaveAttribute('content', OG_IMAGE_ALT)
    expect(document.querySelector('meta[name="twitter:image"]')).toHaveAttribute('content', OG_IMAGE_URL)

    unmount()
    expect(document.querySelector('link[rel="canonical"]')).not.toBeInTheDocument()
    expect(document.querySelector('meta[property="og:title"]')).not.toBeInTheDocument()
    expect(document.querySelector('meta[property="og:image"]')).not.toBeInTheDocument()
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

describe('Leadgen session: landing TrueSync CTA opens RequestFormModal, not a parleo.io link', () => {
  it('"Talk to us about TrueSync" opens the modal with landing_truesync copy', () => {
    render(<LandingPage navigate={navigate} />)

    const trueSyncButton = screen.getByRole('button', { name: 'Talk to us about TrueSync' })
    fireEvent.click(trueSyncButton)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByText('TRUESYNC')).toBeInTheDocument()
    expect(within(dialog).getByText("Let's stop the leak.")).toBeInTheDocument()
    expect(within(dialog).getByPlaceholderText('Tell us about your loyalty program and deals…')).toBeInTheDocument()
  })

  // Cutover: this used to be able to say "the only parleo.io links are
  // the Wordmarks", because the audit tool lived on its own host and
  // every audit link pointed there. The canonical address is now
  // parleo.io/audit, so sample-report links are parleo.io links too
  // and counting them would be counting the wrong thing.
  //
  // The rule this test actually exists for is unchanged: no CTA may
  // hardcode a link to the marketing home. So it checks that the only
  // links to PARLEO_HOME_URL itself are the two Wordmarks, and that
  // every other parleo.io link is an audit URL composed from
  // PUBLIC_AUDIT_BASE_URL rather than a literal someone typed in.
  it('the only marketing-home links are the nav/footer Wordmark — no CTA button hardcodes one', () => {
    render(<LandingPage navigate={navigate} />)
    const hrefs = screen.queryAllByRole('link').map((a) => a.getAttribute('href') || '')

    const homeLinks = screen.queryAllByRole('link').filter((a) => a.getAttribute('href') === PARLEO_HOME_URL)
    expect(homeLinks).toHaveLength(2)
    for (const link of homeLinks) {
      expect(link).toHaveAttribute('aria-label', 'Parleo home')
    }

    for (const href of hrefs) {
      if (!href.includes('parleo.io')) continue
      if (href === PARLEO_HOME_URL) continue
      expect(href.startsWith(`${PUBLIC_AUDIT_BASE_URL}/`)).toBe(true)
    }
  })
})

describe('LandingPage — Wordmark links to parleo.io in chrome, not in the sample card', () => {
  it('the nav and footer Wordmark are both links, opening in a new tab', () => {
    render(<LandingPage navigate={navigate} />)
    const links = screen.getAllByRole('link', { name: 'Parleo home' })
    expect(links).toHaveLength(2)
    for (const link of links) {
      expect(link).toHaveAttribute('href', 'https://parleo.io')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })

  it('the Hero sample-report card\'s Wordmark is NOT wrapped in a "Parleo home" link — it depicts a report, not chrome', () => {
    render(<LandingPage navigate={navigate} />)
    // Three PARLEO wordmarks render: nav, footer, and the Hero's dark
    // sample-card preview — only the first two are inside a home link.
    const parleoTexts = screen.getAllByText('PARLEO')
    expect(parleoTexts).toHaveLength(3)
    const wrappedInHomeLink = parleoTexts.filter((el) => el.closest('a[aria-label="Parleo home"]'))
    expect(wrappedInHomeLink).toHaveLength(2)
  })
})
