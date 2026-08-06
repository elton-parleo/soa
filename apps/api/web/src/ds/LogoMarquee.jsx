/**
 * Edge-faded marquee rail of logo chips. items: strings or {name, tag}.
 * Ported from the exported design-system bundle
 * (components/layout/LogoMarquee.jsx) — same render tree, restored to
 * JSX.
 */
import { Fragment } from 'react'
import { MonoTag } from './MonoTag.jsx'

export function LogoMarquee({ items = [], speed = 30, reverse = false, gap = 10, style }) {
  const chips = items.map((it, i) => {
    const name = typeof it === 'string' ? it : it.name
    const tag = typeof it === 'string' ? it : it.tag || it.name
    return <MonoTag key={i} logo={name}>{tag}</MonoTag>
  })
  return (
    <div className="edge-fade-x" style={{ overflow: 'hidden', ...style }}>
      <div className="animate-marquee" style={{ display: 'flex', gap, width: 'max-content', animationDuration: `${speed}s`, animationDirection: reverse ? 'reverse' : 'normal' }}>
        {chips}
        {chips.map((c, i) => <Fragment key={`d${i}`}>{c}</Fragment>)}
      </div>
    </div>
  )
}
