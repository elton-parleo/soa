/**
 * Share of Algorithm: how often agents recommend each merchant. You =
 * blue; projection ghosts ahead. Ported from the exported design-system
 * bundle (components/artifacts/SoAIndex.jsx) — same render tree,
 * restored to JSX.
 */
import { useEffect, useRef, useState } from 'react'
import { BrandLogo } from './BrandLogo.jsx'
import { Delta } from './Delta.jsx'

export function SoAIndex({ rows = [], you, projected, style }) {
  const ref = useRef(null)
  const [go, setGo] = useState(false)

  useEffect(() => {
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) {
        setGo(true)
        io.disconnect()
      }
    }, { threshold: 0.3 })
    if (ref.current) io.observe(ref.current)
    return () => io.disconnect()
  }, [])

  const max = Math.max(...rows.map((r) => Math.max(r.share, r.projected || 0)), 1)

  return (
    <div ref={ref} style={{ display: 'flex', flexDirection: 'column', gap: 13, ...style }}>
      {rows.map((r, i) => {
        const isYou = r.name === you
        return (
          <div key={i} style={{ display: 'grid', gridTemplateColumns: 'minmax(110px,140px) 1fr 74px', alignItems: 'center', gap: 12 }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: isYou ? 640 : 500, color: 'var(--text-strong)' }}>
              <BrandLogo name={r.name} size={15} />
              {r.name}
            </span>
            <div style={{ position: 'relative', height: 22, borderRadius: 6, background: 'var(--canvas-dim)', overflow: 'hidden' }}>
              {isYou && r.projected ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: go ? `${(r.projected / max) * 100}%` : 0,
                    borderRadius: 6,
                    background: 'repeating-linear-gradient(45deg,rgba(1,102,255,.16) 0 5px,rgba(1,102,255,.05) 5px 10px)',
                    border: '1px dashed rgba(1,102,255,.45)',
                    boxSizing: 'border-box',
                    transition: 'width 1.1s cubic-bezier(.22,1,.36,1) .25s',
                  }}
                />
              ) : null}
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: go ? `${(r.share / max) * 100}%` : 0,
                  borderRadius: 6,
                  background: isYou ? 'var(--blue)' : 'var(--border-strong)',
                  transition: `width .9s cubic-bezier(.22,1,.36,1) ${i * 0.07}s`,
                }}
              />
            </div>
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
              <span className="num" style={{ fontSize: 12.5, fontWeight: 640, color: isYou ? 'var(--blue)' : 'var(--text)' }}>{r.share}%</span>
              {r.delta !== undefined ? <Delta value={r.delta} size="sm" bare /> : null}
            </span>
          </div>
        )
      })}
      {projected ? (
        <div className="mono-label" style={{ fontSize: 11, color: 'var(--faint)', display: 'flex', alignItems: 'center', gap: 7 }}>
          <span
            style={{
              width: 14,
              height: 8,
              borderRadius: 2,
              background: 'repeating-linear-gradient(45deg,rgba(1,102,255,.16) 0 4px,rgba(1,102,255,.05) 4px 8px)',
              border: '1px dashed rgba(1,102,255,.45)',
              display: 'inline-block',
            }}
          />
          {projected}
        </div>
      ) : null}
    </div>
  )
}
