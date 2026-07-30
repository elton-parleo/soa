/**
 * METHODOLOGY — section [2] (internally "anatomy of an answer"),
 * replaces the old two-family (35/65-point) Methodology section
 * (Stage 17; regrouped into per-pillar ledger cards and re-labeled in
 * Stage 18). Walks a visitor through one real shopper question: what
 * the agent's crawl actually sees (browser-chrome markup card, real
 * schema.org JSON-LD), then what the agent says back (an illustrative
 * answer with inline marks), then how that maps onto the pillar score
 * (sticky, pillar-grouped ledger).
 *
 * Stage 24: the ledger now renders the v4 FRAMEWORK PREVIEW —
 * apps/api/web/src/lite/landing/scanDimensionsV4Preview.js — a
 * marketing-only preview of the framework the scan will move to next;
 * the live scan/report stay on v3 (soa_shared/scan_dimensions.py via
 * scanDimensionsRegistry.js) the entire time this is live (see that
 * module's own header comment, and its own S3 in the stage brief). The
 * hidden `data-scorer-version` marker below is the one thing still
 * sourced from the REAL v3 registry — it is an existing P0 CI gate
 * tracking actual scorer reality, unrelated to this preview.
 *
 * Each ledger row expands (accordion, one open at a time) into a
 * three-microsection detail panel — WHAT IT IS / HOW WE MEASURE / HOW
 * IT'S SCORED — populated entirely from the preview module's per-
 * dimension whatItIs/howMeasured/howScored fields, never hard-coded
 * copy in this file.
 *
 * One activation model, keyed by dimension code (I1): clicking/
 * Enter-Space-ing any mark, markup line, chrome badge, or ledger row
 * activates that dimension everywhere — matching elements share a
 * `dim` prop compared against `activeDims`. The ghost sentence
 * activates the three True Value dimensions the illustrative sentence
 * actually marks; every other activation is a single dimension.
 * `openDim` tracks which ONE ledger row has its detail panel expanded
 * (accordion — one open at a time), defaulting to member_value on
 * mount (I2).
 *
 * Value Protocols (Part 3) is the fourth True Value row: it is
 * encode-only, so it has NO mark in the illustrative answer — its
 * cross-highlight target instead is a new capability badge in the
 * browser-chrome row ("UCP · DISCOUNT ✓"), the honest visual for a
 * declared-but-unspoken capability.
 *
 * Demo brand: Allbirds (the existing placeholder brand across the
 * widget — see LiteForm.jsx), footwear category. The agent answer is
 * an illustration, not a quoted/attributed real query result (C5).
 */
import { useState } from 'react'
import { SectionHeader } from '../liteTheme.jsx'
import { SCORER_VERSION } from './scanDimensionsRegistry.js'
import {
  DIMENSIONS,
  DIMENSIONS_BY_CODE,
  PILLAR_NAMES,
  PILLAR_ORDER,
  PILLAR_TRUE_VALUE,
} from './scanDimensionsV4Preview.js'

const DIM = DIMENSIONS_BY_CODE

// The three True Value dimensions the illustrative sentence actually
// marks (I1). Deliberately NOT derived from pillar membership — Value
// Protocols is also a True Value dimension but has no sentence span at
// all (Part 3, V1), so this fixed set is a content decision, not a
// registry fact.
const TRUE_VALUE_SENTENCE_CODES = ['price_truth', 'member_value', 'deal_citability']

// Pillar -> member dimension codes, in registry order. Membership
// itself is static (a dimension's pillar assignment doesn't change),
// but each pillar's point TOTAL is recomputed from live DIM[code].weight
// at render time in PillarCard below — never cached — so perturbing a
// registry weight moves the rendered header total (Change 1's test).
const PILLAR_GROUPS = PILLAR_ORDER.map((pillar) => ({
  pillar,
  codes: DIMENSIONS.filter((d) => d.pillar === pillar).map((d) => d.code),
}))

// ─── Static illustration data (free text — not registry-derived) ────

const JSONLD_LINES = [
  { text: '{', dim: null },
  { text: '  "@context": "https://schema.org",', dim: null },
  { text: '  "@type": "Product",', dim: 'catalog_context' },
  { text: '  "name": "Wool Runner",', dim: 'catalog_context' },
  { text: '  "gtin13": "00012345678905",', dim: 'catalog_context' },
  { text: '  "brand": { "@type": "Brand", "name": "Allbirds" },', dim: 'catalog_context' },
  { text: '  "offers": {', dim: null },
  { text: '    "@type": "Offer",', dim: null },
  { text: '    "price": "98.00",', dim: 'price_truth' },
  { text: '    "priceCurrency": "USD",', dim: 'price_truth' },
  { text: '    "availability": "https://schema.org/InStock",', dim: null },
  { text: '    "priceValidUntil": "2026-12-31",', dim: 'deal_citability' },
  { text: '    "priceSpecification": {', dim: 'member_value' },
  { text: '      "@type": "UnitPriceSpecification",', dim: 'member_value' },
  { text: '      "price": "88.00",', dim: 'member_value' },
  { text: '      "priceCurrency": "USD",', dim: 'member_value' },
  { text: '      "membershipPointsEarned": 50', dim: 'member_value' },
  { text: '    }', dim: 'member_value' },
  { text: '  }', dim: null },
  { text: '}', dim: null },
]

const CHROME_BADGES = [
  { key: 'robots', label: 'robots ✓', dim: 'agent_access' },
  { key: 'sitemap', label: 'sitemap ✓', dim: 'agent_access' },
  { key: 'llms', label: 'llms.txt ✓', dim: 'protocol_feed' },
  { key: 'mcp', label: 'MCP ✓', dim: 'protocol_feed' },
  { key: 'ucp', label: 'UCP ✓', dim: 'protocol_feed' },
  // Part 3 (V1): Value Protocols' only cross-highlight target — it has
  // no answer mark, so this badge is the sole L2 element for it.
  { key: 'ucp-discount', label: 'UCP · DISCOUNT ✓', dim: 'value_protocols' },
]

// ─── Small building blocks ───────────────────────────────────────────

function Mark({ dim, active, tone, onActivate, children, flag }) {
  const classes = ['lite-anatomy-mark', `lite-anatomy-mark--${tone}`]
  if (active) classes.push('lite-anatomy-mark--active')
  return (
    <button
      type="button"
      className={classes.join(' ')}
      aria-pressed={active}
      onClick={() => onActivate([dim], dim)}
    >
      {children}
      {flag !== undefined && <span className="lite-anatomy-flag" aria-hidden="true">{flag}</span>}
    </button>
  )
}

function ChromeBadge({ dim, active, onActivate, children }) {
  return (
    <span
      role="button"
      tabIndex={0}
      className={`lite-chip lite-chip--${active ? 'accent' : 'outline'}`}
      aria-pressed={active}
      onClick={() => onActivate([dim], dim)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onActivate([dim], dim) }
      }}
      style={{ cursor: 'pointer' }}
    >
      {children}
    </span>
  )
}

function CodeLine({ line, active, onActivate }) {
  if (!line.dim) {
    return <span className="lite-anatomy-code-line" aria-hidden="true">{line.text}</span>
  }
  const activeClass = active
    ? (line.dim === 'catalog_context' ? ' lite-anatomy-code-line--active-cc' : ' lite-anatomy-code-line--active-tv')
    : ''
  return (
    <button
      type="button"
      className={`lite-anatomy-code-line${activeClass}`}
      aria-pressed={active}
      onClick={() => onActivate([line.dim], line.dim)}
    >
      {line.text}
    </button>
  )
}

// Part 2 (L1): the three-microsection detail panel — WHAT IT IS / HOW
// WE MEASURE / HOW IT'S SCORED — populated entirely from the preview
// module's per-dimension fields. True Value's seen/said split renders
// inside HOW IT'S SCORED, computed live from dim.seenMax/saidMax (never
// baked into the howScored copy itself) so it still moves under the
// existing perturbation-test discipline.
function DimensionDetailPanel({ dim }) {
  const hasSplit = dim.seenMax !== null && dim.saidMax !== null
  return (
    <span className="lite-anatomy-detail-panel" style={{ display: 'block' }}>
      <span className="lite-anatomy-detail-section" style={{ display: 'block' }}>
        <span className="lite-anatomy-detail-label">WHAT IT IS</span>
        <span className="lite-anatomy-detail-body" style={{ display: 'block' }}>{dim.whatItIs}</span>
      </span>
      <span className="lite-anatomy-detail-section" style={{ display: 'block' }}>
        <span className="lite-anatomy-detail-label">HOW WE MEASURE</span>
        <span className="lite-anatomy-detail-checklist" style={{ display: 'block' }}>
          {dim.howMeasured.map((check) => (
            <span key={check} className="lite-anatomy-detail-check" style={{ display: 'block' }}>✓ {check}</span>
          ))}
        </span>
      </span>
      <span className="lite-anatomy-detail-section" style={{ display: 'block' }}>
        <span className="lite-anatomy-detail-label">HOW IT'S SCORED</span>
        <span className="lite-anatomy-detail-body" style={{ display: 'block' }}>{dim.howScored}</span>
        {hasSplit && (
          <span className="lite-anatomy-seen-said" style={{ display: 'block' }}>
            SEEN {dim.seenMax} · SAID {dim.saidMax}
          </span>
        )}
      </span>
    </span>
  )
}

function LedgerRow({ code, active, open, onActivate }) {
  const dim = DIM[code]
  const classes = ['lite-anatomy-ledger-row']
  if (active) classes.push('lite-anatomy-ledger-row--active')
  return (
    <button
      type="button"
      className={classes.join(' ')}
      aria-expanded={open}
      onClick={() => onActivate([code], code)}
    >
      <span className="lite-anatomy-ledger-row-head">
        <span style={{ fontWeight: 700, fontSize: 13.5 }}>{dim.name}</span>
        <span className="lite-mono" style={{ fontSize: 12, fontWeight: 700 }}>
          {dim.weight} pts
        </span>
      </span>
      {open && <DimensionDetailPanel dim={dim} />}
    </button>
  )
}

function PillarCard({ pillar, codes, activeDims, openDim, onActivate }) {
  // Stage 18 (Change 1): the header total is summed from live
  // DIM[code].weight on every render, not read from a cached export —
  // see PILLAR_GROUPS above for why that matters for the perturbation
  // test.
  const total = codes.reduce((sum, code) => sum + DIM[code].weight, 0)
  const isTrueValue = pillar === PILLAR_TRUE_VALUE
  const classes = ['lite-anatomy-pillar-card']
  if (isTrueValue) classes.push('lite-anatomy-pillar-card--tv')
  return (
    <div className={classes.join(' ')}>
      {isTrueValue && <span className="lite-anatomy-float-tag">ONLY WE SCORE THIS</span>}
      <div className="lite-anatomy-pillar-header">
        <span>{PILLAR_NAMES[pillar]}</span>
        <span>{total}</span>
      </div>
      {codes.map((code) => (
        <LedgerRow
          key={code}
          code={code}
          active={activeDims.includes(code)}
          open={openDim === code}
          onActivate={onActivate}
        />
      ))}
    </div>
  )
}

export function AnatomyOfAnAnswer() {
  const [activeDims, setActiveDims] = useState(['member_value']) // I2: thesis dimension greets the visitor
  const [openDim, setOpenDim] = useState('member_value')

  function activate(codes, primary) {
    setActiveDims(codes)
    setOpenDim(primary)
  }

  function activateGhost() {
    activate(TRUE_VALUE_SENTENCE_CODES, 'member_value')
  }

  const isActive = (code) => activeDims.includes(code)

  return (
    <section className="lite-landing-section" id="methodology">
      <SectionHeader label="METHODOLOGY" />
      <h2 className="lite-display-headline" style={{ fontSize: 'clamp(28px, 4.5vw, 48px)', marginBottom: 32 }}>
        Every tool checks that you're <span className="lite-serif-italic">named</span>.
      </h2>

      <div className="lite-anatomy-grid">
        {/* ── Left: the walkthrough ── */}
        <div>
          <div className="lite-anatomy-question">
            "are allbirds wool runners worth it — and is there a better price?"
          </div>

          <div className="lite-card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="lite-browser-chrome">
              <span className="lite-chrome-dots">
                <span className="lite-chrome-dot" /><span className="lite-chrome-dot" /><span className="lite-chrome-dot" />
              </span>
              <ChromeBadge dim="agent_access" active={isActive('agent_access')} onActivate={activate}>
                <span className="lite-chrome-url-pill" style={{ background: 'none', padding: 0 }}>
                  allbirds.com — as agents read it
                </span>
              </ChromeBadge>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '12px 14px', borderBottom: '1px solid var(--line)' }}>
              {CHROME_BADGES.map((b) => (
                <ChromeBadge key={b.key} dim={b.dim} active={isActive(b.dim)} onActivate={activate}>
                  {b.label}
                </ChromeBadge>
              ))}
            </div>
            <div className="lite-anatomy-code-panel">
              {JSONLD_LINES.map((line, i) => (
                <CodeLine key={i} line={line} active={Boolean(line.dim) && isActive(line.dim)} onActivate={activate} />
              ))}
            </div>
          </div>

          <div className="lite-anatomy-seam">
            <span aria-hidden="true">↓</span> SHOPPER QUERIES
          </div>

          <div className="lite-body lite-muted" style={{ fontSize: 12, fontStyle: 'italic', marginBottom: 8 }}>
            Illustrative agent answer — not a live query result.
          </div>

          <div className="lite-anatomy-answer">
            <Mark dim="share_of_mentions" tone="visibility" active={isActive('share_of_mentions')} onActivate={activate} flag={`V·${DIM.share_of_mentions.weight}`}>
              Allbirds Wool Runners
            </Mark>{' '}
            are frequently mentioned in shopping answers and often come up as{' '}
            <Mark dim="recommendation_strength" tone="visibility" active={isActive('recommendation_strength')} onActivate={activate} flag={`V·${DIM.recommendation_strength.weight}`}>
              a top pick
            </Mark>{' '}
            for a comfortable everyday sneaker. They're{' '}
            <Mark dim="price_truth" tone="true-value" active={isActive('price_truth')} onActivate={activate} flag={`TV·${DIM.price_truth.weight}`}>
              listed at $98
            </Mark>
            .{' '}
            <Mark dim="member_value" tone="true-value" active={isActive('member_value')} onActivate={activate} flag={`TV·${DIM.member_value.weight}`}>
              Members save $10 and earn reward points on this pair
            </Mark>
            , and{' '}
            <Mark dim="deal_citability" tone="true-value" active={isActive('deal_citability')} onActivate={activate} flag={`TV·${DIM.deal_citability.weight}`}>
              a seasonal discount is currently running on select colors
            </Mark>
            .
            <button
              type="button"
              className={`lite-anatomy-ghost${TRUE_VALUE_SENTENCE_CODES.every(isActive) ? ' lite-anatomy-ghost--active' : ''}`}
              aria-pressed={TRUE_VALUE_SENTENCE_CODES.every(isActive)}
              onClick={activateGhost}
            >
              …the sentence most stores never get
              <span className="lite-anatomy-ghost-skip-flag">SKIPPED</span>
            </button>
          </div>
        </div>

        {/* ── Right: sticky pillar ledger, grouped by pillar (Change 1) ── */}
        <div className="lite-anatomy-ledger">
          {PILLAR_GROUPS.map(({ pillar, codes }) => (
            <PillarCard
              key={pillar}
              pillar={pillar}
              codes={codes}
              activeDims={activeDims}
              openDim={openDim}
              onActivate={activate}
            />
          ))}
        </div>
      </div>

      <div className="lite-strip" style={{ marginTop: 32 }}>
        <span className="lite-body" style={{ fontSize: 13.5 }}>
          Every tool checks that you're named. We score what agents can see — and whether the blue sentence exists.
        </span>
      </div>

      <div className="lite-mono lite-muted" style={{ fontSize: 11.5, marginTop: 16 }}>
        12 queries · 1 platform · deterministic · sample, not a category study.
      </div>
      {/* Registry version marker for the P0 CI gate — not user-visible
          copy, and NOT the v4 preview: this tracks the real scan/report
          scorer (still v3) so the gate keeps meaning what it always
          has, independent of this section's preview content above. */}
      <span data-scorer-version={SCORER_VERSION} style={{ display: 'none' }} aria-hidden="true" />
    </section>
  )
}
