/**
 * 2c: the browsing chrome around TranscriptSection's single curated
 * transcript — prev/next across queries, a searchable/grouped picker
 * (compact index rows with a narrative_case chip so a reader can jump
 * straight to "leak" or "not mentioned" cases), and a platform/run
 * selector for whichever query is currently active. Deliberately its
 * own file/exports (not folded into TranscriptSection.jsx) so it can
 * mount in the lite report later behind a flag (2e) without carrying
 * TranscriptSection's own curated-pick rendering along with it.
 *
 * Pure presentational — TranscriptSection.jsx owns all the fetching/
 * state (index data, active run_id, loading/error), this just renders
 * what it's given and calls back on interaction. No lite-vs-full-
 * analysis awareness of any kind lives here.
 */
import { useMemo, useState } from 'react'
import { Glyph, StateChip } from '../../ds/index.js'

const CASE_LABEL = {
  value_gap: 'Leak', not_mentioned: 'Not mentioned', mentioned_no_leak: 'Mentioned', uncoded: 'Uncoded',
}
const CASE_CHIP_STATE = {
  value_gap: 'invisible', not_mentioned: 'partial', mentioned_no_leak: 'seen', uncoded: 'unmeasured',
}

export function TranscriptCaseChip({ narrativeCase, size = 'sm' }) {
  return (
    <StateChip state={CASE_CHIP_STATE[narrativeCase] || 'unmeasured'} variant="chip" size={size}>
      {CASE_LABEL[narrativeCase] || 'Uncoded'}
    </StateChip>
  )
}

function navBtnStyle(enabled) {
  return {
    display: 'flex', alignItems: 'center', justifyContent: 'center', width: 26, height: 26,
    borderRadius: 8, border: '1px solid var(--border-strong)', background: 'var(--surface)',
    cursor: enabled ? 'pointer' : 'default', opacity: enabled ? 1 : 0.4,
  }
}

export function TranscriptNavBar({
  queryIndex, totalQueries, isCurated, pickerOpen,
  onTogglePicker, onPrev, onNext, onBackToPick, canPrev, canNext,
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button type="button" onClick={onPrev} disabled={!canPrev} aria-label="Previous query" style={navBtnStyle(canPrev)}>
          <Glyph name="arrowRight" size={12} color={canPrev ? 'var(--text-strong)' : 'var(--faint)'} style={{ transform: 'rotate(180deg)' }} />
        </button>
        <span className="mono-label" style={{ fontSize: 10.5, color: 'var(--muted)' }}>Query {queryIndex} of {totalQueries}</span>
        <button type="button" onClick={onNext} disabled={!canNext} aria-label="Next query" style={navBtnStyle(canNext)}>
          <Glyph name="arrowRight" size={12} color={canNext ? 'var(--text-strong)' : 'var(--faint)'} />
        </button>
        {isCurated ? (
          <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--blue)', background: 'var(--blue-tint)', borderRadius: 999, padding: '3px 9px', marginLeft: 4 }}>
            PARLEO'S PICK
          </span>
        ) : (
          <button type="button" onClick={onBackToPick} style={{ background: 'none', border: 'none', color: 'var(--blue)', fontSize: 12, cursor: 'pointer', padding: 0, marginLeft: 4 }}>
            ← Back to pick
          </button>
        )}
      </div>
      <button
        type="button" onClick={onTogglePicker} aria-expanded={pickerOpen}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 7, background: pickerOpen ? 'var(--blue-tint)' : 'var(--surface)',
          border: '1px solid var(--border-strong)', borderRadius: 999, padding: '6px 12px', cursor: 'pointer',
          fontSize: 12, fontWeight: 560, color: 'var(--text-strong)',
        }}
      >
        <Glyph name={pickerOpen ? 'x' : 'search'} size={12} color="var(--text-strong)" />
        {pickerOpen ? 'Close' : 'Browse all queries'}
      </button>
    </div>
  )
}

export function TranscriptRunSelector({ runs, activeRunId, onSelectRun }) {
  if (!runs || runs.length < 2) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
      {runs.map((r) => {
        const active = r.run_id === activeRunId
        return (
          <button
            key={r.run_id}
            type="button"
            onClick={() => onSelectRun(r.run_id)}
            aria-pressed={active}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, borderRadius: 999, padding: '4px 10px',
              fontSize: 11.5, fontWeight: 560, cursor: 'pointer',
              border: `1px solid ${active ? 'var(--blue)' : 'var(--border-strong)'}`,
              background: active ? 'var(--blue-tint)' : 'var(--surface)',
              color: active ? 'var(--blue)' : 'var(--text-strong)',
            }}
          >
            {r.platform} · run {r.run_number}
          </button>
        )
      })}
    </div>
  )
}

// Grouped-by-stage, filterable list of every query in the cycle.
// `queries` is the CURRENT page's rows (index.queries) — pagination
// itself (loadMore) is the caller's concern; this renders whatever
// page(s) it's handed, accumulated by the caller across "load more".
export function TranscriptQueryList({ queries, activeQueryId, onSelectQuery, loading, error, onLoadMore, hasMore }) {
  const [filter, setFilter] = useState('')

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return queries
    return queries.filter((q) => q.query_text.toLowerCase().includes(needle))
  }, [queries, filter])

  const grouped = useMemo(() => {
    const byStage = new Map()
    for (const q of filtered) {
      const key = q.stage || 'Other'
      if (!byStage.has(key)) byStage.set(key, [])
      byStage.get(key).push(q)
    }
    return byStage
  }, [filtered])

  return (
    <div style={{ marginTop: 14, background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: 14, padding: '14px 16px', maxHeight: 380, overflowY: 'auto' }}>
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter queries…"
        aria-label="Filter queries"
        style={{ width: '100%', boxSizing: 'border-box', padding: '8px 11px', fontSize: 13, borderRadius: 9, border: '1px solid var(--border-strong)', marginBottom: 12 }}
      />
      {error && <div style={{ fontSize: 12.5, color: 'var(--red-deep)' }}>Couldn't load queries — {error}</div>}
      {!error && filtered.length === 0 && !loading && (
        <div style={{ fontSize: 12.5, color: 'var(--faint)' }}>No queries match "{filter}".</div>
      )}
      {[...grouped.entries()].map(([stage, rows]) => (
        <div key={stage} style={{ marginBottom: 10 }}>
          <div className="mono-label" style={{ fontSize: 9, color: 'var(--faint)', marginBottom: 6 }}>{stage.toUpperCase()}</div>
          {rows.map((q) => {
            const active = q.query_id === activeQueryId
            return (
              <button
                key={q.query_id}
                type="button"
                onClick={() => onSelectQuery(q)}
                aria-current={active}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left',
                  padding: '8px 10px', borderRadius: 9, border: 'none', cursor: 'pointer', marginBottom: 3,
                  background: active ? 'var(--blue-tint)' : 'transparent',
                }}
              >
                <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--faint)', flexShrink: 0, width: 22 }}>{q.index}</span>
                <span style={{ flex: 1, fontSize: 12.5, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {q.query_text}
                </span>
                <TranscriptCaseChip narrativeCase={q.narrative_case} />
              </button>
            )
          })}
        </div>
      ))}
      {loading && <div style={{ fontSize: 12, color: 'var(--faint)', textAlign: 'center', padding: '8px 0' }}>Loading…</div>}
      {hasMore && !loading && (
        <button type="button" onClick={onLoadMore} style={{ display: 'block', margin: '6px auto 0', background: 'none', border: 'none', color: 'var(--blue)', fontSize: 12, cursor: 'pointer' }}>
          Load more
        </button>
      )}
    </div>
  )
}
