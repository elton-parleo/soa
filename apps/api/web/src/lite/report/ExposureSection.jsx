/**
 * S7: exposure. F6 — imports the same computeExposure module the
 * landing estimator uses, so the two surfaces can never disagree about
 * the model. Cause-bar weights below are the same illustrative ratios
 * the mock itself applies to its own modeled total (not a measured
 * breakdown either there or here) — modeled-not-measured framing stays
 * true in both places.
 */
import { Glyph, LeakageEstimator } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { useDetailToggle } from './HowItsScored.jsx'
import { REVENUE_SLIDER_MIN, REVENUE_SLIDER_MAX, AI_SHARE_SLIDER_MIN, AI_SHARE_SLIDER_MAX, formatCurrency } from '../liteDerive.js'

const CAUSE_WEIGHTS = [
  { label: 'Price never quoted in answers', weight: 345 / 775, color: 'var(--blue)' },
  { label: 'Catalog unreadable to agents', weight: 230 / 775, color: 'var(--blue-lite)' },
  { label: 'No value declared at checkout', weight: 200 / 775, color: 'rgba(127,176,255,.42)' },
]

export function ExposureSection({ revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure, open, onToggle }) {
  const [adjOpen, toggleAdj] = useDetailToggle()
  const causes = CAUSE_WEIGHTS.map((c) => ({ ...c, value: Math.round(exposure * c.weight), display: formatCurrency(Math.round(exposure * c.weight)) }))

  return (
    <ReportSection
      id="exp" eyebrow="EXPOSURE · MODELED, NOT MEASURED" title="What the gap is worth"
      extra={(
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <a href="#expmodel" className="mono-label" style={{ fontSize: 9, color: 'var(--blue)' }}>HOW WE MODEL THIS ↓</a>
          <button
            type="button" onClick={toggleAdj}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'var(--blue-soft)', border: '1px solid rgba(1,102,255,.24)', borderRadius: 999, padding: '8px 14px 8px 11px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.11em', color: 'var(--blue)', fontWeight: 640 }}
          >
            <Glyph name={adjOpen ? 'x' : 'plus'} size={12} color="var(--blue)" />ADJUST ASSUMPTIONS
          </button>
        </div>
      )}
      open={open} onToggle={onToggle}
    >
      {adjOpen && (
        <div style={{ marginTop: 18, background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '16px 18px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22 }}>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 12.5, color: 'var(--muted)', marginBottom: 8 }}>
              <span>Annual revenue</span><b className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-strong)' }}>{formatCurrency(revenue)}</b>
            </div>
            <input type="range" min={REVENUE_SLIDER_MIN} max={REVENUE_SLIDER_MAX} step={REVENUE_SLIDER_MIN} value={revenue} onChange={(e) => onRevenueChange(+e.target.value)} aria-label="Annual revenue" style={{ width: '100%', accentColor: 'var(--blue)' }} />
          </div>
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 12.5, color: 'var(--muted)', marginBottom: 8 }}>
              <span>AI-assisted share of sales</span><b className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-strong)' }}>{aiSharePct}%</b>
            </div>
            <input type="range" min={AI_SHARE_SLIDER_MIN} max={AI_SHARE_SLIDER_MAX} value={aiSharePct} onChange={(e) => onAiShareChange(+e.target.value)} aria-label="AI-assisted share of sales" style={{ width: '100%', accentColor: 'var(--blue)' }} />
          </div>
          <div className="mono-label" style={{ gridColumn: '1/-1', fontSize: 8.5, color: 'var(--faint)', lineHeight: 1.7 }}>
            ADJUST THE INPUTS AND THE MODEL FOLLOWS · THE FULL ANALYSIS REPLACES THE MODEL WITH MEASURED PRICE GAPS
          </div>
        </div>
      )}

      <div style={{ marginTop: 20 }}>
        <LeakageEstimator total={formatCurrency(exposure).replace('$', '')} prefix="$" suffix=" / year" label="Modeled annual exposure" causes={causes} />
      </div>

      <div id="expmodel" style={{ marginTop: 16, scrollMarginTop: 26, fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
        <b style={{ color: 'var(--text-strong)' }}>The model:</b> revenue × AI-assisted share × value-invisibility factor. {formatCurrency(revenue)} annual revenue, {aiSharePct}% AI-assisted share. The invisibility factor comes from your True Value result. The Full Analysis replaces this model with measured price gaps.
      </div>
    </ReportSection>
  )
}
