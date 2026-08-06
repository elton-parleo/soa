/**
 * "Inside the product" container: #EAE8E5, 2px blue top border, 16px
 * radius. Frames live demos and sandboxes. Ported from the exported
 * design-system bundle (components/layout/Container.jsx) — same render
 * tree, restored to JSX.
 */
export function Container({ children, pad = 32, label, style }) {
  return (
    <div style={{ position: 'relative', background: 'var(--container)', borderTop: '2px solid var(--blue)', borderRadius: 16, padding: pad, ...style }}>
      {label ? <span className="mono-label" style={{ position: 'absolute', top: 14, right: 18, color: 'var(--faint)' }}>{label}</span> : null}
      {children}
    </div>
  )
}
