/**
 * The per-question drill-down: one row per scored (question x surface x
 * sample), with the outcome, what was expected, what was extracted, and
 * the answer that was scored.
 *
 * This is what "every rate must trace back to stored answers" looks like
 * as a thing a person can click. Every number in the tier table above is
 * a count of these rows, and the row shows the answer text that produced
 * it — so a rate that looks wrong can be checked rather than argued
 * about.
 *
 * Owner-only. It carries raw answer text, which the public share payload
 * deliberately does not, so the parent renders it only when readOnly is
 * false.
 */
import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { StateChip } from '../../ds/index.js'

const OUTCOME_STATE = {
  exact: 'seen',
  stale: 'partial',
  wrong: 'invisible',
  absent: 'unmeasured',
  unscoreable: 'unmeasured',
}

const OUTCOME_LABEL = {
  exact: 'Exact',
  stale: 'Stale',
  wrong: 'Wrong',
  absent: 'Not addressed',
  unscoreable: 'Unreadable',
}

function describeExpectation(expected) {
  if (!expected) return null
  switch (expected.type) {
    case 'price': return `${expected.amount} ${expected.currency}`
    case 'gtin': return `GTIN ${expected.value}`
    case 'pack_count': return `${expected.value} count`
    case 'code': return `${expected.code}, ${expected.value}${expected.value_kind === 'percent_off' ? '%' : ''}`
    case 'member_price': return `${expected.amount} ${expected.currency} (${expected.tier_name})`
    case 'points': return expected.rule?.kind === 'per_dollar'
      ? `${expected.rule.rate} points per dollar`
      : `${expected.rule?.points} points`
    case 'brand_mention': return expected.domain
      ? `brand named, ${expected.domain} cited`
      : 'brand named'
    default: return expected.type
  }
}

export function TierDrillDown({ tier, cycleCode, onClose, onViewResponse }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setRows(null)
    setError(null)
    api.getTierOutcomes(cycleCode, tier)
      .then((data) => { if (!cancelled) setRows(data.outcomes || []) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [cycleCode, tier])

  return (
    <div
      data-testid="tier-drilldown"
      style={{
        border: '1px solid var(--hairline)', borderRadius: 10, padding: 18,
        marginTop: -8, marginBottom: 28, background: 'var(--surface)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--faint)' }}>
          {tier} · every scored answer
        </div>
        <button
          type="button" onClick={onClose}
          style={{ background: 'none', border: 'none', color: 'var(--faint)', fontSize: 12, cursor: 'pointer', padding: 0 }}
        >Close</button>
      </div>

      {error && (
        <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--muted)' }}>
          Could not load the outcomes ({error}).
        </div>
      )}

      {rows === null && !error && (
        <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--muted)' }}>Loading…</div>
      )}

      {rows !== null && rows.length === 0 && (
        <div style={{ marginTop: 12, fontSize: 12.5, color: 'var(--muted)' }}>
          Nothing scored in this tier.
        </div>
      )}

      {(rows || []).map((row) => (
        <div
          key={`${row.run_id}`}
          style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--hairline)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <StateChip state={OUTCOME_STATE[row.outcome] || 'unmeasured'} variant="chip" size="sm">
              {OUTCOME_LABEL[row.outcome] || row.outcome}
            </StateChip>
            <span style={{ fontSize: 11.5, color: 'var(--faint)', fontFamily: 'var(--font-mono)' }}>
              {row.query_code} · {row.platform} · run {row.run_number}
            </span>
          </div>

          <div style={{ marginTop: 6, fontSize: 13, color: 'var(--text-strong)' }}>{row.query_text}</div>

          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
            Expected <strong>{describeExpectation(row.expected_answer)}</strong>
            {' — '}{row.outcome_reason}
            {/* For a stale outcome, WHICH publication it matched. That is
                what makes staleness attributable to a specific past
                publish rather than a general accusation of being
                behind. */}
            {row.matched_published_at && (
              <span> (published {String(row.matched_published_at).slice(0, 10)})</span>
            )}
          </div>

          {row.answer_excerpt && (
            <details style={{ marginTop: 8 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--faint)' }}>
                The answer this was scored from
              </summary>
              <pre style={{
                whiteSpace: 'pre-wrap', fontSize: 12, color: 'var(--muted)',
                lineHeight: 1.6, marginTop: 8, fontFamily: 'inherit',
              }}>{row.answer_excerpt}</pre>
              {onViewResponse && (
                <button
                  type="button" onClick={() => onViewResponse(row.run_id)}
                  style={{ background: 'none', border: 'none', padding: 0, marginTop: 6, cursor: 'pointer', color: 'var(--faint)', fontSize: 12, textDecoration: 'underline' }}
                >Open the full response</button>
              )}
            </details>
          )}
        </div>
      ))}
    </div>
  )
}
