/**
 * The Path — V4 design, three-step "measure → deepen → fix" cards.
 * Ported verbatim from the mock's "The Path" section.
 */
import { Glyph } from '../../ds/index.js'
import { LITE_QUERY_COUNT } from './scanDimensionsRegistry.js'

function StepCard({ n, tag, glyph, glyphBg, glyphColor, tagColor, title, body, footer, footerBorder, highlight }) {
  return (
    <div
      style={{
        position: 'relative',
        background: highlight ? 'var(--container)' : 'var(--surface)',
        borderRadius: highlight ? 16 : 14,
        borderTop: highlight ? '2px solid var(--blue)' : undefined,
        padding: highlight ? '22px 24px 22px' : '24px 24px 22px',
        boxShadow: 'var(--shadow-card)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 34, height: 34, flexShrink: 0, borderRadius: 10, background: glyphBg }}>
          <Glyph name={glyph} size={16} color={glyphColor} />
        </span>
        <span className="num" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: highlight ? 'var(--blue)' : 'var(--faint)' }}>{n}</span>
        <span style={{ flex: 1, height: 1, background: highlight ? 'rgba(1,102,255,.2)' : 'var(--hairline)' }} />
        <span className="mono-label" style={{ fontSize: 9.5, color: tagColor }}>{tag}</span>
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-strong)', letterSpacing: '-0.016em' }}>{title}</div>
      <div style={{ fontSize: 13.5, color: 'var(--muted)', lineHeight: 1.6, marginTop: 7 }}>{body}</div>
      <div className="mono-label" style={{ fontSize: 8.5, color: 'var(--faint)', marginTop: 'auto', paddingTop: 18, borderTop: `1px solid ${footerBorder}` }}>{footer}</div>
    </div>
  )
}

export function Path() {
  return (
    <section style={{ padding: '60px 24px 12px' }}>
      <div style={{ maxWidth: 1120, margin: '0 auto' }}>
        <div className="section-heading sm">Measure your agentic gaps. <span className="accent">Then close them.</span></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 18, marginTop: 32, alignItems: 'stretch' }}>
          <StepCard
            n="01"
            tag="TODAY"
            glyph="search"
            glyphBg="rgba(1,102,255,.09)"
            glyphColor="var(--blue)"
            tagColor="var(--blue)"
            title="Find the leak"
            body={`The free audit: ${LITE_QUERY_COUNT} live ChatGPT queries and a crawl of your store. Your Agentic Value Score, verdict, and first fixes in one shareable report.`}
            footer="FREE · 10–20 MIN · NO EMAIL TO START"
            footerBorder="var(--hairline)"
          />
          <StepCard
            n="02"
            tag="GO DEEPER"
            glyph="layers"
            glyphBg="rgba(1,102,255,.09)"
            glyphColor="var(--blue)"
            tagColor="var(--blue)"
            title="Trace every gap"
            body={`The Full Analysis runs Gemini, Perplexity, and Claude on the same questions, a category study at thousands of queries instead of ${LITE_QUERY_COUNT}, and SKU-level price accuracy across your catalog. Free, and custom to your store.`}
            footer="BOOK A WALKTHROUGH · FREE"
            footerBorder="var(--hairline)"
          />
          <StepCard
            n="03"
            tag="THE FIX"
            glyph="refresh"
            glyphBg="var(--blue)"
            glyphColor="#fff"
            tagColor="var(--blue)"
            title="Stop the leak with TrueSync"
            body="Two of the four gap areas the audit measures are the two Parleo fixes directly: TrueSync encodes your member value and deals, declares them to the checkout standards agents use (Google's UCP, OpenAI's ACP), and keeps them in sync as offers change."
            footer="MEASURE → FIX → STAY AGENT-READY"
            footerBorder="rgba(70,69,85,.12)"
            highlight
          />
        </div>
      </div>
    </section>
  )
}
