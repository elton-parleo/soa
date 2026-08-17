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
 */
import { useState } from 'react'
import { MonoTag } from '../../ds/index.js'
import { ReportSection } from './ReportSection.jsx'
import { HowItsScoredButton } from './HowItsScored.jsx'
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

export function TranscriptSection({ report, open, onToggle }) {
  const [showFull, setShowFull] = useState(false)
  const transcript = report.transcript
  if (!transcript) return null

  const {
    platform, query_text: queryText, query_index: queryIndex, total_queries: totalQueries,
    asked_at: askedAt, response_text: responseText, preview_cutoff: previewCutoff,
    spans, narrative_case: narrativeCase, right, leaked,
  } = transcript

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

      <div style={{ background: 'var(--surface-warm)', border: '1px solid var(--hairline)', borderRadius: 18, padding: '22px 24px' }}>
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

      <div className="mono-label" style={{ marginTop: 16, fontSize: 9, color: 'var(--faint)' }}>
        {legendText ? `▨ ${legendText} · ` : ''}
        {askedLabel ? `Asked ${askedLabel} · ` : ''}Query {queryIndex} of {totalQueries}
      </div>
    </ReportSection>
  )
}
