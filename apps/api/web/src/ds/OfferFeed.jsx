/**
 * Merchant Offer Feed: structured offers with freshness, channel, agent
 * readability. Ported from the exported design-system bundle
 * (components/artifacts/OfferFeed.jsx) — same render tree, restored to
 * JSX, with one addition: the readable-label ternary only covered
 * seen/partial/else in the source (else read "Not readable" for both
 * invisible and any future state). B-6 adds a fourth honest state,
 * 'unmeasured' — sampling/blocked, not "we looked and it wasn't
 * there" — so it needs its own label, not to collapse into invisible's.
 */
import { Glyph } from './Glyph.jsx'
import { StatusChip } from './StatusChip.jsx'
import { StateChip } from './StateChip.jsx'

function readableLabel(readable) {
  if (readable === 'seen') return 'Agent-readable'
  if (readable === 'partial') return 'Partial'
  if (readable === 'unmeasured') return 'Unmeasured'
  return 'Not readable'
}

export function OfferFeed({ offers = [], style }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', ...style }}>
      {offers.map((o, i) => (
        <div key={i} className="lite-offerfeed-row" style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '12px 4px', borderBottom: i < offers.length - 1 ? '1px solid var(--hairline)' : 'none' }}>
          <span
            style={{
              width: 30,
              height: 30,
              borderRadius: 9,
              background: o.readable === 'seen' ? 'var(--blue-tint)' : 'var(--canvas-dim)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: o.readable === 'seen' ? 'var(--blue)' : 'var(--faint)',
              flexShrink: 0,
            }}
          >
            <Glyph name={o.glyph || 'tag'} size={14} />
          </span>
          <div className="lite-offerfeed-content" style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-strong)', letterSpacing: '-0.01em' }}>{o.name}</span>
              {o.value ? <span className="num" style={{ fontSize: 11.5, fontWeight: 640, color: 'var(--green)' }}>{o.value}</span> : null}
            </div>
            <div className="mono-label" style={{ fontSize: 11, color: 'var(--faint)', marginTop: 2.5 }}>
              {o.channel}{o.eligibility ? `, ${o.eligibility}` : ''}
            </div>
          </div>
          {/* Grouped (rather than two direct flex children, as before) so
              RM5's phone override can drop both chips to their own line
              — a single flex-basis:100% on this wrapper — without
              touching the outer row's gap math: the wrapper's own
              internal gap matches the row's, so desktop spacing between
              content/freshness/state is pixel-identical either way. */}
          <div className="lite-offerfeed-chips" style={{ display: 'flex', alignItems: 'center', gap: 13, flexShrink: 0 }}>
            {o.freshness ? (
              <StatusChip tone={o.freshness === 'live' ? 'live' : o.freshness === 'stale' ? 'warning' : 'neutral'} size="sm">
                {o.freshness}
              </StatusChip>
            ) : null}
            <StateChip state={o.readable || 'seen'} size="sm">{readableLabel(o.readable)}</StateChip>
          </div>
        </div>
      ))}
    </div>
  )
}
