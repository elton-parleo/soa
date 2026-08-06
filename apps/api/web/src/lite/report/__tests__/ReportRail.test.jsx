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

function renderRail(report) {
  return render(
    <ReportRail
      report={report}
      primaryEntityName="Acme Co"
      exposure={1000}
      active="score"
      focus={false}
      allLabel="Expand all"
      onToggleAll={() => {}}
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
