/**
 * Big-number stat. countUp animates on first view (300ms shimmer then
 * count). Internal dependency of LeakageEstimator and MetricRow — not
 * in D2's named component list, ported alongside them. Ported from the
 * exported design-system bundle (components/foundation/Stat.jsx) — same
 * render tree, restored to JSX.
 */
import { useEffect, useRef, useState } from 'react'
import { Delta } from './Delta.jsx'

export function Stat({ value, prefix = '', suffix = '', label, sub, delta, deltaTone, size = 44, align = 'left', dark = false, countUp = false, accent = false, style }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(countUp ? 0 : value)
  const [ready, setReady] = useState(!countUp)

  useEffect(() => {
    if (!countUp) {
      setShown(value)
      setReady(true)
      return undefined
    }
    const num = parseFloat(String(value).replace(/[^0-9.\-]/g, ''))
    if (isNaN(num)) {
      setShown(value)
      setReady(true)
      return undefined
    }
    const el = ref.current
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return
      io.disconnect()
      const t0 = performance.now()
      const dur = 900
      const dec = (String(value).split('.')[1] || '').length
      const step = (t) => {
        const p = Math.min(1, (t - t0) / dur)
        const ease = 1 - Math.pow(1 - p, 3)
        setShown((num * ease).toFixed(dec))
        setReady(true)
        if (p < 1) requestAnimationFrame(step)
        else setShown(value)
      }
      requestAnimationFrame(step)
    }, { threshold: 0.4 })
    if (el) io.observe(el)
    return () => io.disconnect()
  }, [value, countUp])

  const ink = dark ? 'var(--dark-text)' : accent ? 'var(--blue)' : 'var(--text-strong)'
  const mut = dark ? 'var(--dark-muted)' : 'var(--muted)'

  return (
    <div ref={ref} style={{ textAlign: align, ...style }}>
      {label ? <div className="mono-label" style={{ color: mut, marginBottom: size * 0.22 }}>{label}</div> : null}
      <div className="num" style={{ fontSize: size, fontWeight: 720, letterSpacing: '-0.03em', lineHeight: 1, color: ink, opacity: ready ? 1 : 0.3, transition: 'opacity .3s' }}>
        {prefix && <span style={{ fontSize: size * 0.6, fontWeight: 640, verticalAlign: 'baseline' }}>{prefix}</span>}
        {shown}
        {suffix && <span style={{ fontSize: size * 0.6, fontWeight: 640, color: dark ? 'var(--dark-muted)' : 'var(--faint)' }}>{suffix}</span>}
        {delta !== undefined ? <Delta value={delta} tone={deltaTone} size="sm" style={{ marginLeft: 10, verticalAlign: `${size * 0.14}px` }} /> : null}
      </div>
      {sub ? <div style={{ fontSize: 12.5, color: mut, marginTop: size * 0.18, lineHeight: 1.45 }}>{sub}</div> : null}
    </div>
  )
}
