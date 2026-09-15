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
 *
 * ── A dead click is a bug in this file, whatever caused it ─────────────
 *
 * The catalog-accuracy drill-down went unresponsive on a real cycle while
 * the value tier's opened fine. That is the failure mode this panel has
 * to be incapable of: something went wrong, the console knew, and the
 * person clicking did not. So every path through this component now ends
 * in something rendered —
 *
 *   * the fetch is reported whether it succeeds, fails, or returns
 *     nothing, and "Loading…" is a state it can leave;
 *   * a row that throws while rendering is caught per row, so one bad
 *     row costs one row rather than all eighty-seven, and the count and
 *     the message are stated;
 *   * the panel chrome itself is inside a boundary, so a failure in the
 *     filters or the header cannot blank the panel either.
 *
 * None of that is a substitute for fixing what throws. It is what makes
 * the next thing that throws say so.
 */
import { Component, useEffect, useMemo, useState } from 'react'
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

// The five outcomes in the order the tier table lists them, so the chips
// and the columns above them read the same way round.
export const OUTCOMES = ['exact', 'stale', 'wrong', 'absent', 'unscoreable']

/**
 * Anything a row hands us, rendered as text and never as itself.
 *
 * React throws on an object child, which takes the whole subtree with it
 * — and these fields come from a JSON column, a model's extraction and a
 * timestamp cast, so "it is always a string" is an assumption about
 * three systems rather than a fact about one. Making it true here costs
 * a function call.
 */
function asText(value) {
  if (value === null || value === undefined) return null
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value instanceof Date) return value.toISOString()
  try {
    return JSON.stringify(value)
  } catch (_) {
    return String(value)
  }
}

/** The first ten characters of a date, however the field arrived. */
function asDay(value) {
  const text = asText(value)
  return text ? text.slice(0, 10) : null
}

export function describeExpectation(expected) {
  if (!expected || typeof expected !== 'object') return asText(expected)
  switch (expected.type) {
    case 'price': return `${asText(expected.amount)} ${asText(expected.currency)}`
    case 'gtin': return `GTIN ${asText(expected.value)}`
    case 'pack_count': return `${asText(expected.value)} count`
    case 'code': return `${asText(expected.code)}, ${asText(expected.value)}${expected.value_kind === 'percent_off' ? '%' : ''}`
    case 'member_price': return `${asText(expected.amount)} ${asText(expected.currency)} (${asText(expected.tier_name)})`
    case 'points': return expected.rule?.kind === 'per_dollar'
      ? `${asText(expected.rule.rate)} points per dollar`
      : `${asText(expected.rule?.points)} points`
    case 'brand_mention': return expected.domain
      ? `brand named, ${asText(expected.domain)} cited`
      : 'brand named'
    default: return asText(expected.type)
  }
}

// ─── The boundary ─────────────────────────────────────────────────────────
//
// A class, because that is the only thing React lets catch a render
// error. It renders nothing in place of what failed and reports the
// error upward; the panel states the count and the message in one line,
// so the reader learns that entries are missing and why, rather than
// counting rows against a total nobody showed them.

class RenderBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error) {
    // Reported, not swallowed: the console entry is what a developer
    // needs and the callback is what the reader needs, and neither
    // substitutes for the other.
    // eslint-disable-next-line no-console
    console.error('[tier-drilldown] could not render an entry', error)
    if (this.props.onError) this.props.onError(error)
  }

  render() {
    if (this.state.failed) return this.props.fallback ?? null
    return this.props.children
  }
}

// ─── Filters ──────────────────────────────────────────────────────────────

function FilterChips({ counts, total, active, onChange }) {
  const chip = (key, label, n) => {
    const on = active === key
    const empty = n === 0
    return (
      <button
        key={key}
        type="button"
        data-testid={`outcome-filter-${key}`}
        aria-pressed={on}
        disabled={empty && key !== 'all'}
        onClick={() => onChange(on && key !== 'all' ? 'all' : key)}
        style={{
          font: 'inherit',
          fontSize: 11.5,
          padding: '3px 10px',
          borderRadius: 999,
          cursor: empty && key !== 'all' ? 'default' : 'pointer',
          border: `1px solid ${on ? 'var(--text-strong)' : 'var(--hairline)'}`,
          background: on ? 'var(--text-strong)' : 'transparent',
          color: on ? 'var(--surface)' : empty ? 'var(--faint)' : 'var(--muted)',
          opacity: empty && key !== 'all' ? 0.55 : 1,
          whiteSpace: 'nowrap',
        }}
      >
        {label} <span className="num">{n}</span>
      </button>
    )
  }

  return (
    <div
      data-testid="outcome-filters"
      style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}
    >
      {chip('all', 'All', total)}
      {/* Every outcome, always, including the ones with none. A zero here
          is a finding — "nothing in this tier went stale" is the kind of
          thing a reader should be able to see rather than infer from an
          absent chip. */}
      {OUTCOMES.map((o) => chip(o, OUTCOME_LABEL[o], counts[o] || 0))}
    </div>
  )
}

// ─── One entry ────────────────────────────────────────────────────────────

function OutcomeEntry({ row, onViewResponse }) {
  return (
    <div
      data-testid="outcome-entry"
      data-outcome={row.outcome}
      style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--hairline)' }}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <StateChip state={OUTCOME_STATE[row.outcome] || 'unmeasured'} variant="chip" size="sm">
          {OUTCOME_LABEL[row.outcome] || asText(row.outcome) || 'Unknown'}
        </StateChip>
        <span style={{ fontSize: 11.5, color: 'var(--faint)', fontFamily: 'var(--font-mono)' }}>
          {asText(row.query_code)} · {asText(row.platform)} · run {asText(row.run_number)}
        </span>
      </div>

      <div style={{ marginTop: 6, fontSize: 13, color: 'var(--text-strong)' }}>
        {asText(row.query_text)}
      </div>

      <div style={{ marginTop: 4, fontSize: 12, color: 'var(--muted)' }}>
        Expected <strong>{describeExpectation(row.expected_answer)}</strong>
        {' — '}{asText(row.outcome_reason)}
        {/* For a stale outcome, WHICH publication it matched. That is
            what makes staleness attributable to a specific past
            publish rather than a general accusation of being
            behind. */}
        {row.matched_published_at && (
          <span> (published {asDay(row.matched_published_at)})</span>
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
          }}>{asText(row.answer_excerpt)}</pre>
          {onViewResponse && (
            <button
              type="button" onClick={() => onViewResponse(row.run_id)}
              style={{ background: 'none', border: 'none', padding: 0, marginTop: 6, cursor: 'pointer', color: 'var(--faint)', fontSize: 12, textDecoration: 'underline' }}
            >Open the full response</button>
          )}
        </details>
      )}
    </div>
  )
}

// ─── The panel ────────────────────────────────────────────────────────────

const NOTE = { marginTop: 12, fontSize: 12.5, color: 'var(--muted)' }

export function TierDrillDown({ tier, cycleCode, onClose, onViewResponse }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all')
  const [failures, setFailures] = useState([])

  useEffect(() => {
    let cancelled = false
    setRows(null)
    setError(null)
    setFilter('all')
    setFailures([])
    api.getTierOutcomes(cycleCode, tier)
      .then((data) => {
        if (cancelled) return
        // Defensive on the envelope, not just on the request. A 401
        // resolves to undefined here (api.js reloads the page), and a
        // shape change upstream should read as "nothing to show",
        // never as a panel stuck on Loading forever.
        setRows(Array.isArray(data?.outcomes) ? data.outcomes : [])
      })
      .catch((err) => {
        if (cancelled) return
        setError(err?.message || String(err) || 'unknown error')
      })
    return () => { cancelled = true }
  }, [cycleCode, tier])

  const counts = useMemo(() => {
    const out = {}
    for (const row of rows || []) {
      out[row?.outcome] = (out[row?.outcome] || 0) + 1
    }
    return out
  }, [rows])

  const shown = useMemo(
    () => (rows || []).filter((row) => filter === 'all' || row?.outcome === filter),
    [rows, filter],
  )

  const noteFailure = (err) => setFailures((prev) => [...prev, err])

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

      {/* The chrome below is inside its own boundary: a throw in the
          filters must not be able to blank the panel, which would be the
          same dead click by another route. */}
      <RenderBoundary
        onError={noteFailure}
        fallback={<div style={NOTE}>Could not render this drill-down.</div>}
      >
        {error && (
          <div data-testid="drilldown-error" style={NOTE}>
            Could not load the outcomes ({error}).
          </div>
        )}

        {rows === null && !error && (
          <div style={NOTE}>Loading…</div>
        )}

        {rows !== null && rows.length === 0 && (
          <div style={NOTE}>Nothing scored in this tier.</div>
        )}

        {rows !== null && rows.length > 0 && (
          <>
            <FilterChips
              counts={counts} total={rows.length}
              active={filter} onChange={setFilter}
            />

            {failures.length > 0 && (
              <div
                data-testid="drilldown-render-failures"
                style={{ ...NOTE, color: 'var(--red-deep)' }}
              >
                {`Couldn't render ${failures.length} `
                  + `${failures.length === 1 ? 'entry' : 'entries'}: `
                  + (failures[0]?.message || String(failures[0]))}
              </div>
            )}

            {shown.length === 0 && (
              <div style={NOTE}>
                Nothing in this tier scored {OUTCOME_LABEL[filter]?.toLowerCase() || filter}.
              </div>
            )}

            {shown.map((row, index) => (
              <RenderBoundary key={row?.run_id ?? `row-${index}`} onError={noteFailure}>
                <OutcomeEntry row={row} onViewResponse={onViewResponse} />
              </RenderBoundary>
            ))}
          </>
        )}
      </RenderBoundary>
    </div>
  )
}
