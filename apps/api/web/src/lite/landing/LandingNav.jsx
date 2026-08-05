/** Sticky landing nav — logo + wordmark left, anchor + parleo.io pill right. */
export function LandingNav() {
  return (
    <nav className="lite-landing-nav" aria-label="Parleo Audit">
      <div className="lite-landing-nav-left">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="2" y="2" width="8" height="20" rx="1.5" style={{ fill: 'var(--accent)' }} />
          <rect x="14" y="6" width="8" height="12" rx="1.5" style={{ fill: 'var(--accent)' }} opacity="0.4" />
        </svg>
        <span className="lite-divider-v" style={{ height: 16 }} aria-hidden="true" />
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>Parleo Audit</span>
      </div>
      <div className="lite-landing-nav-right">
        <a href="#methodology" className="lite-landing-nav-link">How it works</a>
        <span className="lite-pill" style={{ cursor: 'default' }}>
          <span className="lite-badge-dot" aria-hidden="true" />
          parleo.io
        </span>
      </div>
    </nav>
  )
}
