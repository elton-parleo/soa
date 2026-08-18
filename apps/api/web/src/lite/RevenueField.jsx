/**
 * The revenue control shared by the report's ADJUST ASSUMPTIONS panel
 * (report/ExposureSection.jsx) and the landing Stakes widget
 * (landing/Stakes.jsx): a logarithmic slider plus a typed field.
 *
 * Why both controls, and why they live in one component:
 *   - The track runs $120K to $5B, four and a half orders of magnitude.
 *     Linear, that is ~$5M per pixel and the entire small-and-mid range
 *     — most of the brands that run this audit — is unsettable. The
 *     range input therefore carries a unitless 0-1000 position and
 *     liteDerive.js maps it geometrically, so an equal drag always
 *     covers an equal ratio.
 *   - A slider cannot express "we did $6.2B" at all, and rounding a
 *     merchant's real figure down to the track's ceiling would be
 *     exactly the silent understatement this session set out to remove.
 *     So the typed field clamps to the PLAUSIBILITY bounds, not the
 *     slider's: type $8B and the track pins at max while the readout
 *     and the model both carry $8B.
 *
 * The parse/commit/reject behavior is identical on both surfaces, so it
 * is written once here; only the palette differs (`tone`), since the
 * landing widget sits on a dark panel.
 */
import { useEffect, useRef, useState } from 'react'
import {
  REVENUE_SLIDER_STEPS, revenueSliderPositionToRevenue, revenueToSliderPosition,
  parseRevenueInput, clampToPlausibleRevenue, formatCompactCurrency,
} from './liteDerive.js'

const TONES = {
  light: {
    label: 'var(--muted)', value: 'var(--text-strong)', accent: 'var(--blue)',
    border: 'var(--border)', surface: 'var(--surface)', invalid: 'var(--red)',
  },
  dark: {
    label: 'var(--dark-muted)', value: 'var(--dark-text)', accent: 'var(--dark-text)',
    border: 'var(--dark-border)', surface: 'rgba(242,240,239,.06)', invalid: 'var(--red)',
  },
}

export function RevenueField({
  label = 'Annual revenue',
  revenue,
  onRevenueChange,
  onInteract,
  tone = 'light',
  labelStyle,
  valueStyle,
}) {
  const palette = TONES[tone] || TONES.light
  // `draft` is null whenever the field is showing the committed value —
  // so a slider drag or a new seed flows straight through, and only
  // active typing holds the display.
  const [draft, setDraft] = useState(null)
  const [invalid, setInvalid] = useState(false)
  const inputRef = useRef(null)

  // A revenue change from anywhere else (the slider, the probe seed)
  // discards a half-typed draft rather than letting the field show one
  // number while the model uses another.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setDraft(null)
      setInvalid(false)
    }
  }, [revenue])

  function commit() {
    if (draft === null) return
    const parsed = parseRevenueInput(draft)
    if (parsed === null) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    setDraft(null)
    onRevenueChange(clampToPlausibleRevenue(parsed))
    if (onInteract) onInteract()
  }

  return (
    <div className="lite-revenue-field">
      <span className="lite-revenue-field-label" style={{ ...labelStyle, color: labelStyle?.color || palette.label }}>
        {label}
      </span>
      <input
        ref={inputRef}
        type="text"
        inputMode="decimal"
        className="lite-revenue-field-input num"
        aria-label={`${label} (exact amount)`}
        aria-invalid={invalid || undefined}
        value={draft ?? formatCompactCurrency(revenue)}
        onChange={(e) => { setDraft(e.target.value); setInvalid(false) }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit() }
          if (e.key === 'Escape') { setDraft(null); setInvalid(false) }
        }}
        style={{
          fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 640,
          color: invalid ? palette.invalid : (valueStyle?.color || palette.value),
          background: palette.surface,
          border: `1px solid ${invalid ? palette.invalid : palette.border}`,
          borderRadius: 8, padding: '5px 9px', textAlign: 'right', minWidth: 92,
          ...valueStyle,
          ...(invalid ? { color: palette.invalid } : null),
        }}
      />
      <input
        type="range"
        className="lite-revenue-field-range"
        min={0}
        max={REVENUE_SLIDER_STEPS}
        step={1}
        value={revenueToSliderPosition(revenue)}
        onChange={(e) => {
          onRevenueChange(revenueSliderPositionToRevenue(+e.target.value))
          if (onInteract) onInteract()
        }}
        aria-label={label}
        style={{ width: '100%', accentColor: palette.accent }}
      />
      {invalid && (
        <span className="lite-revenue-field-error mono-label" style={{ fontSize: 8.5, color: palette.invalid }}>
          ENTER AN AMOUNT — E.G. 250M, 1.2B, OR 750000
        </span>
      )}
    </div>
  )
}
