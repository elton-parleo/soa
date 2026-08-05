/**
 * METHODOLOGY — section [2]. Stage 26 rebuild: replaces the walkthrough
 * layout (browser-chrome code panel + illustrative answer + sticky
 * pillar ledger, Stages 17-25) with the exhibit-tabs design from
 * design-refs/methodology-v4-exhibit-tabs-mock.html — THE EXAMPLE (one
 * grouped, dashed-border exhibit: seen/said cards joined by an arrow
 * labeled with the query count) above THE FRAMEWORK (one card whose
 * header IS the score equation as a tab bar, opening into per-pillar
 * accordion rows, closing with a static verdict-gate teaching demo).
 *
 * Every dimension name/one-liner/points/chip/caption/visual comes from
 * scanDimensionsRegistry.js (oneLiner/chips/scoredCaption/visualKind+
 * params) — the same registry-backed module the live report uses.
 * Nothing scoring-relevant is hard-coded here; only the exhibit's own
 * illustrative content (a Brooklinen bedding example, verbatim from the
 * mock — deliberately a different demo brand than the rest of the
 * landing page's Allbirds convention, matching the mock exactly) and the
 * gate demo's two static teaching states are free text.
 *
 * Interaction model (replaces the old click-any-element activation):
 * the equation tab bar is a real ARIA tablist (arrow-key navigable);
 * each pillar's accordion is one-open-at-a-time, independently per
 * panel; opening a True Value row (price_truth/member_value/
 * deal_citability/value_protocols) pulses its mapped exhibit elements
 * twice via the XMAP below, then stops — reduced-motion skips both the
 * pulse and the fill-width transition, rendering final states.
 */
import { Fragment, useEffect, useRef, useState } from 'react'
import { SectionHeader } from '../liteTheme.jsx'
import {
  SCORER_VERSION,
  LITE_QUERY_COUNT,
  DIMENSIONS,
  DIMENSIONS_BY_CODE,
  PILLAR_NAMES,
  PILLAR_QUESTIONS,
  PILLAR_ORDER,
  PILLAR_WEIGHTS,
  PILLAR_TRUE_VALUE,
  TOTAL_MAX,
} from './scanDimensionsRegistry.js'
import { reportUrl } from '../publicUrls.js'

// B3: no dedicated sample-report route exists yet — points at a real,
// complete, scorer_version-4 report already in the database (the
// Allbirds run generated during this stage's own live verification),
// not a placeholder. Single constant per B3. Rebased onto
// PUBLIC_AUDIT_BASE_URL (U1) by the audit.parleo.io migration — this
// link opens in a new tab, so it must be absolute regardless of which
// host is currently rendering the landing page.
export const SAMPLE_REPORT_URL = reportUrl('1710d72d74ee4a2ea6c9884c72cc96e2')

// True Value dimensions with an exhibit cross-highlight target (D3's
// XMAP) — pt/mv/dc each map to a seen-card line + a said-card mark;
// value_protocols maps to the seen-card capability badge row instead
// (it has no said-card mark at all, per its encode-only design).
const PULSE_CODES = ['price_truth', 'member_value', 'deal_citability', 'value_protocols']
const PULSE_DURATION_MS = 2000 // two 1s animation iterations, then stop

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  ))
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener ? mq.addEventListener('change', onChange) : mq.addListener(onChange)
    return () => {
      mq.removeEventListener ? mq.removeEventListener('change', onChange) : mq.removeListener(onChange)
    }
  }, [])
  return reduced
}

// ─── THE EXAMPLE ──────────────────────────────────────────────────────

function CapBadge({ label, ok }) {
  return (
    <span className="lite-anatomy-x-badge">
      {label} <i className={ok ? 'lite-anatomy-x-badge-ok' : ''}>{ok ? '✓' : '✕'}</i>
    </span>
  )
}

function Exhibit({ pulsingCode }) {
  const pulsePt = pulsingCode === 'price_truth'
  const pulseMv = pulsingCode === 'member_value'
  const pulseDc = pulsingCode === 'deal_citability'
  const pulseVp = pulsingCode === 'value_protocols'

  return (
    <div className="lite-anatomy-exhibit">
      <span className="lite-anatomy-ex-tab">EXAMPLE</span>
      <span className="lite-anatomy-ex-q">"best sheets worth the money?"</span>
      <div className="lite-anatomy-ex-grid">
        <div className="lite-anatomy-seen">
          <span className="lite-anatomy-ex-hd">WHAT THE AGENT SAW ON YOUR SITE</span>
          <span className={`lite-anatomy-kv${pulsePt ? ' lite-anatomy-pulse' : ''}`}>
            "price": <b>269.00</b> · "priceCurrency": "USD"
          </span>
          <span className={`lite-anatomy-kv${pulseMv ? ' lite-anatomy-pulse' : ''}`}>
            "priceSpecification": {'{'} "price": <b>228.65</b>,
          </span>
          <span className={`lite-anatomy-kv${pulseMv ? ' lite-anatomy-pulse' : ''}`}>
            &nbsp;&nbsp;tier: <b>"Comfort Crew"</b> {'}'}
          </span>
          <span className={`lite-anatomy-kv${pulseDc ? ' lite-anatomy-pulse' : ''}`}>
            "discount": "25% BUNDLE" · valid <b>2026-08-01</b>
          </span>
          <span className={`lite-anatomy-badges${pulseVp ? ' lite-anatomy-pulse' : ''}`}>
            <CapBadge label="robots" ok /> <CapBadge label="llms.txt" ok /> <CapBadge label="UCP·DISCOUNT" ok />
          </span>
        </div>
        <div className="lite-anatomy-ex-mid" aria-hidden="true">
          <svg width="30" height="60" viewBox="0 0 30 60">
            <path d="M6 6 C 26 18, 26 42, 6 54" fill="none" stroke="var(--text-2)" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M6 54 l 8 -2 M6 54 l 2 -8" fill="none" stroke="var(--text-2)" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <span className="lite-anatomy-ex-mid-label">{LITE_QUERY_COUNT} QUERIES</span>
        </div>
        <div className="lite-anatomy-said">
          <span className="lite-anatomy-ex-hd">WHAT THE AGENT SAID</span>
          "<mark className="lite-anatomy-mark-v">Brooklinen</mark> is <mark className="lite-anatomy-mark-v">a top pick</mark> — the Luxe set runs{' '}
          <mark className={pulsePt ? 'lite-anatomy-pulse' : ''}>$269</mark>,{' '}
          <mark className={pulseMv ? 'lite-anatomy-pulse' : ''}>members pay $228.65</mark>.{' '}
          <mark className={pulseDc ? 'lite-anatomy-pulse' : ''}>Bundles 25% off through Sunday</mark>.
          <span className="lite-anatomy-ghost">…most stores never get this sentence</span>
        </div>
      </div>
      <div className="lite-anatomy-ex-cap">
        <b>BLUE = YOUR VALUE IN THE ANSWER.</b> EVERY HIGHLIGHT IS SCORED BELOW.
      </div>
    </div>
  )
}

// ─── Visual kinds (D1) ─────────────────────────────────────────────────

function Meter({ open, params }) {
  const pct = open ? params.fillPct : 0
  return (
    <div className="lite-anatomy-meter">
      <div className="lite-anatomy-meter-fill" style={{ width: `${pct}%` }} />
      <span className="lite-anatomy-meter-tick" style={{ left: `${params.tickPct}%` }} />
      <span className="lite-anatomy-meter-tlab" style={{ left: `${params.tickPct}%` }}>{params.tickLabel}</span>
    </div>
  )
}

function Ladder({ params }) {
  return (
    <div className="lite-anatomy-ladder">
      {params.bands.map((b) => (
        <span key={b.label} className={`lite-anatomy-ladder-band${b.hot ? ' lite-anatomy-ladder-band--hot' : ''}`}>
          <i>{b.label}</i>{b.value}
        </span>
      ))}
    </div>
  )
}

function Pips({ params }) {
  return (
    <div className="lite-anatomy-pips">
      {params.pips.map((p) => (
        <span key={p.label} className={`lite-anatomy-pip${p.ok ? '' : ' lite-anatomy-pip--off'}`}>
          <i>{p.ok ? '✓' : '✕'}</i>{p.label}
        </span>
      ))}
    </div>
  )
}

function ProductGrid({ params }) {
  const cells = Array.from({ length: params.total }, (_, i) => i < params.ok)
  return (
    <div className="lite-anatomy-grid4">
      {cells.map((ok, i) => (
        <i key={i} className={ok ? 'lite-anatomy-grid4-ok' : ''} />
      ))}
    </div>
  )
}

function Duo({ open, params }) {
  const leftPct = open ? params.leftPct : 0
  const rightPct = open ? params.rightPct : 0
  return (
    <div>
      <div className="lite-anatomy-duo">
        <span className="lite-anatomy-duo-l"><div style={{ width: `${leftPct}%` }} /></span>
        <span className="lite-anatomy-duo-mid">⇄</span>
        <span className="lite-anatomy-duo-r"><div style={{ width: `${rightPct}%` }} /></span>
      </div>
      <div className="lite-anatomy-duolab">
        <b>{params.leftLabel}</b><b>{params.rightLabel}</b>
      </div>
    </div>
  )
}

function ScoredVisual({ open, dim }) {
  switch (dim.visualKind) {
    case 'meter': return <Meter open={open} params={dim.visualParams} />
    case 'ladder': return <Ladder params={dim.visualParams} />
    case 'pips': return <Pips params={dim.visualParams} />
    case 'grid': return <ProductGrid params={dim.visualParams} />
    case 'duo': return <Duo open={open} params={dim.visualParams} />
    default: return null
  }
}

function ScoredCaption({ segments }) {
  return (
    <span className="lite-anatomy-mcap">
      {segments.map((seg, i) => (seg.bold ? <b key={i}>{seg.text}</b> : <span key={i}>{seg.text}</span>))}
    </span>
  )
}

function Chip({ chip }) {
  if (typeof chip === 'string') return <span className="lite-anatomy-chip">{chip}</span>
  return <span className="lite-anatomy-chip lite-anatomy-chip--advisory">{chip.label}</span>
}

// ─── THE FRAMEWORK ─────────────────────────────────────────────────────

function DimensionRow({ dim, open, onToggle }) {
  return (
    <div className="lite-anatomy-dim">
      <button
        type="button"
        className="lite-anatomy-dim-head"
        aria-expanded={open}
        onClick={() => onToggle(dim.code)}
      >
        <span className="lite-anatomy-dim-car" aria-hidden="true">{open ? '−' : '+'}</span>
        <span className="lite-anatomy-dim-nm">{dim.name}</span>
        <span className="lite-anatomy-dim-one">{dim.oneLiner}</span>
        <span className="lite-anatomy-dim-pt">{dim.weight}</span>
        {dim.siteOnly && <span className="lite-anatomy-vtag">SITE ONLY</span>}
      </button>
      {open && (
        <div className="lite-anatomy-dbody">
          <div className="lite-anatomy-cell">
            <span className="lite-anatomy-cell-k">{dim.leftLabel}</span>
            {dim.visualKind === 'pips'
              ? <Pips params={dim.visualParams} />
              : (
                <div className="lite-anatomy-sig">
                  {dim.chips.map((c, i) => <Chip key={i} chip={c} />)}
                </div>
              )}
          </div>
          <div className="lite-anatomy-cell">
            <span className="lite-anatomy-cell-k">{dim.rightLabel}</span>
            {dim.visualKind !== 'pips' && <ScoredVisual open={open} dim={dim} />}
            <ScoredCaption segments={dim.scoredCaption} />
          </div>
        </div>
      )}
    </div>
  )
}

function PillarPanel({ pillar, openCode, onToggle }) {
  const codes = DIMENSIONS.filter((d) => d.pillar === pillar).map((d) => d.code)
  const classes = ['lite-anatomy-panel']
  if (pillar === PILLAR_TRUE_VALUE) classes.push('lite-anatomy-panel--tv')
  return (
    <div className={classes.join(' ')} role="tabpanel" id={`lite-anatomy-panel-${pillar}`} aria-labelledby={`lite-anatomy-tab-${pillar}`}>
      {codes.map((code) => (
        <DimensionRow
          key={code}
          dim={DIMENSIONS_BY_CODE[code]}
          open={openCode === code}
          onToggle={(c) => onToggle(pillar, c)}
        />
      ))}
    </div>
  )
}

const TAB_ORDER = PILLAR_ORDER

function EquationTabBar({ activeTab, onSelect }) {
  const tabRefs = useRef({})

  function onKeyDown(e) {
    const idx = TAB_ORDER.indexOf(activeTab)
    let next = null
    if (e.key === 'ArrowRight') next = TAB_ORDER[(idx + 1) % TAB_ORDER.length]
    else if (e.key === 'ArrowLeft') next = TAB_ORDER[(idx - 1 + TAB_ORDER.length) % TAB_ORDER.length]
    if (next) {
      e.preventDefault()
      onSelect(next)
      tabRefs.current[next]?.focus()
    }
  }

  return (
    <div className="lite-anatomy-eq" role="tablist" aria-label="Score composition — tap a pillar" onKeyDown={onKeyDown}>
      {TAB_ORDER.map((pillar, i) => (
        <Fragment key={pillar}>
          <button
            ref={(el) => { tabRefs.current[pillar] = el }}
            type="button"
            role="tab"
            id={`lite-anatomy-tab-${pillar}`}
            aria-selected={activeTab === pillar}
            aria-controls={`lite-anatomy-panel-${pillar}`}
            tabIndex={activeTab === pillar ? 0 : -1}
            className={`lite-anatomy-eq-btn${activeTab === pillar ? ' lite-anatomy-eq-btn--on' : ''}${pillar === PILLAR_TRUE_VALUE ? ' lite-anatomy-eq-btn--tv' : ''}`}
            onClick={() => onSelect(pillar)}
          >
            <span className="lite-anatomy-eq-t">{PILLAR_NAMES[pillar].toUpperCase()}</span>
            <span className="lite-anatomy-eq-n">{PILLAR_WEIGHTS[pillar]}</span>
            <span className="lite-anatomy-eq-q">{PILLAR_QUESTIONS[pillar]}</span>
          </button>
          {i < TAB_ORDER.length - 1 && <span className="lite-anatomy-eq-plus" aria-hidden="true">+</span>}
        </Fragment>
      ))}
      <span className="lite-anatomy-eq-plus" aria-hidden="true">=</span>
      <div className="lite-anatomy-eq-total">
        <span className="lite-anatomy-eq-t">SCORE</span>
        <span className="lite-anatomy-eq-n">{TOTAL_MAX}</span>
        <span className="lite-anatomy-eq-q">simple sum</span>
      </div>
    </div>
  )
}

const GATE_STATES = {
  encoded: {
    label: 'VALUE ENCODED', score: 82, chip: 'AGENT-READY', tone: 'ok',
    text: [
      { text: "This store's value is readable and cited:", bold: true },
      { text: ' 82, agent-ready.', bold: false },
    ],
  },
  zero: {
    label: 'ZERO TRUE VALUE', score: 42, chip: 'NOT AGENT-READY', tone: 'no',
    text: [
      { text: 'Same store, zero True Value: 42 — and it fails the readiness check.', bold: true },
      { text: " Visibility alone can't pass.", bold: false },
    ],
  },
}

function GateDemo() {
  const [state, setState] = useState('encoded')
  const g = GATE_STATES[state]
  return (
    <div className="lite-anatomy-gate">
      <div className="lite-anatomy-tog">
        {Object.entries(GATE_STATES).map(([key, s]) => (
          <button
            key={key}
            type="button"
            className={state === key ? 'lite-anatomy-tog-on' : ''}
            aria-pressed={state === key}
            onClick={() => setState(key)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <span className="lite-anatomy-gsc">{g.score}</span>
      <span className={`lite-anatomy-gch lite-anatomy-gch--${g.tone}`}>{g.chip}</span>
      <span className="lite-anatomy-gtx">
        {g.text.map((seg, i) => (seg.bold ? <b key={i}>{seg.text}</b> : <span key={i}>{seg.text}</span>))}
      </span>
    </div>
  )
}

// ─── Root ──────────────────────────────────────────────────────────────

export function AnatomyOfAnAnswer() {
  const [activeTab, setActiveTab] = useState(PILLAR_ORDER[0])
  const [openByPillar, setOpenByPillar] = useState({})
  const [pulsingCode, setPulsingCode] = useState(null)
  const reducedMotion = usePrefersReducedMotion()
  const pulseTimer = useRef(null)

  useEffect(() => () => { if (pulseTimer.current) clearTimeout(pulseTimer.current) }, [])

  function toggleRow(pillar, code) {
    const willOpen = openByPillar[pillar] !== code
    setOpenByPillar((prev) => ({ ...prev, [pillar]: willOpen ? code : null }))
    if (willOpen && PULSE_CODES.includes(code) && !reducedMotion) {
      setPulsingCode(code)
      if (pulseTimer.current) clearTimeout(pulseTimer.current)
      pulseTimer.current = setTimeout(() => setPulsingCode(null), PULSE_DURATION_MS)
    } else if (!willOpen) {
      setPulsingCode(null)
      if (pulseTimer.current) clearTimeout(pulseTimer.current)
    }
  }

  return (
    <section className="lite-landing-section" id="methodology">
      <SectionHeader label="METHODOLOGY" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.4vw, 44px)', marginBottom: 8 }}>
        How your score <span className="lite-serif-italic">works</span>.
      </h2>
      <p className="lite-body lite-muted" style={{ fontSize: 14, maxWidth: 520, lineHeight: 1.5, marginBottom: 28 }}>
        We ask ChatGPT {LITE_QUERY_COUNT} shopper questions about you, and read your store the way agents do.
        Tap anything below to see how points are earned.
      </p>

      <Exhibit pulsingCode={pulsingCode} />

      <div className="lite-anatomy-fw-wrap">
        <span className="lite-anatomy-fw-tab">THE FRAMEWORK</span>
        <div className="lite-anatomy-fw">
          <EquationTabBar activeTab={activeTab} onSelect={setActiveTab} />
          {TAB_ORDER.map((pillar) => (
            <div key={pillar} style={{ display: activeTab === pillar ? 'block' : 'none' }}>
              <PillarPanel pillar={pillar} openCode={openByPillar[pillar] || null} onToggle={toggleRow} />
            </div>
          ))}
          <GateDemo />
        </div>
      </div>

      <div className="lite-anatomy-foot">
        <span className="lite-mono lite-muted" style={{ fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
          {LITE_QUERY_COUNT} queries · ChatGPT only · deterministic · sample, not a category study
        </span>
        <a href={SAMPLE_REPORT_URL} target="_blank" rel="noopener noreferrer" className="lite-pill lite-pill--solid">
          View a sample report →
        </a>
      </div>

      {/* Registry version marker for the P0 CI gate — not user-visible
          copy. Tracks the real scan/report scorer, straight off the
          same registry this whole section renders from. */}
      <span data-scorer-version={SCORER_VERSION} style={{ display: 'none' }} aria-hidden="true" />
    </section>
  )
}
