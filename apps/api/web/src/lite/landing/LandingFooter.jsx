/** Footer — ink band, logo left, one-line tagline right. */
export function LandingFooter() {
  return (
    <footer style={{ background: 'var(--ink)', padding: '28px 20px' }}>
      <div style={{
        maxWidth: 1120, margin: '0 auto', display: 'flex', justifyContent: 'space-between',
        alignItems: 'center', gap: 16, flexWrap: 'wrap',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="2" y="2" width="8" height="20" rx="1.5" style={{ fill: 'var(--accent)' }} />
            <rect x="14" y="6" width="8" height="12" rx="1.5" style={{ fill: 'var(--accent)' }} opacity="0.4" />
          </svg>
          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-inv)' }}>Parleo</span>
        </div>
        <span className="lite-body--inv" style={{ fontSize: 12.5, textAlign: 'right' }}>
          Parleo scores, tracks, and optimizes how your pricing, promotions, and
          incentives perform when AI agents decide.
        </span>
      </div>
    </footer>
  )
}
