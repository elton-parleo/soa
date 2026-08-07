/**
 * S1: score hero. Pace-lane chart is registry-driven per the brief:
 * pace_i = READINESS_BAR × (max_i/100), delta = earned_i − pace_i,
 * rounded — no literals. READINESS_BAR reuses the same
 * VERDICT_COMPOSITE_THRESHOLD (60) the verdict gate itself uses, so the
 * chart and the gate can never quietly disagree about what "on pace"
 * means.
 */
import { DarkPanel, Glyph, StatusChip, MonoTag } from '../../ds/index.js'
import { LITE_QUERY_COUNT, VERDICT_COMPOSITE_THRESHOLD, PILLAR_NAMES } from '../landing/scanDimensionsRegistry.js'
import { formatCurrency } from '../liteDerive.js'
import { pillarEarnedMax, pillarNominalWeight, pillarHeadline, isAgentReady, buildMeasurableContext, isPartialRead, PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE } from './reportDerive.js'

// Part 2d: a lane whose measurable_max is short of its registry
// full_max renders the shortfall as the DS hatch (ds-hatch, tokens.css)
// instead of today's plain fill-to-max — and swaps the pace-delta
// caption for "N PTS NEED PRODUCT PAGES", since pace against a max we
// never attempted this run would be meaningless (asserted by test: no
// lane with unread points ever renders a pace delta).
function PaceLane({ label, earned, measurableMax, fullMax, isTrueValue }) {
  const unread = Math.max(0, fullMax - measurableMax)
  const pace = (VERDICT_COMPOSITE_THRESHOLD / 100) * fullMax
  const delta = Math.round(earned - pace)
  const fillPct = fullMax ? Math.min(100, (earned / fullMax) * 100) : 0
  const hatchPct = fullMax ? Math.min(100 - fillPct, (unread / fullMax) * 100) : 0
  const atPace = delta >= 0
  return (
    <div style={{ flex: `0 1 auto`, width: `calc(${fullMax}% - 18px)`, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: isTrueValue ? 'var(--blue)' : 'var(--text-strong)', letterSpacing: '-0.01em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
      <div style={{ position: 'relative', height: 30, borderRadius: 4, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)', overflow: 'hidden', marginTop: 14 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${fillPct}%`, background: isTrueValue ? 'var(--blue)' : (atPace ? 'var(--ink)' : '#6B6979') }} />
        {unread > 0 && (
          <div className="ds-hatch" style={{ position: 'absolute', left: `${fillPct}%`, top: 0, bottom: 0, width: `${hatchPct}%` }} />
        )}
        <span aria-hidden="true" style={{ position: 'absolute', left: `${VERDICT_COMPOSITE_THRESHOLD}%`, top: 0, bottom: 0, width: 1, background: 'rgba(30,30,46,.28)' }} />
        <span className="num" style={{ position: 'absolute', right: 9, top: '50%', transform: 'translateY(-50%)', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: isTrueValue ? 'var(--blue)' : 'var(--text-strong)' }}>
          {unread > 0
            ? <>{Math.round(earned)}<span style={{ color: 'var(--faint)', fontWeight: 520 }}>/{Math.round(measurableMax)} of {Math.round(fullMax)}</span></>
            : <>{Math.round(earned)}<span style={{ color: 'var(--faint)', fontWeight: 520 }}>/{Math.round(fullMax)}</span></>}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap', marginTop: 8 }}>
        {unread > 0 ? (
          <>
            <i style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--amber)', flexShrink: 0 }} />
            <span className="mono-label" style={{ fontSize: 9, color: 'var(--amber-deep)' }}>{Math.round(unread)} PTS NEED PRODUCT PAGES</span>
          </>
        ) : (
          <>
            <i style={{ width: 5, height: 5, borderRadius: '50%', background: atPace ? 'var(--green)' : 'var(--red-deep)', flexShrink: 0 }} />
            <span className="mono-label" style={{ fontSize: 9, color: atPace ? 'var(--green)' : 'var(--red-deep)' }}>{atPace ? 'AT PACE' : `${delta} TO PACE`}</span>
          </>
        )}
      </div>
    </div>
  )
}

export function ScoreHero({ report, exposure, shareOfMentionsRank, headline }) {
  const { plain, emphasis } = headline
  const pillars = report.pillars
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const composite = report.composite
  const shortOfReady = composite != null ? Math.max(0, Math.round(VERDICT_COMPOSITE_THRESHOLD - composite)) : null
  const partial = isPartialRead(pillars, report.scan?.degraded_reason)
  const measurable = partial ? buildMeasurableContext(pillars) : null

  const pillarCards = [
    { key: PILLAR_VISIBILITY, icon: 'eye', ...vis, sub: pillarHeadline(report, PILLAR_VISIBILITY) },
    { key: PILLAR_ACCESSIBILITY, icon: 'globe', ...acc, sub: pillarHeadline(report, PILLAR_ACCESSIBILITY) },
    { key: PILLAR_TRUE_VALUE, icon: 'tag', ...tv, sub: pillarHeadline(report, PILLAR_TRUE_VALUE), accent: true },
  ]

  return (
    <div id="score" style={{ marginBottom: 18, scrollMarginTop: 26 }}>
      <DarkPanel pad={0} radius={18} atmos style={{ overflow: 'hidden', boxShadow: 'var(--shadow-elevated)' }}>
        <div style={{ padding: '28px 32px 26px', borderBottom: '1px solid var(--dark-border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Glyph name="chart" size={13} color="var(--blue-lite)" />
            <span className="mono-label" style={{ fontSize: 10, color: 'var(--dark-faint)' }}>AGENTIC VALUE SCORE</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 7, flexWrap: 'wrap' }}>
              <MonoTag logo="ChatGPT" tone="dark">ChatGPT</MonoTag>
              <MonoTag tone="dark">{LITE_QUERY_COUNT} QUERIES</MonoTag>
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 40, alignItems: 'flex-end', marginTop: 18, flexWrap: 'wrap' }}>
            <div className="lite-scorehero-headline" style={{ flex: 1, minWidth: 340, maxWidth: 560, fontSize: 38, fontWeight: 740, letterSpacing: '-0.034em', lineHeight: 1.1, color: 'var(--dark-text)' }}>
              {plain} <em style={{ fontFamily: "'Newsreader',Georgia,serif", fontWeight: 440, fontStyle: 'italic', color: 'var(--blue-lite)', letterSpacing: '-0.008em' }}>{emphasis}</em>
            </div>
            {pillars.state === 'scored' ? (
              <div style={{ flexShrink: 0 }}><StatusChip tone={isAgentReady(pillars) ? 'success' : 'risk'}>{isAgentReady(pillars) ? 'Agent-ready' : 'Not agent-ready'}</StatusChip></div>
            ) : partial ? (
              <div style={{ flexShrink: 0 }}><StatusChip tone="warning">Partial read</StatusChip></div>
            ) : null}
          </div>

          <div style={{ marginTop: 26, padding: '22px 24px 20px', background: 'rgba(242,240,239,.055)', border: '1px solid var(--dark-border)', borderRadius: 15 }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 22, flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
                <span className="num lite-display-num" style={{ fontSize: 66, fontWeight: 750, letterSpacing: '-0.044em', lineHeight: 0.86, color: 'var(--dark-text)' }}>
                  {composite != null ? Math.round(composite) : partial ? Math.round(measurable.earned) : '—'}
                </span>
                <span className="num" style={{ fontSize: 23, fontWeight: 560, color: 'var(--dark-faint)', letterSpacing: '-0.02em' }}>
                  {composite == null && partial ? `/${Math.round(measurable.measurable_max)} measurable` : '/100'}
                </span>
              </div>
              {shortOfReady != null ? (
                <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                  <div className="num" style={{ fontSize: 23, fontWeight: 720, letterSpacing: '-0.024em', color: 'var(--blue-lite)', lineHeight: 1 }}>{shortOfReady} points</div>
                  <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)', marginTop: 5 }}>SHORT OF THE READINESS BAR</div>
                </div>
              ) : partial ? (
                <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                  <div className="num" style={{ fontSize: 23, fontWeight: 720, letterSpacing: '-0.024em', color: 'var(--amber)', lineHeight: 1 }}>{Math.round(measurable.unmeasurable_points)} points</div>
                  <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)', marginTop: 5 }}>COULDN'T BE READ THIS RUN</div>
                </div>
              ) : null}
            </div>
            <div style={{ marginTop: 24 }}>
              <div style={{ background: 'var(--canvas)', borderRadius: 14, padding: '22px 22px 18px', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.7),0 10px 26px -12px rgba(10,10,18,.6)' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 14, marginBottom: 15, paddingBottom: 12, borderBottom: '1px solid var(--hairline)' }}>
                  <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--muted)' }}>LANE WIDTH = POINT BUDGET · FILL = POINTS EARNED</span>
                  <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--muted)' }}>PACE FOR A READY SCORE</span>
                </div>
                <div className="lite-scorehero-lanes-row" style={{ display: 'flex', gap: 27, alignItems: 'flex-start' }}>
                  <PaceLane label={PILLAR_NAMES[PILLAR_VISIBILITY]} earned={vis.earned} measurableMax={partial ? vis.max : pillarNominalWeight(PILLAR_VISIBILITY)} fullMax={pillarNominalWeight(PILLAR_VISIBILITY)} />
                  <PaceLane label={PILLAR_NAMES[PILLAR_ACCESSIBILITY]} earned={acc.earned} measurableMax={partial ? acc.max : pillarNominalWeight(PILLAR_ACCESSIBILITY)} fullMax={pillarNominalWeight(PILLAR_ACCESSIBILITY)} />
                  <PaceLane label={PILLAR_NAMES[PILLAR_TRUE_VALUE]} earned={tv.earned} measurableMax={partial ? tv.max : pillarNominalWeight(PILLAR_TRUE_VALUE)} fullMax={pillarNominalWeight(PILLAR_TRUE_VALUE)} isTrueValue />
                </div>
              </div>
            </div>
          </div>

          <div className="lite-scorehero-tiles-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 16 }}>
            <div style={{ background: 'rgba(242,240,239,.05)', border: '1px solid var(--dark-border)', borderRadius: 13, padding: '15px 17px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><Glyph name="eye" size={13} color="var(--blue-lite)" /><span className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)' }}>SHARE OF MENTIONS</span></div>
              <div className="num" style={{ fontSize: 24, fontWeight: 720, letterSpacing: '-0.026em', color: 'var(--dark-text)', marginTop: 10, lineHeight: 1 }}>
                {shareOfMentionsRank || '—'}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--dark-faint)', marginTop: 6 }}>In your auto-selected competitor set</div>
            </div>
            <div style={{ background: 'rgba(1,102,255,.13)', border: '1px solid rgba(127,176,255,.34)', borderRadius: 13, padding: '15px 17px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}><Glyph name="card" size={13} color="var(--blue-lite)" /><span className="mono-label" style={{ fontSize: 8.5, color: 'var(--blue-lite)' }}>MODELED EXPOSURE / YEAR</span></div>
              <div className="num" style={{ fontSize: 24, fontWeight: 720, letterSpacing: '-0.026em', color: 'var(--dark-text)', marginTop: 10, lineHeight: 1 }}>{formatCurrency(exposure)}</div>
              <a href="#exp" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: 'var(--blue-lite)', fontWeight: 520, marginTop: 6 }}>How we model this<Glyph name="arrowRight" size={12} color="var(--blue-lite)" /></a>
            </div>
          </div>
        </div>

        <div style={{ padding: '26px 32px 28px' }}>
          <div className="lite-scorehero-pillars-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 14 }}>
            {pillarCards.map((p) => {
              const pct = p.max ? (p.earned / p.max) * 100 : 0
              return (
                <div key={p.key} style={{ background: p.accent ? 'rgba(1,102,255,.14)' : 'rgba(242,240,239,.05)', border: `1px solid ${p.accent ? 'rgba(127,176,255,.42)' : 'var(--dark-border)'}`, borderRadius: 13, padding: '16px 17px 15px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
                    <Glyph name={p.icon} size={15} color={p.accent ? 'var(--blue-lite)' : 'rgba(242,240,239,.55)'} />
                    <span style={{ fontSize: 13.5, fontWeight: 620, color: 'var(--dark-text)', letterSpacing: '-0.01em' }}>{PILLAR_NAMES[p.key]}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 3, marginTop: 13 }}>
                    <span className="num" style={{ fontSize: 30, fontWeight: 700, letterSpacing: '-0.03em', color: 'var(--dark-text)', lineHeight: 1 }}>{Math.round(p.earned)}</span>
                    <span className="num" style={{ fontSize: 15, fontWeight: 500, color: 'var(--dark-faint)' }}>/{Math.round(p.max)}</span>
                  </div>
                  <div style={{ position: 'relative', height: 6, borderRadius: 3, background: 'rgba(242,240,239,.13)', marginTop: 12, overflow: 'hidden' }}>
                    <i style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct}%`, background: p.accent ? 'var(--blue-lite)' : 'rgba(242,240,239,.55)', borderRadius: 3 }} />
                  </div>
                  <div className="mono-label" style={{ fontSize: 9, color: p.accent ? 'var(--blue-lite)' : 'var(--dark-faint)', marginTop: 11, lineHeight: 1.6 }}>{p.sub}</div>
                </div>
              )
            })}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap', marginTop: 18, paddingTop: 15, borderTop: '1px solid var(--dark-border)' }}>
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--dark-faint)' }}>
              VISIBILITY {pillarNominalWeight(PILLAR_VISIBILITY)} · ACCESSIBILITY {pillarNominalWeight(PILLAR_ACCESSIBILITY)} · TRUE VALUE {pillarNominalWeight(PILLAR_TRUE_VALUE)} · STRAIGHT SUM, NO BLACK BOX{partial && ` · ${Math.round(measurable.unmeasurable_points)} PTS UNREAD THIS RUN`}
            </span>
          </div>
        </div>
      </DarkPanel>
    </div>
  )
}
