import { DarkPanel, Glyph } from '../../ds/index.js'
import { EDITORIAL_QUOTE } from './reportContent.js'

export function EditorialBand() {
  return (
    <div style={{ marginBottom: 16 }}>
      <DarkPanel pad={0} radius={16} atmos style={{ overflow: 'hidden', boxShadow: 'var(--shadow-card)' }}>
        <div style={{ padding: '34px 36px 30px', display: 'flex', flexDirection: 'column', gap: 18, minHeight: 150, justifyContent: 'flex-end' }}>
          <div style={{ fontFamily: "'Newsreader',Georgia,serif", fontStyle: 'italic', fontSize: 29, lineHeight: 1.32, color: 'var(--dark-text)', maxWidth: 620, letterSpacing: '-0.012em' }}>
            {EDITORIAL_QUOTE}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span className="mono-label" style={{ fontSize: 8.5, color: 'var(--dark-faint)' }}>EVERYTHING BELOW IS WHAT THAT COSTS, AND WHAT CLOSES IT</span>
            <span style={{ flex: 1, height: 1, background: 'var(--dark-border)', minWidth: 20 }} />
            <Glyph name="arrowRight" size={14} color="var(--blue-lite)" />
          </div>
        </div>
      </DarkPanel>
    </div>
  )
}
