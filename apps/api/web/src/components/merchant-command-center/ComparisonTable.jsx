import React from 'react'

/**
 * The inspector's field-comparison table, shared by both kinds of
 * comparison the product makes.
 *
 * Dimension 2 (our own listings) compares a surface against the master
 * record we published, so one column is authoritative and the other is
 * what we found. §2b (prospects) compares two surfaces against each
 * other, where **neither side is known to be right** — so the same
 * table renders with two neutral surface names instead of
 * master/observed, and neither value is styled as the correct one.
 *
 * Keeping one component for both is deliberate: they are the same
 * finding schema with the expected/observed pair renamed, and a second
 * table would drift from this one the first time either changed.
 */

export function text(value, fallback = '—') {
  if (value == null || value === '') return fallback
  const type = typeof value
  if (type === 'string' || type === 'number' || type === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch (_) {
    return fallback
  }
}

/**
 * Master-vs-surface. `findings` are dimension 2 findings:
 * { variant, field, expected, observed }.
 */
export function MasterComparisonTable({ findings }) {
  return (
    <table className="mcc-kv">
      <thead>
        <tr>
          <th style={{ width: '22%' }}>Field</th>
          <th>Variant</th>
          <th>Master record</th>
          <th>On surface</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((f, i) => (
          <tr key={`${f.field}-${f.variant}-${i}`}>
            <td className="field">{text(f.field)}</td>
            <td className="mcc-val">{text(f.variant)}</td>
            <td><span className="mcc-val good">{text(f.expected)}</span></td>
            <td>
              {f.observed == null
                ? <span className="mcc-val missing">missing</span>
                : <span className="mcc-val bad">{text(f.observed)}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * Surface-vs-surface (§2b). `findings` are normalised prospect
 * findings: { variantKey, field, surfaceA, valueA, surfaceB, valueB }.
 *
 * Both values carry the SAME styling. There is no master here, and
 * colouring one of them as correct would be inventing an authority the
 * data does not have.
 */
export function SurfaceComparisonTable({ findings }) {
  return (
    <table className="mcc-kv mcc-kv-surfaces">
      <thead>
        <tr>
          <th style={{ width: '20%' }}>Field</th>
          <th>Surface A</th>
          <th>Value</th>
          <th>Surface B</th>
          <th>Value</th>
        </tr>
      </thead>
      <tbody>
        {findings.map((f, i) => (
          <tr key={`${f.field}-${f.variantKey}-${i}`} className={f.missingIdentifier ? 'finding-identifier' : undefined}>
            <td className="field">
              {text(f.field)}
              {/* A surface that omits the identifier is the one an agent
                  trips over first — called out rather than listed as
                  just another mismatched field. */}
              {f.missingIdentifier && <div className="mcc-finding-note">identifier missing</div>}
            </td>
            <td className="mcc-val mcc-surface-name">{text(f.surfaceA)}</td>
            <td><span className="mcc-val neutral">{text(f.valueA, 'missing')}</span></td>
            <td className="mcc-val mcc-surface-name">{text(f.surfaceB)}</td>
            <td><span className="mcc-val neutral">{text(f.valueB, 'missing')}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
