import { useState } from 'react'
import { Glyph } from '../../ds/index.js'

export function useDetailToggle() {
  return useState(false)
}

export function HowItsScoredButton({ open, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 9, background: 'var(--surface)',
        border: '1px solid var(--border-strong)', borderRadius: 10, padding: '6px 13px 6px 7px',
        cursor: 'pointer', fontFamily: 'inherit', fontSize: 12.5, fontWeight: 580,
        letterSpacing: '-0.008em', color: 'var(--text-strong)', boxShadow: 'var(--shadow-sm)',
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, flexShrink: 0, borderRadius: 7, background: 'var(--blue-tint)' }}>
        <Glyph name={open ? 'x' : 'plus'} size={11} color="var(--blue)" />
      </span>
      How it's scored
    </button>
  )
}

export function HowItsScoredPanel({ children }) {
  return (
    <div style={{ marginTop: 13, background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 12, padding: '14px 16px' }}>
      <span className="mono-label" style={{ display: 'block', fontSize: 9, color: 'var(--faint)', marginBottom: 9 }}>HOW WE MEASURE</span>
      <div style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.6 }}>{children}</div>
    </div>
  )
}
