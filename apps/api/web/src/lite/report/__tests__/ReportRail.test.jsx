/**
 * Logo feature, Parts 1c/4: the rail's brand mark is provenance-pure —
 * BrandLogo's `src` tier is fed straight from report.brand_icon_url (the
 * merchant's own crawled icon, never a third-party guess for the
 * primary brand), with report.store_domain as the fallback identity for
 * the provider/favicon tiers when the crawl found no icon at all (a
 * blocked or root-failed run). The target's own domain is always known
 * from the submitted URL, independent of whether the crawl succeeded, so
 * a blocked run still degrades to a real favicon or a clean monogram —
 * never a broken frame.
 */
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'

vi.mock('../../../ds/logoProvider.js', () => ({
  logoProviderUrl: vi.fn(() => null),
  LOGO_PROVIDER_CONFIGURED: false,
}))

import { ReportRail } from '../ReportRail.jsx'

function _report(overrides = {}) {
  return {
    brand_icon_url: null,
    store_domain: 'acme.com',
    composite: 72,
    pillars: {
      state: 'scored',
      verdict: 'not_agent_ready',
      visibility: { dimensions: [] },
      accessibility: { dimensions: [] },
      true_value: { dimensions: [] },
    },
    ...overrides,
  }
}

function renderRail(report, extraProps = {}) {
  return render(
    <ReportRail
      report={report}
      primaryEntityName="Acme Co"
      exposure={1000}
      active="score"
      focus={false}
      allLabel="Expand all"
      onToggleAll={() => {}}
      {...extraProps}
    />
  )
}

describe('ReportRail brand mark provenance', () => {
  it('passes the crawled icon as the src tier when present', () => {
    const { container } = renderRail(_report({ brand_icon_url: 'https://acme.com/icon.png' }))
    expect(container.querySelector('img').src).toBe('https://acme.com/icon.png')
  })

  it('falls back to the store domain (never a name-based guess) when the crawl found no icon', () => {
    const { container } = renderRail(_report({ brand_icon_url: null, store_domain: 'acme.com' }))
    expect(container.querySelector('img').src).toBe('https://www.google.com/s2/favicons?domain=acme.com&sz=64')
  })

  it('renders a clean monogram, never a broken frame, on a blocked run with no icon and no domain', () => {
    const { container, getByRole } = renderRail(_report({ brand_icon_url: null, store_domain: null }))
    expect(container.querySelector('img')).not.toBeInTheDocument()
    expect(getByRole('img', { name: 'Acme Co logo' })).toBeInTheDocument()
  })
})

describe('ReportRail — Share report button placement', () => {
  it('renders full-width, directly below "Run your free audit", when a token is given', () => {
    const { getByRole } = renderRail(_report(), { token: 'tok-rail-123' })
    const runAudit = getByRole('link', { name: /Run your free audit/ })
    const share = getByRole('button', { name: 'Share report' })
    expect(share).toBeInTheDocument()
    // DOM order: the CTA anchor comes before the share button.
    // eslint-disable-next-line no-bitwise
    expect(runAudit.compareDocumentPosition(share) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(share.style.width).toBe('100%')
  })

  it('renders nothing when no token is available (defensive — the full report always has one)', () => {
    const { queryByRole } = renderRail(_report(), { token: undefined })
    expect(queryByRole('button', { name: 'Share report' })).not.toBeInTheDocument()
  })

  it('renders for a partial-read run (state !== "scored") the same as a fully scored one — same token either way', () => {
    const partialReport = _report({ pillars: { ...(_report().pillars), state: 'unverified' } })
    const { getByRole } = renderRail(partialReport, { token: 'tok-partial' })
    expect(getByRole('button', { name: 'Share report' })).toBeInTheDocument()
  })
})
