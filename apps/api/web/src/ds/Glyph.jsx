/**
 * Restrained 1.5px line glyphs. Only where they clarify state or system
 * relationships. Ported from the exported design-system bundle
 * (components/foundation/Glyph.jsx) — same render tree, restored to JSX.
 * Every glyph carries the visibility notch — a bite at NE with the
 * logo's satellite bar docked in it, in blue. notch={false} opts out
 * (dense tables).
 *
 * 'viewport' is not in the exported bundle (it defines 25 names, none
 * called viewport) but is named as in-use for this stage — added here,
 * matching the bundle's own line-icon style (1.5px stroke, 16x16
 * viewBox), rather than left missing.
 */
import { useId } from 'react'

const P = {
  eye: (
    <>
      <path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8s-2.4 4.5-6.5 4.5S1.5 8 1.5 8Z" />
      <circle cx="8" cy="8" r="2.1" />
    </>
  ),
  eyeOff: <path d="M3 3l10 10M6.7 4.1A6.9 6.9 0 0 1 8 4c4.1 0 6.5 4 6.5 4a11.8 11.8 0 0 1-1.9 2.3M9.6 9.6a2.1 2.1 0 0 1-3-3M4.4 5.2A11 11 0 0 0 1.5 8s2.4 4.5 6.5 4.5a6.6 6.6 0 0 0 2.2-.38" />,
  arrowUpRight: <path d="M4.5 11.5l7-7M5.5 4.5h6v6" />,
  arrowRight: <path d="M2.5 8h11M9.5 4l4 4-4 4" />,
  chart: <path d="M2.5 13.5V10M6.2 13.5V6.5M9.8 13.5V8.5M13.5 13.5V3.5" />,
  spark: <path d="M8 1.8l1.5 4.4 4.7.2-3.7 2.9 1.3 4.5L8 11.2l-3.8 2.6 1.3-4.5L1.8 6.4l4.7-.2L8 1.8Z" />,
  check: <path d="M2.8 8.6l3.4 3.4 7-7.6" />,
  x: <path d="M4 4l8 8M12 4l-8 8" />,
  plus: <path d="M8 2.5v11M2.5 8h11" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5l3.5 3.5" />
    </>
  ),
  layers: <path d="M8 2l6.5 3.2L8 8.4 1.5 5.2 8 2ZM2.6 8.4L8 11l5.4-2.6M2.6 11.4L8 14l5.4-2.6" />,
  chevronDown: <path d="M3.5 6l4.5 4.5L12.5 6" />,
  external: <path d="M6.5 3.5H2.5v10h10V9.5M9 2.5h4.5V7M13 3L7.5 8.5" />,
  refresh: <path d="M13.5 6.5a5.7 5.7 0 0 0-10.4-1.2M2.5 2.7v3.1h3.1M2.5 9.5a5.7 5.7 0 0 0 10.4 1.2M13.5 13.3v-3.1h-3.1" />,
  filter: <path d="M2 3.5h12M4.5 8h7M6.8 12.5h2.4" />,
  doc: <path d="M4 1.5h5.5L13 5v9.5H4V1.5ZM9.5 1.5V5H13M6 8h4M6 10.7h4" />,
  code: <path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.6V8l2.4 1.6" />
    </>
  ),
  tag: (
    <>
      <path d="M1.8 8.2V2h6.3l6 6-6.2 6.2-6-6Z" />
      <circle cx="5" cy="5" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  card: <path d="M1.5 4.2h13v8h-13v-8ZM1.5 6.8h13M3.6 10h3" />,
  globe: (
    <>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M1.8 8h12.4M8 1.8c1.9 1.7 2.8 3.9 2.8 6.2S9.9 12.5 8 14.2C6.1 12.5 5.2 10.3 5.2 8S6.1 3.5 8 1.8Z" />
    </>
  ),
  link: <path d="M6.5 9.5a3 3 0 0 0 4.3.2l2.1-2.1a3 3 0 0 0-4.2-4.2L7.5 4.6M9.5 6.5a3 3 0 0 0-4.3-.2L3.1 8.4a3 3 0 0 0 4.2 4.2l1.2-1.2" />,
  settings: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.6v2M8 12.4v2M1.6 8h2M12.4 8h2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M12.5 3.5l-1.4 1.4M4.9 11.1l-1.4 1.4" />
    </>
  ),
  grid: <path d="M2 2h5v5H2zM9 2h5v5H9zM2 9h5v5H2zM9 9h5v5H9z" />,
  agent: (
    <>
      <rect x="2" y="2.5" width="5" height="11" rx="1.8" />
      <rect x="9.5" y="5" width="4.5" height="6" rx="1.6" />
    </>
  ),
  viewport: (
    <>
      <rect x="1.8" y="3" width="12.4" height="9.2" rx="1.4" />
      <path d="M1.8 5.4h12.4" />
    </>
  ),
}

const glyphNames = Object.keys(P)

export function Glyph({ name = 'eye', size = 16, color = 'currentColor', strokeWidth = 1.5, notch = true, accent = 'var(--blue)', style }) {
  const id = useId()
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke={color}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, display: 'inline-block', verticalAlign: '-0.15em', ...style }}
    >
      {notch ? (
        <mask id={id}>
          <rect width="16" height="16" fill="#fff" />
          <circle cx="13.1" cy="2.9" r="3.5" fill="#000" />
        </mask>
      ) : null}
      <g mask={notch ? `url(#${id})` : undefined}>{P[name] || P.eye}</g>
      {notch ? <rect x="11.95" y="0.85" width="2.3" height="4.1" rx="1.15" fill={accent} stroke="none" /> : null}
    </svg>
  )
}

Glyph.names = glyphNames
