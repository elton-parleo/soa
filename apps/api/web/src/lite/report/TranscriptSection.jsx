/**
 * "From the transcript" — one live query + verbatim agent response,
 * selected server-side (app/services/transcript_pick.py::select_
 * transcript) from the SAME cycle the report's own numbers come from.
 * Ships in both the lite audit report (LiteFullReportV4.jsx) and the
 * Full Analysis report (FullAnalysisReport.jsx) from this ONE
 * component, mounted identically — report.transcript is null-safe:
 * this renders nothing (and callers must add no rail row) when it is.
 *
 * Markup grammar follows design-refs/report-partial-read-mock.html's
 * "FROM THE TRANSCRIPT" section, but every token is the shipped design
 * system's own (--surface-warm, --blue/--blue-tint, --amber, --red-tint,
 * --green-tint) rather than the mock's ad hoc --warm/.dbox.red classes —
 * per this codebase's shipped-beats-mock precedent. The literal ◉ ◑ ▨
 * glyph characters mirror an existing precedent (ExposureSection.jsx's
 * "▨ SPLIT MODELED…" line, ResponseExplorer.jsx's "◎" engine glyph),
 * not a mock-only affectation.
 *
 * Highlight spans ({start, end, kind}) are located server-side (coded
 * mentions/price observations store no character offsets) — this
 * component only paints them. Capturing spans at coding time instead is
 * a noted follow-up, not done here (see transcript_pick.py's docstring).
 *
 * Transcript browsing (2b/2c) is entirely OPT IN via `browsable` +
 * `fetchIndex`/`fetchDetail` — lite mounts this component exactly as it
 * always has (no new props), so its render tree and its 15/50-odd
 * pinned tests are untouched. When browsable, this component owns all
 * the browsing state (active transcript, index cache, loading/error);
 * TranscriptPicker.jsx is pure presentation for the nav bar/run
 * selector/query list.
 */
import { useEffect, useRef, useState } from 'react'
import { MonoTag } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { HowItsScoredButton } from './HowItsScored.jsx'
import { TranscriptNavBar, TranscriptRunSelector, TranscriptQueryList } from './TranscriptPicker.jsx'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

const PLATFORM_LOGO = { chatgpt: 'ChatGPT', gemini: 'Gemini', gemini_grounded: 'Gemini', claude: 'Claude', perplexity: 'Perplexity' }

const INTRO_COPY = {
  value_gap: "This is the query where your value gap shows most clearly.",
  mentioned_no_leak: "This is a real answer where you're named.",
  not_mentioned: "This is a real answer where you were left out.",
  uncoded: 'This is a real, recorded answer from this cycle.',
}

function formatAskedDate(isoLike) {
  if (!isoLike) return null
  const d = new Date(isoLike)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Legend/hover label per dotted-underline span kind — 'value_claim' is
// a genuine off-site source (a different merchant named the price);
// 'stale_price' is the primary's OWN price, self-attributed but
// inaccurate (the sharpest DTC leak — never an off-site claim, so it
// gets its own label rather than reusing "sourced outside your
// markup", which would be false for it).
const SPAN_LABELS = {
  value_claim: 'value claim sourced outside your markup',
  stale_price: 'your price, quoted stale',
}

// Splits response_text into React nodes, painting brand spans as a blue
// highlight and value-claim/stale-price spans as a dotted amber
// underline (same style, different hover label — see SPAN_LABELS).
// limit clips both the text and any span that starts before it — the
// collapsed preview never shows a highlight for text it doesn't render.
function renderAnswer(text, spans, limit, expanded) {
  const cut = expanded ? text.length : Math.min(limit ?? text.length, text.length)
  const visible = (spans || []).filter((s) => s.start < cut)
  const nodes = []
  let cursor = 0
  for (const span of visible) {
    const start = Math.max(span.start, cursor)
    const end = Math.min(span.end, cut)
    if (end <= start) continue
    if (start > cursor) nodes.push(<span key={`t${cursor}`}>{text.slice(cursor, start)}</span>)
    const content = text.slice(start, end)
    if (span.kind === 'brand') {
      nodes.push(
        <mark key={`s${start}`} style={{ background: 'var(--blue-tint)', color: 'var(--blue-deep)', padding: '1px 5px', borderRadius: 5, fontWeight: 600 }}>
          {content}
        </mark>,
      )
    } else {
      nodes.push(
        <span key={`s${start}`} title={SPAN_LABELS[span.kind]} style={{ borderBottom: '2px dotted var(--amber)' }}>
          {content}
        </span>,
      )
    }
    cursor = end
  }
  if (cursor < cut) nodes.push(<span key={`t${cursor}`}>{text.slice(cursor, cut)}</span>)
  if (!expanded && cut < text.length) nodes.push(<span key="ellipsis">…</span>)
  return nodes
}

// Wraps every occurrence of `needle` in `text` with an anchor to href —
// used to link the "Price Truth" phrase in generated LEAKED copy to the
// True Value pillar section where that dimension lives.
function linkify(text, needle, href) {
  if (!text || !text.includes(needle)) return text
  const parts = text.split(needle)
  const nodes = []
  parts.forEach((part, i) => {
    if (i > 0) nodes.push(<a key={`l${i}`} href={href} style={{ color: 'var(--blue)' }}>{needle}</a>)
    nodes.push(<span key={`t${i}`}>{part}</span>)
  })
  return nodes
}

export function TranscriptSection({ report, open, onToggle, browsable = false, fetchIndex, fetchDetail }) {
  const [showFull, setShowFull] = useState(false)
  const [activeTranscript, setActiveTranscript] = useState(report.transcript)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [indexData, setIndexData] = useState(null)
  const [indexLoading, setIndexLoading] = useState(false)
  const [indexError, setIndexError] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(null)
  const indexLoadedRef = useRef(false)

  useEffect(() => {
    setActiveTranscript(report.transcript)
  }, [report.transcript])

  useEffect(() => {
    if (browsable && fetchIndex) ensureIndexLoaded()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browsable, fetchIndex])

  // Arrow-key nav only while this section is open and browsable, and
  // never while the picker's own filter input (or any other field) has
  // focus — that input needs its arrow keys for text editing, not
  // section-level query navigation.
  useEffect(() => {
    if (!browsable || !open) return undefined
    function handleKeyDown(e) {
      const tag = e.target && e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'ArrowLeft') goToOffset(-1)
      else if (e.key === 'ArrowRight') goToOffset(1)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browsable, open, indexData, activeTranscript])

  async function ensureIndexLoaded() {
    if (indexLoadedRef.current || indexLoading || !fetchIndex) return
    setIndexLoading(true)
    setIndexError(null)
    try {
      let page = 1
      let acc = []
      let meta = null
      for (;;) {
        const res = await fetchIndex(page)
        acc = acc.concat(res.queries)
        meta = res
        if (acc.length >= res.total_queries || res.queries.length === 0) break
        page += 1
      }
      setIndexData({ queries: acc, total_queries: meta ? meta.total_queries : acc.length, curated_run_id: meta ? meta.curated_run_id : null })
      indexLoadedRef.current = true
    } catch (e) {
      setIndexError(e.message || 'Could not load queries')
    } finally {
      setIndexLoading(false)
    }
  }

  async function loadRun(runId, navProps) {
    if (!fetchDetail) return
    setDetailLoading(true)
    setDetailError(null)
    try {
      const detail = await fetchDetail(runId)
      setActiveTranscript(detail)
      track(EVENTS.TRANSCRIPT_NAVIGATED, {
        ...navProps,
        position: `${detail.query_index}/${detail.total_queries}`,
        platform: detail.platform,
        narrative_case: detail.narrative_case,
      })
    } catch (e) {
      setDetailError(e.message || 'Could not load this transcript')
    } finally {
      setDetailLoading(false)
    }
  }

  function runForQuery(queryRow) {
    const curatedRunId = indexData ? indexData.curated_run_id : null
    return queryRow.runs.find((r) => r.run_id === curatedRunId) || queryRow.runs[0]
  }

  function handleSelectQuery(queryRow) {
    const run = runForQuery(queryRow)
    if (!run) return
    setPickerOpen(false)
    loadRun(run.run_id, { picker: true })
  }

  function handleSelectRun(runId) {
    loadRun(runId, { picker: true })
  }

  function handleBackToPick() {
    setActiveTranscript(report.transcript)
    setDetailError(null)
    track(EVENTS.TRANSCRIPT_NAVIGATED, {
      picker: true,
      position: `${report.transcript.query_index}/${report.transcript.total_queries}`,
      platform: report.transcript.platform,
      narrative_case: report.transcript.narrative_case,
    })
  }

  function handleTogglePicker() {
    const next = !pickerOpen
    setPickerOpen(next)
    if (next) ensureIndexLoaded()
  }

  function goToOffset(delta) {
    if (!indexData) return
    const pos = indexData.queries.findIndex((q) => q.index === activeTranscript.query_index)
    if (pos === -1) return
    const nextPos = pos + delta
    if (nextPos < 0 || nextPos >= indexData.queries.length) return
    const run = runForQuery(indexData.queries[nextPos])
    if (!run) return
    loadRun(run.run_id, { direction: delta > 0 ? 'next' : 'prev' })
  }

  const transcript = activeTranscript
  if (!transcript) return null

  const {
    platform, query_text: queryText, query_index: queryIndex, total_queries: totalQueries,
    asked_at: askedAt, response_text: responseText, preview_cutoff: previewCutoff,
    spans, narrative_case: narrativeCase, right, leaked, run_id: runId,
  } = transcript

  const isCurated = runId === report.transcript.run_id
  const activeQueryRow = indexData ? indexData.queries.find((q) => q.runs.some((r) => r.run_id === runId)) : null
  const currentPos = indexData ? indexData.queries.findIndex((q) => q.index === queryIndex) : -1
  const canPrev = currentPos > 0
  const canNext = currentPos !== -1 && currentPos < (indexData ? indexData.queries.length : 0) - 1

  // TRANSCRIPT_NARRATIVE_ENABLED (soa_shared/config.py) decides server-
  // side whether right/leaked are in the payload at all — the frontend
  // never reads a flag of its own, it just renders the duo boxes when
  // both fields are actually present. Omitted (not empty-string) when
  // the server has the gate off, so this check is unambiguous.
  const showBoxes = right != null && leaked != null

  function toggleFull() {
    setShowFull((v) => {
      const next = !v
      if (next) track(EVENTS.TRANSCRIPT_ANSWER_EXPANDED, {})
      return next
    })
  }

  const askedLabel = formatAskedDate(askedAt)
  const hasOffsite = (spans || []).some((s) => s.kind === 'value_claim')
  const hasStale = (spans || []).some((s) => s.kind === 'stale_price')
  const legendText = hasOffsite && hasStale
    ? 'Dotted underlines = value claims sourced outside your markup, or your own price quoted stale'
    : hasOffsite
      ? 'Dotted underlines = value claims sourced outside your markup'
      : hasStale
        ? 'Dotted underline = your own price, quoted stale'
        : null

  return (
    <ReportSection
      id="transcript"
      eyebrow={`FROM THE TRANSCRIPT · ${queryIndex} OF ${totalQueries} LIVE QUERIES · VERBATIM`}
      title="One of the conversations behind these numbers"
      extra={<MonoTag logo={PLATFORM_LOGO[platform]}>◎ {PLATFORM_LOGO[platform] || platform}</MonoTag>}
      open={open} onToggle={onToggle}
    >
      <p style={{ fontSize: 14, color: 'var(--muted)', maxWidth: 640, margin: '4px 0 18px', lineHeight: 1.55 }}>
        Every score above comes from real conversations like this one — asked live, recorded verbatim, unedited.{' '}
        {INTRO_COPY[narrativeCase] || INTRO_COPY.uncoded}
      </p>

      {browsable && (
        <TranscriptNavBar
          queryIndex={queryIndex} totalQueries={totalQueries}
          isCurated={isCurated} pickerOpen={pickerOpen}
          onTogglePicker={handleTogglePicker}
          onPrev={() => goToOffset(-1)} onNext={() => goToOffset(1)}
          onBackToPick={handleBackToPick}
          canPrev={canPrev} canNext={canNext}
        />
      )}

      {browsable && activeQueryRow && (
        <TranscriptRunSelector runs={activeQueryRow.runs} activeRunId={runId} onSelectRun={handleSelectRun} />
      )}

      {browsable && pickerOpen && (
        <TranscriptQueryList
          queries={indexData ? indexData.queries : []}
          activeQueryId={activeQueryRow ? activeQueryRow.query_id : null}
          onSelectQuery={handleSelectQuery}
          loading={indexLoading} error={indexError}
          onLoadMore={undefined} hasMore={false}
        />
      )}

      {browsable && detailError && (
        <div style={{ fontSize: 12.5, color: 'var(--red-deep)', marginBottom: 12 }}>Couldn't load that transcript — {detailError}</div>
      )}

      <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 18, padding: '22px 24px', opacity: browsable && detailLoading ? 0.5 : 1 }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
          <div style={{ background: 'var(--blue)', color: '#fff', borderRadius: '16px 16px 4px 16px', padding: '13px 17px', fontSize: 15, maxWidth: 520 }}>
            {queryText}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <span style={{ flex: 'none', width: 30, height: 30, borderRadius: 9, background: 'var(--ink)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13 }}>◎</span>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--hairline)', borderRadius: '4px 16px 16px 16px', padding: '16px 19px', fontSize: 15, lineHeight: 1.65, maxWidth: 640 }}>
            {renderAnswer(responseText, spans, previewCutoff, showFull)}
            {previewCutoff < responseText.length && (
              <div style={{ marginTop: 12 }}>
                <HowItsScoredButton open={showFull} onToggle={toggleFull} label={showFull ? 'Hide the full answer' : 'Show the full answer'} />
              </div>
            )}
          </div>
        </div>
      </div>

      {showBoxes && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 18 }}>
          <div style={{ background: 'var(--green-tint)', border: '1px solid var(--hairline)', borderRadius: 13, padding: '15px 17px' }}>
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--text-strong)' }}>◉ WHAT WENT RIGHT</span>
            <div style={{ marginTop: 8, fontSize: 13.5, color: 'var(--text)', lineHeight: 1.55 }}>{right}</div>
          </div>
          <div style={{ background: 'var(--red-tint)', border: '1px solid var(--hairline)', borderRadius: 13, padding: '15px 17px' }}>
            <span className="mono-label" style={{ fontSize: 9.5, color: 'var(--red-deep)' }}>◑ WHAT LEAKED</span>
            <div style={{ marginTop: 8, fontSize: 13.5, color: 'var(--text)', lineHeight: 1.55 }}>{linkify(leaked, 'Price Truth', '#tv')}</div>
          </div>
        </div>
      )}

      {/* No boxes: the provenance line takes over the duo's own 18px
          top margin (instead of stacking 18 + 16) so it follows the
          answer card at the same visual distance either way — never a
          double gap, never a cramped one. */}
      <div className="mono-label" style={{ marginTop: showBoxes ? 16 : 18, fontSize: 9, color: 'var(--faint)' }}>
        {legendText ? `▨ ${legendText} · ` : ''}
        {askedLabel ? `Asked ${askedLabel} · ` : ''}Query {queryIndex} of {totalQueries}
      </div>
    </ReportSection>
  )
}
