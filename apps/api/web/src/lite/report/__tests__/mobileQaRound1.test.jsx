/**
 * Mobile QA round 1 — structural checks that the phone-only CSS
 * (src/lite/__tests__/mobileCss.test.js) has something real to target:
 * renders each fixed component and asserts the classNames actually land
 * on the right elements, and that nothing crashes on the blocked-run
 * shape defect 2 was specifically re-checked against live. This is the
 * DOM-contract half; the CSS-text assertions are the rule half; live
 * viewport correctness (no horizontal scroll, visual stacking) was
 * verified directly against the dev server in a real browser this
 * session — see the PR description.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import '@testing-library/jest-dom'

import { ReportSection } from '../ReportSection.jsx'
import { TrueValueSection } from '../TrueValueSection.jsx'
import { MetricRow } from '../../../ds/MetricRow.jsx'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

describe('defect 1 — ReportSection header structure', () => {
  it('the header row and the extra/score/collapse group both carry their targetable classNames', () => {
    const { container } = render(
      <ReportSection
        id="exp" eyebrow="EXPOSURE · MODELED, NOT MEASURED" title="What the gap is worth"
        extra={<a href="#x">HOW WE MODEL THIS</a>}
        score="40/100"
        open onToggle={() => {}}
      >
        <div>body</div>
      </ReportSection>
    )
    const header = container.querySelector('.lite-report-section-header')
    expect(header).toBeInTheDocument()
    const controls = header.querySelector('.lite-report-section-controls')
    expect(controls).toBeInTheDocument()
    // extra, the score span, and the collapse button must all still be
    // reachable inside .lite-report-section-controls — display:contents
    // must not have hidden or dropped any of them.
    expect(controls).toHaveTextContent('HOW WE MODEL THIS')
    expect(controls).toHaveTextContent('40/100')
    expect(controls.querySelector('button')).toBeInTheDocument()
  })

  it('renders correctly with no extra and no score too (Visibility/Accessibility shape) — the controls group must not assume extra is present', () => {
    const { container } = render(
      <ReportSection id="acc" eyebrow="PILLAR 02 · ACCESSIBILITY" title="Agents can knock" score="8/20" open onToggle={() => {}}>
        <div>body</div>
      </ReportSection>
    )
    expect(container.querySelector('.lite-report-section-controls')).toBeInTheDocument()
    expect(container.querySelector('.lite-report-section-controls')).toHaveTextContent('8/20')
  })
})

describe('defect 2 — True Value pillar header structure', () => {
  function _report(overrides = {}) {
    return {
      composite: 40,
      offers: null,
      product_image_url: null,
      product_name: null,
      pillars: {
        state: 'scored',
        verdict: 'not_agent_ready',
        tv_pct: 12,
        member_value_na: false,
        true_value: {
          dimensions: [
            { code: 'price_truth', name: 'Price Truth', earned: 2, max: 12, na: false, blocked: false, seen: { earned: 2, max: 5, na: false }, said: { earned: 0, max: 7, na: false }, checks: [] },
          ],
        },
        ...overrides.pillars,
      },
      ...overrides,
    }
  }

  it('the header carries lite-tv-header/-title/-meta/-score/-points-row/-collapse, all reachable, on a normal scored run', () => {
    const { container } = render(<TrueValueSection report={_report()} open={false} onToggle={() => {}} />)
    expect(container.querySelector('.lite-tv-header')).toBeInTheDocument()
    expect(container.querySelector('.lite-tv-header-title')).toBeInTheDocument()
    const meta = container.querySelector('.lite-tv-header-meta')
    expect(meta).toBeInTheDocument()
    const score = meta.querySelector('.lite-tv-header-score')
    expect(score).toBeInTheDocument()
    expect(score.querySelector('.lite-tv-header-points-row')).toBeInTheDocument()
    expect(meta.querySelector('.lite-tv-header-collapse')).toBeInTheDocument()
    expect(meta.querySelector('.lite-tv-header-collapse button')).toBeInTheDocument()
  })

  it('renders the same header structure on the blocked-run shape (0/0, no numeric-value assumption) without crashing or dropping any of the header classNames', () => {
    const blockedPillars = {
      state: 'unverified',
      verdict: null,
      tv_pct: null,
      member_value_na: false,
      true_value: {
        dimensions: [
          { code: 'price_truth', name: 'Price Truth', earned: 0, max: 12, na: false, blocked: true, seen: { earned: 0, max: 5, na: false, blocked: true }, said: { earned: 0, max: 7, na: false } },
        ],
      },
    }
    const { container, getByText } = render(
      <TrueValueSection report={_report({ composite: null, offers: null, pillars: blockedPillars })} open={false} onToggle={() => {}} />
    )
    expect(container.querySelector('.lite-tv-header')).toBeInTheDocument()
    expect(container.querySelector('.lite-tv-header-meta')).toBeInTheDocument()
    expect(container.querySelector('.lite-tv-header-collapse')).toBeInTheDocument()
    expect(getByText('0')).toBeInTheDocument()
    expect(getByText('/0')).toBeInTheDocument()
  })
})

describe('defect 3 — MetricRow structure (sample-report preview\'s real fix)', () => {
  it('the row and every item carry their targetable classNames', () => {
    const items = [
      { value: 25, suffix: '/40', label: 'Visibility' },
      { value: 8, suffix: '/20', label: 'Accessibility' },
      { value: 7, suffix: '/40', label: 'True Value' },
    ]
    const { container } = render(<MetricRow items={items} size={34} />)
    expect(container.querySelector('.lite-metric-row')).toBeInTheDocument()
    const rowItems = container.querySelectorAll('.lite-metric-row-item')
    expect(rowItems).toHaveLength(3)
  })

  it('CycleDashboard (the authed app\'s own MetricRow caller, outside .lite-root) is unaffected — the phone override only exists inside theme.css, which CycleDashboard never imports', () => {
    // Structural guarantee, not a CycleDashboard render test: confirms
    // the classNames are plain, unconditional additions (not gated on
    // any .lite-root ancestor check in MetricRow.jsx itself), so the
    // ONLY thing that could make them do anything outside the audit
    // surface is a stray theme.css import — which CycleDashboard.jsx
    // does not have.
    const cycleDashboardSrc = fs.readFileSync(path.join(__dirname, '../../../components/CycleDashboard.jsx'), 'utf8')
    expect(cycleDashboardSrc).not.toMatch(/theme\.css/)
  })
})
