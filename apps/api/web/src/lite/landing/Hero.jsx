/**
 * THE HERO — V4 design, section [1]. Ported from the mock's Hero
 * section (Audit Landing.dc.html) verbatim: headline, what-you-get
 * list, URL submit (LiteForm compact, restyled to DS tokens — see
 * LiteForm.jsx), measured-on line, trust badges, and the right-column
 * sample-report preview card.
 *
 * L2: the URL input drives the existing intake submit unchanged — no
 * new API call, no fabricated intermediate "queued" state beyond what
 * LiteForm's own submitting label already shows, since the real flow
 * submits and navigates to the progress page immediately (U2).
 */
import { Glyph, Button, BrowserChrome, Wordmark, BrandLogo } from '../../ds/index.js'
import { LiteForm } from '../LiteForm.jsx'
import { SAMPLE_REPORT_URL } from './landingSampleContent.js'

export function Hero({ onSubmitted }) {
  return (
    <section style={{ position: 'relative', isolation: 'isolate', overflow: 'hidden' }}>
      <div aria-hidden="true" className="light-burn-warm" style={{ position: 'absolute', inset: 0, zIndex: 0 }} />
      <div aria-hidden="true" className="bg-grid-fine" style={{ position: 'absolute', inset: 0, zIndex: 0, backgroundSize: '56px 56px' }} />
      <div style={{ position: 'relative', zIndex: 1, maxWidth: 1120, margin: '0 auto', padding: '64px 24px 26px', display: 'grid', gridTemplateColumns: '6.4fr 5.6fr', gap: 56, alignItems: 'center' }}>
        <div>
          <h1 className="section-heading" style={{ fontSize: 54, margin: 0 }}>
            Are AI agents quoting your product's{' '}
            <em style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontWeight: 460, color: 'var(--blue)', letterSpacing: '-0.012em' }}>true value</em>?
          </h1>
          <p className="section-copy" style={{ margin: '20px 0 0', maxWidth: 456, fontSize: 16, lineHeight: 1.55 }}>
            We test ChatGPT with queries across the entire purchase funnel to track your brand's recommendation share and pricing accuracy. Then, we simulate how agents crawl your site and surface your products &amp; offers.
          </p>
          <div style={{ marginTop: 20, maxWidth: 470 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9, marginTop: 13 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Glyph name="chart" size={15} color="var(--blue)" />
                <span style={{ fontSize: 15, color: 'var(--text)' }}>Your <b style={{ color: 'var(--text-strong)', fontWeight: 620 }}>Agentic Value Score</b></span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Glyph name="check" size={15} color="var(--blue)" />
                <span style={{ fontSize: 15, color: 'var(--text)' }}>Your <b style={{ color: 'var(--text-strong)', fontWeight: 620 }}>ranked fixes</b></span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Glyph name="card" size={15} color="var(--blue)" />
                <span style={{ fontSize: 15, color: 'var(--text)' }}>The <b style={{ color: 'var(--text-strong)', fontWeight: 620 }}>dollar exposure</b> behind the gap</span>
              </div>
            </div>
          </div>
          <div id="run" style={{ display: 'flex', gap: 10, marginTop: 28, maxWidth: 470, scrollMarginTop: 90 }}>
            <LiteForm compact onSubmitted={onSubmitted} placeholder="yourstore.com" submitLabel="Run my free audit" />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap', marginTop: 26 }}>
            <span style={{ fontSize: 13.5, color: 'var(--faint)', marginRight: 2 }}>Measured on</span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 500, letterSpacing: '0.07em', textTransform: 'uppercase', padding: '5px 12px', borderRadius: 999, background: 'var(--surface)', boxShadow: 'var(--shadow-card)' }}>
              <BrandLogo name="ChatGPT" size={13} />ChatGPT
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--faint)' }}>plus Gemini, Perplexity and Claude in the Full Analysis</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 22px', marginTop: 22, maxWidth: 470 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26, flexShrink: 0, borderRadius: 8, background: 'rgba(1,102,255,.09)' }}>
                <Glyph name="card" size={14} color="var(--blue)" />
              </span>
              <span style={{ fontSize: 13.5, fontWeight: 540, color: 'var(--text-strong)' }}>Free, no email to start</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26, flexShrink: 0, borderRadius: 8, background: 'rgba(1,102,255,.09)' }}>
                <Glyph name="clock" size={14} color="var(--blue)" />
              </span>
              <span style={{ fontSize: 13.5, fontWeight: 540, color: 'var(--text-strong)' }}>Ready in 10–20 minutes</span>
            </div>
          </div>
        </div>

        <div style={{ position: 'relative' }}>
          <a href={SAMPLE_REPORT_URL} style={{ display: 'block', textDecoration: 'none' }}>
            <BrowserChrome url="audit.parleo.io/allbirds">
              <div>
                <div className="atmos-cool-dark" style={{ position: 'relative', isolation: 'isolate', background: 'var(--ink)', padding: '15px 20px 16px', overflow: 'hidden' }}>
                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
                      <Wordmark size={12} dark />
                      <span style={{ width: 1, height: 13, background: 'var(--dark-border)' }} />
                      <span style={{ fontSize: 12, color: 'var(--dark-muted)' }}>Agentic Value Audit</span>
                      <span className="mono-label" style={{ marginLeft: 'auto', fontSize: 8.5, color: 'var(--dark-faint)' }}>SAMPLE · JUL 2026</span>
                    </div>
                    <div style={{ marginTop: 15 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <BrandLogo name="Allbirds" domain="allbirds.com" size={19} />
                        <span style={{ fontSize: 13.5, fontWeight: 620, color: 'var(--dark-text)' }}>Allbirds</span>
                      </div>
                      <div style={{ fontSize: 26, fontWeight: 730, letterSpacing: '-0.03em', lineHeight: 1.12, color: 'var(--dark-text)', marginTop: 10 }}>
                        $5.9M of funded value <em style={{ fontFamily: "'Newsreader',Georgia,serif", fontWeight: 440, fontStyle: 'italic', color: '#7FB0FF', letterSpacing: '-0.008em' }}>agents never quoted.</em>
                      </div>
                      <div style={{ fontSize: 12.5, color: 'var(--dark-muted)', lineHeight: 1.5, marginTop: 9 }}>
                        Allbirds funds member pricing and live promotions. Across 24 ChatGPT answers, none of it surfaced.
                      </div>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, marginTop: 14, border: '1px solid rgba(127,176,255,.32)', background: 'rgba(127,176,255,.09)', borderRadius: 999, padding: '6px 12px' }}>
                        <Glyph name="arrowUpRight" size={12} color="#7FB0FF" />
                        <span className="mono-label" style={{ fontSize: 9, color: '#7FB0FF' }}>20 POINTS RECOVERABLE</span>
                      </div>
                      <div style={{ marginTop: 20, paddingTop: 18, borderTop: '1px solid var(--dark-border)' }}>
                        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16 }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
                            <span className="num" style={{ fontSize: 46, fontWeight: 750, letterSpacing: '-0.044em', lineHeight: 0.86, color: 'var(--dark-text)' }}>40</span>
                            <span className="num" style={{ fontSize: 17, fontWeight: 560, color: 'var(--dark-faint)' }}>/100</span>
                          </div>
                          <div className="mono-label" style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--dark-faint)', textAlign: 'right', lineHeight: 1.6 }}>
                            AGENTIC VALUE SCORE<br />20 SHORT OF THE READINESS BAR
                          </div>
                        </div>
                        <div style={{ marginTop: 20 }}>
                          <ReadinessBarMini earnedPct={40} readyPct={60} />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div style={{ background: 'var(--canvas)', padding: '15px 20px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                    <span className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)' }}>POINTS EARNED PER PILLAR</span>
                    <span style={{ flex: 1, height: 1, background: 'var(--hairline)' }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginTop: 11 }}>
                    <HeroPillarRow label="Visibility" sub="Whether agents mention you at all" pct={62.5} score="25/40" />
                    <HeroPillarRow label="Accessibility" sub="Whether they can read your pages" pct={40} score="8/20" />
                    <HeroPillarRow trueValue label="True Value" sub="Whether they can quote your real price" pct={17.5} score="7/40" />
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 11, background: 'var(--surface)', borderTop: '1px solid var(--border)', padding: '13px 20px' }}>
                  <Glyph name="check" size={13} color="var(--blue)" />
                  <span style={{ fontSize: 12, color: 'var(--text)' }}>3 ranked fixes, in priority order</span>
                  <span className="mono-label" style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--blue)' }}>RECOVERS UP TO 20 PTS</span>
                </div>
              </div>
            </BrowserChrome>
          </a>
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 26 }}>
            <a href={SAMPLE_REPORT_URL} style={{ textDecoration: 'none', flexShrink: 0 }}>
              <Button variant="outline" arrow>See the full sample report</Button>
            </a>
          </div>
        </div>
      </div>
    </section>
  )
}

function ReadinessBarMini({ earnedPct, readyPct }) {
  return (
    <div style={{ background: 'var(--canvas)', borderRadius: 12, padding: '16px 16px 13px', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.7),0 8px 20px -10px rgba(10,10,18,.55)' }}>
      <div style={{ position: 'relative', height: 13, borderRadius: 6.5, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${earnedPct}%`, borderRadius: 6.5, background: 'var(--ink)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.16)' }} />
        <span aria-hidden="true" style={{ position: 'absolute', left: `${readyPct}%`, top: -2, bottom: -2, width: 3, transform: 'translateX(-3px)', borderRadius: 2, background: 'var(--blue)', boxShadow: '0 0 10px rgba(1,102,255,.6)' }} />
        <span aria-hidden="true" style={{ position: 'absolute', left: `${readyPct}%`, top: -4, bottom: -4, width: 1, background: 'var(--text-strong)' }} />
        <span aria-hidden="true" style={{ position: 'absolute', left: `${readyPct}%`, top: -8, width: 5, height: 5, transform: 'translateX(-2px)', background: 'var(--text-strong)', clipPath: 'polygon(0 0,100% 0,50% 100%)' }} />
      </div>
      <div style={{ position: 'relative', height: 14, marginTop: 7 }}>
        <span className="mono-label" style={{ position: 'absolute', left: 0, top: 0, fontSize: 9, color: 'var(--text-strong)', fontWeight: 600 }}>{earnedPct} EARNED</span>
        <span className="mono-label" style={{ position: 'absolute', left: `${readyPct}%`, top: 0, transform: 'translateX(-50%)', fontSize: 9, color: 'var(--muted)', whiteSpace: 'nowrap' }}>READY {readyPct}</span>
        <span className="mono-label" style={{ position: 'absolute', right: 0, top: 0, fontSize: 9, color: 'var(--faint)' }}>100</span>
      </div>
    </div>
  )
}

function HeroPillarRow({ label, sub, pct, score, trueValue = false }) {
  if (trueValue) {
    return (
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 13, background: 'var(--blue-tint)', border: '1px solid rgba(1,102,255,.18)', borderRadius: 11, padding: '11px 13px 11px 14px', marginTop: 3 }}>
        <span style={{ position: 'absolute', left: 0, top: 11, bottom: 11, width: 3, borderRadius: '0 3px 3px 0', background: 'var(--blue)' }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12.5, fontWeight: 680, color: 'var(--blue)', letterSpacing: '-0.008em', whiteSpace: 'nowrap' }}>{label}</span>
            <span className="mono-label" style={{ fontSize: 8.5, color: '#fff', background: 'var(--blue)', borderRadius: 999, padding: '3px 8px', whiteSpace: 'nowrap' }}>ONLY PARLEO MEASURES THIS</span>
          </div>
          <div style={{ fontSize: 10.5, color: 'var(--muted)', marginTop: 3 }}>{sub}</div>
        </div>
        <span style={{ display: 'block', width: 72, height: 8, borderRadius: 4, background: 'rgba(1,102,255,.14)', overflow: 'hidden', flexShrink: 0 }}>
          <span style={{ display: 'block', width: `${pct}%`, height: '100%', borderRadius: 4, background: 'var(--blue)', boxShadow: '0 0 8px rgba(1,102,255,.5)' }} />
        </span>
        <span className="num" style={{ fontSize: 18, fontWeight: 740, letterSpacing: '-0.024em', color: 'var(--blue)', width: 48, textAlign: 'right', flexShrink: 0 }}>{score}</span>
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-strong)', letterSpacing: '-0.005em' }}>{label}</div>
        <div style={{ fontSize: 10.5, color: 'var(--faint)', marginTop: 1 }}>{sub}</div>
      </div>
      <span style={{ display: 'block', width: 72, height: 6, borderRadius: 3, background: 'var(--canvas-dim)', overflow: 'hidden', flexShrink: 0 }}>
        <span style={{ display: 'block', width: `${pct}%`, height: '100%', borderRadius: 3, background: 'var(--ink)' }} />
      </span>
      <span className="num" style={{ fontSize: 16, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-strong)', width: 48, textAlign: 'right', flexShrink: 0 }}>{score}</span>
    </div>
  )
}

