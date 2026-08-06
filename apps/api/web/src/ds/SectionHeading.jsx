/**
 * Site-wide headline signature: lead phrase + muted accent + blue
 * square end-mark. Never an eyebrow. Ported from the exported
 * design-system bundle (components/foundation/SectionHeading.jsx) —
 * same render tree, restored to JSX.
 */
export function SectionHeading({ children, accent, accentTone = 'muted', body, dark = false, align = 'left', size = 'lg', mark = true, maxWidth, bodyMaxWidth, style }) {
  const accentStyle = accentTone === 'primary'
    ? { color: 'var(--blue)', fontWeight: 680 }
    : { color: dark ? 'var(--dark-faint)' : 'rgba(70,69,85,.42)', fontWeight: 640, letterSpacing: '-0.024em' }

  return (
    <div style={{ textAlign: align, maxWidth, marginLeft: align === 'center' ? 'auto' : undefined, marginRight: align === 'center' ? 'auto' : undefined, ...style }}>
      <h2 className={`section-heading${size === 'sm' ? ' sm' : ''}${dark ? ' on-dark' : ''}${mark ? '' : ' no-mark'}`}>
        {children}
        {accent ? <> <span style={accentStyle}>{accent}</span></> : null}
      </h2>
      {body ? (
        <p
          className={`section-copy${dark ? ' on-dark' : ''}`}
          style={{ marginTop: 18, maxWidth: bodyMaxWidth || 560, marginLeft: align === 'center' ? 'auto' : undefined, marginRight: align === 'center' ? 'auto' : undefined }}
        >
          {body}
        </p>
      ) : null}
    </div>
  )
}
