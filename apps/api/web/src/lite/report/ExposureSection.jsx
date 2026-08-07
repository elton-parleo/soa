/**
 * S7: exposure. F6 — imports the same computeExposure module the
 * landing estimator uses, so the two surfaces can never disagree about
 * the model.
 *
 * Part 4: the cause breakdown is no longer three static, run-agnostic
 * weights — it's up to 3 reasons apps/api/app/services/exposure_
 * reasons.py selected from THIS run's own measured gaps, each carrying
 * an impact_weight (that reason's share of the selected group's
 * severity). Dollar amounts still have to be computed here, live,
 * because revenue/AI-share are sliders the visitor can drag — the
 * server can't know the split in dollars, only the proportions.
 */
import { Glyph, LeakageEstimator } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { useCollapsible } from './Collapsible.jsx'
import { REVENUE_SLIDER_MIN, REVENUE_SLIDER_MAX, AI_SHARE_SLIDER_MIN, AI_SHARE_SLIDER_MAX, formatCurrency } from '../liteDerive.js'
import { isPartialRead } from './reportDerive.js'

// 4c: reasons.impact_weight * exposure, independently rounded, can
// drift a dollar or two from the modeled total — the remainder goes to
// the largest share so the displayed lines always sum to exactly what
// the hero number above them shows.
export function splitExposureDollars(exposure, reasons) {
  if (!reasons.length) return []
  const total = Math.round(exposure)
  const rounded = reasons.map((r) => Math.round(exposure * r.impact_weight))
  const drift = total - rounded.reduce((sum, v) => sum + v, 0)
  if (drift !== 0) {
    let largestIdx = 0
    for (let i = 1; i < reasons.length; i++) {
      if (reasons[i].impact_weight > reasons[largestIdx].impact_weight) largestIdx = i
    }
    rounded[largestIdx] += drift
  }
  return rounded
}

export function ExposureSection({ report, revenue, onRevenueChange, aiSharePct, onAiShareChange, exposure, open, onToggle }) {
  const [adjOpen, toggleAdj] = useCollapsible()
  const reasons = report?.pillars?.exposure_reasons || []
  const dollars = splitExposureDollars(exposure, reasons)
  const causes = reasons.map((r, i) => ({
    label: r.text,
    value: dollars[i],
    display: `≈ ${formatCurrency(dollars[i])}/yr · modeled`,
  }))
  const partialRead = isPartialRead(report?.pillars || {}, report?.scan?.degraded_reason)

  return (
    <ReportSection
      id="exp" eyebrow="EXPOSURE · MODELED, NOT MEASURED" title="What the gap is worth"
      extra={(
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <a href="#expmodel" className="mono-label" style={{ fontSize: 9, color: 'var(--blue)' }}>HOW WE MODEL THIS ↓</a>
          <button
            type="button" onClick={toggleAdj} aria-expanded={adjOpen}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'var(--blue-soft)', border: '1px solid rgba(1,102,255,.24)', borderRadius: 999, padding: '8px 14px 8px 11px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.11em', color: 'var(--blue)', fontWeight: 640 }}
          >
            <Glyph name={adjOpen ? 'x' : 'plus'} size={12} color="var(--blue)" />ADJUST ASSUMPTIONS
          </button>
        </div>
      )}
      open={open} onToggle={onToggle}
    >
      {adjOpen && (
        <div className="lite-exposure-adjust-grid" style={{ marginTop: 18, background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '16px 18px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 22 }}>
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
        <LeakageEstimator
          total={formatCurrency(exposure).replace('$', '')} prefix="$" suffix=" / year" label="Modeled annual exposure"
          causes={causes}
          provenance={causes.length ? ["the split across reasons is modeled from this run's own measured gaps, not independently measured"] : undefined}
        />
      </div>

      <div id="expmodel" style={{ marginTop: 16, scrollMarginTop: 26, fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
        <b style={{ color: 'var(--text-strong)' }}>The model:</b> revenue × AI-assisted share × value-invisibility factor. {formatCurrency(revenue)} annual revenue, {aiSharePct}% AI-assisted share. The invisibility factor comes from your True Value result. The Full Analysis replaces this model with measured price gaps.
      </div>
      {partialRead && (
        <div className="mono-label" style={{ marginTop: 10, fontSize: 8.5, color: 'var(--faint)' }}>
          ▨ SPLIT MODELED FROM THIS RUN'S OWN MEASURED GAPS · UNREAD DIMENSIONS CONTRIBUTE NOTHING
        </div>
      )}
    </ReportSection>
  )
}
