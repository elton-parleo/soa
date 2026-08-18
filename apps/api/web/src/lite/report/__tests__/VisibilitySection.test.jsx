/**
 * VisibilitySection — shared between the lite report (24 queries,
 * always LITE_QUERY_COUNT) and the Full Analysis report (a real,
 * variable query count read from the payload). Two bug-fix regressions
 * covered here:
 *  - the "PILLAR 01 · VISIBILITY · N QUERIES" header (and the "How
 *    it's scored" panel copy) must use the real queryCount prop, not
 *    always the lite-only LITE_QUERY_COUNT constant — a 50-query Full
 *    Analysis cycle used to render "24 QUERIES".
 *  - a scope of just the primary (no competitor set — the NewCycleFlow
 *    launch bug this fixes) must render an honest "not measurable"
 *    state, never a fabricated-looking 100% share.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { VisibilitySection } from '../VisibilitySection.jsx'

function _report({ shareOfMentions } = {}) {
  return {
    pillars: {
      visibility: {
        score: 62.5, max: 100,
        dimensions: [
          { code: 'share_of_mentions', name: 'Share of Mentions', earned: 18, max: 25, na: false, evidence: [] },
          { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 5, max: 7, na: false, evidence: [] },
        ],
      },
    },
    visibility_breakdown: {
      share_of_mentions: shareOfMentions ?? [
        { entity: 'Acme', is_primary: true, share_pct: 35, domain: null },
        { entity: 'Rival Co', is_primary: false, share_pct: 65, domain: null },
      ],
    },
  }
}

describe('VisibilitySection — query count sourced from the payload', () => {
  it('defaults to the lite query count (24) when no queryCount prop is passed', () => {
    render(<VisibilitySection report={_report()} open onToggle={() => {}} />)
    expect(screen.getByText(/PILLAR 01 · VISIBILITY · 24 QUERIES/)).toBeInTheDocument()
  })

  it('renders the real cycle query count when passed (Full Analysis, e.g. 50 queries)', () => {
    render(<VisibilitySection report={_report()} open onToggle={() => {}} queryCount={50} />)
    expect(screen.getByText(/PILLAR 01 · VISIBILITY · 50 QUERIES/)).toBeInTheDocument()
    expect(screen.queryByText(/24 QUERIES/)).not.toBeInTheDocument()
  })
})

describe('VisibilitySection — honest state for a scope of just the primary', () => {
  it('renders the real percentage and progress bar with a real competitor set', () => {
    render(<VisibilitySection report={_report()} open onToggle={() => {}} />)
    expect(screen.getByText(/35% of all brand mentions were you/)).toBeInTheDocument()
    expect(screen.getByText('YOU · 35%')).toBeInTheDocument()
  })

  it('renders "not measurable" — never a 100% share — when the scope has no competitors', () => {
    const report = _report({ shareOfMentions: [{ entity: 'Acme', is_primary: true, share_pct: 100, domain: null }] })
    render(<VisibilitySection report={report} open onToggle={() => {}} />)
    expect(screen.getByText('Not measurable — no competitor set for this cycle.')).toBeInTheDocument()
    expect(screen.queryByText(/100% of all brand mentions/)).not.toBeInTheDocument()
    expect(screen.queryByText('YOU · 100%')).not.toBeInTheDocument()
  })

  it('renders "not measurable" for a genuinely empty share_of_mentions too', () => {
    const report = _report({ shareOfMentions: [] })
    render(<VisibilitySection report={report} open onToggle={() => {}} />)
    expect(screen.getByText('Not measurable — no competitor set for this cycle.')).toBeInTheDocument()
  })
})
