/**
 * Unreachable-host follow-up (Lululemon, request 138): the status page
 * renders DegradedRunBanner with no partial-read pointer, so the
 * unreachable run's own registry body has to reach it here too — the
 * same words the report's finding section uses, never the old generic
 * "we couldn't finish reading your site" line.
 */
import React from 'react'
import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { DegradedRunBanner, _fetchProbeSentence } from '../DegradedRunBanner.jsx'
import { FAILURE_POINT_COPY, resolveFailurePointBody } from '../report/reportContent.js'

const PROBE_OPENED_HOME = { outcome: 'opened_no_price', agent_could_access: true, kind: 'store_root' }

describe('DegradedRunBanner — unreachable', () => {
  it('renders the unreachable registry body, naming the vendor DNS recognized', () => {
    const { container } = render(
      <DegradedRunBanner status="failed" degradedReason="unreachable" bannerFacts={{}} edgeVendor="akamai" />,
    )
    expect(container.textContent).toContain(resolveFailurePointBody(FAILURE_POINT_COPY.unreachable.body, {}, 'akamai'))
    expect(container.textContent).toContain("Akamai's bot protection")
    expect(container.textContent).not.toContain("We couldn't finish reading your site this time")
  })

  it('says the site is up when ChatGPT opened it', () => {
    expect(_fetchProbeSentence({ fetch_probe: PROBE_OPENED_HOME }, 'unreachable', 'failed')).toBe(
      ' ChatGPT opened your homepage fine — your site is up; it just never answered a reader like ours.',
    )
  })

  it('a failed run with no reason keeps the generic line', () => {
    const { container } = render(<DegradedRunBanner status="failed" degradedReason={null} bannerFacts={{}} />)
    expect(container.textContent).toContain("We couldn't finish reading your site this time")
  })
})
