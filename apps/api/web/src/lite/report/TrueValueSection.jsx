/**
 * S5: True Value centerpiece. AgentAnswer is deferred this stage — the
 * parsed-page card is full width instead of sharing a row with it (no
 * empty column, no placeholder). H1: the card renders only when
 * report.offers exists (a successful parse this run); otherwise an
 * honest banner takes its place, image slot included.
 */
import { useState } from 'react'
import { Glyph, MonoTag, StateChip, OfferFeed, DarkPanel } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { HowItsScoredButton, HowItsScoredPanel, useDetailToggle } from './HowItsScored.jsx'
import { dimByCode, pillarEarnedMax, anyTrueValueEncodeBlocked, trueValueNotMeasurableCount, isAgentReady } from './reportDerive.js'
import { DIMENSIONS_BY_CODE, VERDICT_COMPOSITE_THRESHOLD, VERDICT_TRUE_VALUE_RATIO_THRESHOLD } from '../landing/scanDimensionsRegistry.js'

const GROUP_META = {
  seen: { label: 'CAN QUOTE', glyph: 'check', color: 'var(--green)', bg: null },
  partial: { label: "CAN'T COUNT", glyph: 'filter', color: 'var(--amber-deep)', bg: 'var(--amber-tint)' },
  invisible: { label: 'INVISIBLE', glyph: 'x', color: 'var(--red-deep)', bg: 'var(--red-tint)' },
}

function ParsedPageCard({ offers, productImageUrl }) {
  const groups = { seen: [], partial: [], invisible: [] }
  for (const o of offers) {
    if (groups[o.readable]) groups[o.readable].push(o)
  }
  const price = offers.find((o) => o.name === 'List price')
  const availability = offers.find((o) => o.name === 'Availability')

  return (
    <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px', display: 'grid', gridTemplateColumns: productImageUrl ? '1fr 140px' : '1fr', gap: 18 }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Glyph name="doc" size={14} color="var(--faint)" />
          <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)' }}>YOUR PAGE, AS PARSED</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 12 }}>
          {price && <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 19, fontWeight: 700, color: 'var(--text-strong)' }}>{price.value}</span>}
          {availability && <StateChip state={availability.readable} variant="chip" size="sm">{availability.value}</StateChip>}
        </div>

        {['seen', 'partial', 'invisible'].map((state) => {
          const rows = groups[state]
          if (!rows.length) return null
          const meta = GROUP_META[state]
          return (
            <div key={state} style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--hairline)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Glyph name={meta.glyph} size={13} color={meta.color} />
                <span className="mono-label" style={{ fontSize: 9.5, color: meta.color }}>{meta.label}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {rows.map((o) => (
                  <div
                    key={o.name}
                    style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10,
                      background: meta.bg || 'var(--surface)', border: meta.bg ? undefined : '1px solid var(--hairline)',
                      borderRadius: 8, padding: '8px 10px',
                    }}
                  >
                    <span style={{ fontSize: 12.5, color: 'var(--text-strong)', fontWeight: 600 }}>{o.name}: {o.value}</span>
                    <i className="mono-label" style={{ fontStyle: 'normal', fontSize: 8, color: meta.color, whiteSpace: 'nowrap' }}>{o.channel}</i>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
      {productImageUrl && (
        <div>
          <img
            src={productImageUrl}
            alt="Product, as parsed from the merchant's own markup"
            loading="lazy"
            referrerPolicy="no-referrer"
            style={{ width: '100%', aspectRatio: '1 / 1', objectFit: 'contain', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--hairline)' }}
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
          <div style={{ fontSize: 10, color: 'var(--faint)', marginTop: 6, lineHeight: 1.4 }}>The merchant's own image, from the same markup we scored.</div>
        </div>
      )}
    </div>
  )
}

function ParsedPageHonestBanner() {
  return (
    <div style={{ background: 'var(--surface-warm)', border: '1px dashed var(--border-strong)', borderRadius: 14, padding: '20px 22px', textAlign: 'center' }}>
      <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6 }}>
        No product page parsed cleanly enough this run to show what an agent read — the dimension rows below still reflect what could be measured.
      </div>
    </div>
  )
}

function DualLensDim({ code, iconGlyph, dim, oneLiner, open, onToggle, howText }) {
  const reg = DIMENSIONS_BY_CODE[code]
  const seen = dim?.seen
  const said = dim?.said
  return (
    <div style={{ borderTop: '1px solid var(--hairline)', padding: '20px 0 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 11, flexWrap: 'wrap', marginBottom: 14 }}>
        <Glyph name={iconGlyph} size={15} color="var(--text-strong)" />
        <span style={{ fontSize: 16, fontWeight: 660, color: 'var(--text-strong)', letterSpacing: '-0.014em' }}>{reg.name}</span>
        <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, fontWeight: 680, color: 'var(--text-strong)' }}>
          {Math.round(dim?.earned ?? 0)}<span style={{ color: 'var(--faint)', fontWeight: 500 }}>/{reg.weight}</span>
        </span>
        <span style={{ fontSize: 13.5, color: 'var(--muted)' }}>{oneLiner}</span>
        <span style={{ marginLeft: 'auto' }}><HowItsScoredButton open={open} onClick={onToggle} /></span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <MeterHalf label="ON YOUR SITE" glyph="doc" sub={seen} blocked={seen?.blocked} />
        <MeterHalf label="IN ANSWERS" glyph="agent" sub={said} blocked={false} />
      </div>
      {open && <HowItsScoredPanel>{howText}</HowItsScoredPanel>}
    </div>
  )
}

function MeterHalf({ label, glyph, sub, blocked }) {
  const earned = sub?.earned ?? 0
  const max = sub?.max ?? 0
  const pct = max ? Math.min(100, (earned / max) * 100) : 0
  const zero = earned === 0
  const tone = blocked ? 'var(--faint)' : zero ? 'var(--red-deep)' : 'var(--text-strong)'
  const bg = blocked ? 'var(--canvas-dim)' : zero ? 'var(--red-tint)' : 'var(--surface-warm)'
  return (
    <div style={{ background: bg, border: `1px solid ${zero && !blocked ? 'rgba(239,67,67,.28)' : 'var(--border)'}`, borderRadius: 12, padding: '15px 17px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Glyph name={glyph} size={14} color={tone} />
        <span className="mono-label" style={{ fontSize: 9, color: tone }}>{label}</span>
        <span className="num" style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 700, color: tone }}>
          {blocked ? 'N/M' : `${Math.round(earned)}/${Math.round(max)}`}
        </span>
      </div>
      <div style={{ height: 8, background: blocked ? 'var(--canvas-dim)' : zero ? 'rgba(239,67,67,.16)' : 'var(--canvas-dim)', borderRadius: 4, marginTop: 13, overflow: 'hidden', position: 'relative' }}>
        {!blocked && !zero && <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct}%`, background: 'var(--ink)', borderRadius: 4 }} />}
      </div>
    </div>
  )
}

export function TrueValueSection({ report, open, onToggle }) {
  const pillars = report.pillars
  const dims = pillars.true_value?.dimensions || []
  const tv = pillarEarnedMax(pillars.true_value)
  const priceTruth = dimByCode(dims, 'price_truth')
  const memberValue = dimByCode(dims, 'member_value')
  const dealCitability = dimByCode(dims, 'deal_citability')
  const valueProtocols = dimByCode(dims, 'value_protocols')
  const notMeasurable = trueValueNotMeasurableCount(pillars)
  const encodeBlocked = anyTrueValueEncodeBlocked(pillars)

  const [ptOpen, togglePt] = useDetailToggle()
  const [mvOpen, toggleMv] = useDetailToggle()
  const [dcOpen, toggleDc] = useDetailToggle()
  const [vpOpen, toggleVp] = useDetailToggle()
  const [whyNaOpen, setWhyNaOpen] = useState(false)

  const offers = report.offers
  const unmeasuredOffers = (offers || []).filter((o) => o.readable === 'unmeasured').length

  const composite = report.composite
  const tvPct = report.pillars.tv_pct

  return (
    <div id="tv" style={{ borderRadius: 18, boxShadow: 'var(--shadow-elevated)', marginBottom: 16, scrollMarginTop: 26, overflow: 'hidden', border: '1.5px solid var(--blue)' }}>
      <DarkPanel pad="22px 28px 20px" radius={0} atmos>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 24 }}>
          <div style={{ maxWidth: 520 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
              <Glyph name="tag" size={14} color="var(--blue-lite)" />
              <span className="mono-label" style={{ fontSize: 10, color: 'var(--blue-lite)' }}>PILLAR 03 · TRUE VALUE</span>
              <MonoTag tone="blue">THE PILLAR ONLY PARLEO MEASURES</MonoTag>
            </div>
            <h2 style={{ fontSize: 25, fontWeight: 720, letterSpacing: '-0.024em', color: 'var(--dark-text)', margin: '13px 0 0', lineHeight: 1.15 }}>Your value leaks before it reaches the answer</h2>
            <div style={{ fontSize: 14, color: 'var(--dark-muted)', lineHeight: 1.6, marginTop: 10 }}>
              One SKU, as parsed from the page your markup reached, next to what agents actually read.
              {notMeasurable > 0 && ` ${notMeasurable} dimension${notMeasurable === 1 ? '' : 's'} not measurable this run.`}
            </div>
          </div>
          <div style={{ textAlign: 'right', flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, justifyContent: 'flex-end' }}>
              <span className="num" style={{ fontSize: 38, fontWeight: 720, letterSpacing: '-0.03em', color: 'var(--dark-text)', lineHeight: 1 }}>{Math.round(tv.earned)}</span>
              <span className="num" style={{ fontSize: 18, fontWeight: 500, color: 'var(--dark-faint)' }}>/{Math.round(tv.max)}</span>
            </div>
            <div className="mono-label" style={{ fontSize: 9, color: 'var(--blue-lite)', marginTop: 7 }}>POINTS EARNED</div>
            <div style={{ marginTop: 12 }}><HowItsScoredButton open={open} onClick={onToggle} /></div>
          </div>
        </div>
      </DarkPanel>

      {open && (
        <div className="sec-body" style={{ background: 'var(--surface)', padding: '24px 28px 26px' }}>
          {offers ? <ParsedPageCard offers={offers} productImageUrl={report.product_image_url} /> : <ParsedPageHonestBanner />}

          {offers && (
            <div style={{ marginTop: 16, background: 'var(--surface-warm)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 14 }}>
                <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>WHAT AGENTS COULD READ OF YOUR VALUE</span>
                {unmeasuredOffers > 0 && <span className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)' }}>{unmeasuredOffers} OF {offers.length} SIGNALS UNMEASURED</span>}
              </div>
              <OfferFeed offers={offers} />
            </div>
          )}

          <div style={{ marginTop: 26, borderTop: '1px solid var(--hairline)', paddingTop: 20 }}>
            {priceTruth && (
              <DualLensDim
                code="price_truth" iconGlyph="card" dim={priceTruth}
                oneLiner={encodeBlocked && priceTruth.blocked ? 'not measurable this run' : 'readable on your site, cited in answers'}
                open={ptOpen} onToggle={togglePt}
                howText="Encoding checks plus how often answers that name you state your price. A price behind sign-in doesn't exist to an agent."
              />
            )}

            {memberValue?.na ? (
              <div style={{ borderTop: '1px solid var(--hairline)', padding: '18px 0 20px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 15, fontWeight: 660, color: 'var(--text-strong)', letterSpacing: '-0.012em' }}>Member Value</span>
                  <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, fontWeight: 640, color: 'var(--faint)' }}>N/A</span>
                  <span style={{ fontSize: 13, color: 'var(--muted)' }}><b className="mono-label" style={{ fontSize: 9, color: 'var(--text)' }}>NOT APPLICABLE</b> · no loyalty program found</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <button type="button" onClick={() => setWhyNaOpen((v) => !v)} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'var(--canvas-dim)', border: '1px solid var(--border)', borderRadius: 999, padding: '8px 14px 8px 11px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.11em', color: 'var(--text)', fontWeight: 640 }}>
                      <Glyph name={whyNaOpen ? 'x' : 'plus'} size={12} color="var(--text)" />WHY N/A
                    </button>
                  </span>
                </div>
                {whyNaOpen && (
                  <div style={{ marginTop: 12, background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 16px', fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
                    Neither the site crawl nor a direct model check found a program, so these points are skipped and your score is calculated on the remaining applicable points.
                  </div>
                )}
              </div>
            ) : memberValue && (
              <DualLensDim
                code="member_value" iconGlyph="card" dim={memberValue}
                oneLiner="loyalty program found and scored"
                open={mvOpen} onToggle={toggleMv}
                howText="Encoding checks plus how often answers credit you with member value. Skipped and rescaled only when no program exists."
              />
            )}

            {dealCitability && (
              <DualLensDim
                code="deal_citability" iconGlyph="spark" dim={dealCitability}
                oneLiner="deals encoded, cited when shoppers are ready"
                open={dcOpen} onToggle={toggleDc}
                howText="Encoding checks plus deal citations on purchase-intent questions. No published deals scores zero, not exempt."
              />
            )}

            {valueProtocols && (
              <div style={{ background: 'var(--blue-tint)', border: '1.5px solid rgba(1,102,255,.35)', borderRadius: 14, padding: '18px 20px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 15, fontWeight: 660, color: 'var(--text-strong)', letterSpacing: '-0.012em' }}>Value Protocols</span>
                  <MonoTag tone="blue">THE GAP TRUESYNC CLOSES</MonoTag>
                  <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, fontWeight: 700, color: valueProtocols.earned === 0 ? 'var(--red-deep)' : 'var(--text-strong)' }}>
                    {valueProtocols.blocked ? 'N/M' : `${Math.round(valueProtocols.earned)}/${DIMENSIONS_BY_CODE.value_protocols.weight}`}
                  </span>
                  <span style={{ marginLeft: 'auto' }}><HowItsScoredButton open={vpOpen} onClick={toggleVp} /></span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 14 }}>
                  {(valueProtocols.checks || []).map((c) => (
                    <StateChip key={c.code} state={c.state === 'blocked' ? 'unmeasured' : (c.state === 'pass' ? 'seen' : 'invisible')} variant="chip" size="sm">{c.label}</StateChip>
                  ))}
                </div>
                <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px dashed rgba(1,102,255,.3)', fontSize: 13, color: 'var(--text)', lineHeight: 1.6 }}>
                  <span className="mono-label" style={{ fontSize: 8, background: 'var(--blue)', color: '#fff', borderRadius: 999, padding: '2px 8px', fontWeight: 700, marginRight: 8 }}>TRUESYNC</span>
                  This is the dimension Parleo fixes directly: TrueSync declares and maintains your value across the checkout standards agents use (Google's UCP, OpenAI's ACP).
                </div>
                {vpOpen && (
                  <div style={{ marginTop: 14, background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 16px', fontSize: 12.5, color: 'var(--muted)', lineHeight: 1.6 }}>
                    <b style={{ color: 'var(--text-strong)' }}>This one never shows up in answers. It works at checkout.</b> We score what your store declares. The Full Analysis tests what works.
                  </div>
                )}
              </div>
            )}

            {pillars.state === 'scored' && !isAgentReady(pillars) && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11, marginTop: 22, padding: '15px 17px', background: 'var(--surface-warm)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <Glyph name="filter" size={15} color="var(--amber-deep)" />
                <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6 }}>
                  <b style={{ color: 'var(--text-strong)' }}>Why not agent-ready:</b> readiness takes a composite of {VERDICT_COMPOSITE_THRESHOLD}+ and True Value above {Math.round(VERDICT_TRUE_VALUE_RATIO_THRESHOLD * 100)}% of its applicable points. You're at {Math.round(composite ?? 0)}{tvPct != null ? `, and True Value is at ${Math.round(tvPct)}%` : ''}.
                </div>
              </div>
            )}
            {pillars.state !== 'scored' && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11, marginTop: 22, padding: '15px 17px', background: 'var(--canvas-dim)', border: '1px solid var(--border)', borderRadius: 12 }}>
                <Glyph name="eyeOff" size={15} color="var(--faint)" />
                <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6 }}>
                  <b style={{ color: 'var(--text-strong)' }}>Verdict withheld:</b> {pillars.state === 'unverified' ? 'True Value itself could not be fully measured this run.' : 'part of this run could not be measured, so a readiness verdict would not be honest.'}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
