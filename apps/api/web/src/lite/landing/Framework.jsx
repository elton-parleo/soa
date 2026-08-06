/**
 * Framework — V4 design. Three pillar rows (Visibility, Accessibility,
 * True Value) each expanding into its dimension breakdown. C1: names
 * and point weights come from scanDimensionsRegistry.js, the same
 * registry the report's methodology section uses — never a local
 * literal. The little 5-segment fill bar per dimension is derived from
 * weight relative to the heaviest dimension in the whole framework
 * (share_of_mentions, 25pts), not copied pixel values from the mock.
 * READ THE FRAMEWORK link stays behind showFrameworkLink (default off
 * — no methodology deep-dive page exists yet).
 */
import { Glyph, MonoTag, SectionHeading } from '../../ds/index.js'
import { DIMENSIONS, PILLAR_ORDER, PILLAR_NAMES, PILLAR_WEIGHTS, PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE } from './scanDimensionsRegistry.js'

const PILLAR_ICON = { [PILLAR_VISIBILITY]: 'eye', [PILLAR_ACCESSIBILITY]: 'globe', [PILLAR_TRUE_VALUE]: 'tag' }
const PILLAR_SUBHEAD = {
  [PILLAR_VISIBILITY]: 'Are you in the room when shoppers ask?',
  [PILLAR_ACCESSIBILITY]: 'Can agents get in, and parse what you sell?',
  [PILLAR_TRUE_VALUE]: 'Does the value behind your price survive into the answer?',
}
const DIMENSION_BLURB = {
  share_of_mentions: 'Your share of every brand mention in the answers.',
  recommendation_strength: 'Named first and endorsed, or listed in passing.',
  agent_access: 'robots.txt, bot blocks, sitemap resolution.',
  catalog_context: 'Product and Offer markup, identifiers, completeness.',
  protocol_feed: 'llms.txt, MCP, a UCP profile at the known endpoint.',
  price_truth: 'Can agents state your real price, and do they.',
  member_value: 'Can agents see what members get, and do they say it.',
  deal_citability: 'Do live promotions survive into answers.',
  value_protocols: 'Can your value execute inside agent checkout. Almost no store declares anything here yet.',
}

const GLOBAL_MAX_WEIGHT = Math.max(...DIMENSIONS.map((d) => d.weight))

function fillCount(weight) {
  return Math.min(5, Math.max(1, Math.round((weight / GLOBAL_MAX_WEIGHT) * 5)))
}

function DimensionTile({ dim, blue }) {
  const filled = fillCount(dim.weight)
  const fillColor = blue ? 'var(--blue)' : 'var(--text-strong)'
  return (
    <div style={{ minWidth: 0, padding: '14px 16px 13px', borderRadius: 12, background: blue ? 'rgba(1,102,255,.05)' : 'var(--canvas-dim)', display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-strong)', letterSpacing: '-0.01em', lineHeight: 1.25 }}>{dim.name}</span>
        <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 680, color: blue ? 'var(--blue)' : 'var(--text)', flexShrink: 0 }}>{dim.weight}</span>
      </div>
      <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
        {Array.from({ length: 5 }, (_, i) => (
          <i key={i} style={{ display: 'block', flex: 1, height: 3, borderRadius: 2, background: i < filled ? fillColor : 'var(--hairline)' }} />
        ))}
      </div>
      <span style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5, marginTop: 'auto' }}>{DIMENSION_BLURB[dim.code]}</span>
    </div>
  )
}

function PillarRow({ pillar }) {
  const dims = DIMENSIONS.filter((d) => d.pillar === pillar)
  const weight = PILLAR_WEIGHTS[pillar]
  const isTrueValue = pillar === PILLAR_TRUE_VALUE
  const cols = pillar === PILLAR_VISIBILITY ? 2 : pillar === PILLAR_ACCESSIBILITY ? 3 : 2
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '250px 1fr',
        gap: 26,
        alignItems: 'start',
        padding: '24px 26px',
        borderRadius: 16,
        background: 'var(--surface)',
        boxShadow: 'var(--shadow-card)',
        outline: isTrueValue ? '1.5px solid var(--blue)' : undefined,
        outlineOffset: isTrueValue ? -1.5 : undefined,
      }}
    >
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 34, height: 34, borderRadius: 10, background: isTrueValue ? 'var(--blue)' : 'rgba(1,102,255,.09)', flexShrink: 0 }}>
            <Glyph name={PILLAR_ICON[pillar]} size={18} color={isTrueValue ? '#fff' : 'var(--blue)'} />
          </span>
          <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 720, color: isTrueValue ? 'var(--blue)' : 'var(--text-strong)', letterSpacing: '-0.025em' }}>
            {weight}<span style={{ fontSize: 13, fontWeight: 600, color: 'var(--faint)' }}> pts</span>
          </span>
        </div>
        <div style={{ fontSize: 19, fontWeight: 700, color: 'var(--text-strong)', letterSpacing: '-0.018em', marginTop: 13 }}>{PILLAR_NAMES[pillar]}</div>
        <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.5, marginTop: 5 }}>{PILLAR_SUBHEAD[pillar]}</div>
        {isTrueValue && (
          <div style={{ marginTop: 13 }}>
            <MonoTag tone="blue">ONLY PARLEO MEASURES THIS</MonoTag>
          </div>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols},1fr)`, gap: 10, alignItems: 'stretch' }}>
        {dims.map((d) => <DimensionTile key={d.code} dim={d} blue={isTrueValue} />)}
      </div>
    </div>
  )
}

export function Framework({ showFrameworkLink = false }) {
  return (
    <section style={{ padding: '60px 24px 12px' }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <SectionHeading
          size="sm"
          accent="scores 100 points."
          body="Three pillars, eight dimensions, one straight sum. Every point traces back to something an agent could or could not read on your site. Two pillars are table stakes. The third decides whether your value reaches the answer."
        >
          The Share of Algorithm framework
        </SectionHeading>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 30 }}>
          {PILLAR_ORDER.map((pillar) => <PillarRow key={pillar} pillar={pillar} />)}
        </div>
        <p style={{ margin: '20px 0 0', maxWidth: 760, fontSize: 13.5, lineHeight: 1.65, color: 'var(--muted)', textWrap: 'pretty' }}>
          <b style={{ color: 'var(--text-strong)', fontWeight: 640 }}>Every True Value dimension is dual-lens:</b> what your pages encode, and what agents actually said. The visibility tools you already pay for measure the first pillar only.
        </p>
        {showFrameworkLink && (
          <a href="#" className="mono-label" style={{ display: 'inline-block', fontSize: 9.5, color: 'var(--blue)', marginTop: 14, borderBottom: '1px dashed rgba(1,102,255,.4)', paddingBottom: 2 }}>
            READ THE FRAMEWORK →
          </a>
        )}
      </div>
    </section>
  )
}
