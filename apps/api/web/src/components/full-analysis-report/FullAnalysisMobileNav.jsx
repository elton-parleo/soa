/**
 * fix/full-analysis-mobile, 1a: the phone replacement for FullAnalysisRail's
 * 300px sticky sidebar — mirrors MobileReportNav.jsx's markup, CSS classes
 * (.lite-report-mobile-*, theme.css), and interaction (a compact summary
 * block at the top of the page, a sticky bar that reveals once the summary
 * scrolls out of view via IntersectionObserver, a bottom Sections sheet)
 * exactly, rather than being modified into lite's own component: this
 * report's own section id set (discovery, matrix, analyst, evidence) does
 * not fit lite's fixed buildNavItems/NAV_META vocabulary, the same reason
 * FullAnalysisHero/FullAnalysisRail are siblings of ScoreHero/ReportRail
 * rather than parameterized variants of them.
 *
 * Reuses, never forks: useSummaryScrolledPast (MobileReportNav.jsx — a
 * generic, ref-only hook, no lite-specific coupling) for the reveal
 * timing, and FullAnalysisRail's own NAV_ITEMS/filterNavItems/navScore
 * for the sheet's item list — one source of truth with the desktop rail,
 * so the two can never list different sections or disagree on a score.
 *
 * `active` is passed straight through from FullAnalysisReport.jsx, which
 * currently hardcodes it to 'score' (Full Analysis has no scroll-spy hook
 * wired yet, unlike lite's useReportSections) — this component highlights
 * whatever it's given, matching the desktop rail's own current behavior
 * rather than adding new scroll-spy machinery out of this bug fix's scope.
 */
import { useRef, useState } from 'react'
import { BrandLogo, Glyph, StatusChip, StateChip } from '../../ds/index.js'
import { isAgentReady, isPartialRead, buildMeasurableContext } from '../../lite/report/reportDerive.js'
import { useSummaryScrolledPast } from '../../lite/report/MobileReportNav.jsx'
import { NAV_ITEMS, filterNavItems, navScore } from './FullAnalysisRail.jsx'

const READY_PCT = 60

function MobileSummaryBlock({ report, primaryEntityName, summaryRef }) {
  const pillars = report.pillars
  const composite = report.composite
  const partial = isPartialRead(pillars, report.scan?.degraded_reason)
  const unmeasurable = partial ? buildMeasurableContext(pillars).unmeasurable_points : 0

  return (
    <div className="lite-report-mobile-summary" ref={summaryRef}>
      <div className="lite-report-mobile-summary-brand">
        <BrandLogo name={primaryEntityName} src={report.brand_icon_url} domain={report.store_domain} size={30} />
        <span className="lite-report-mobile-summary-name">{primaryEntityName}</span>
      </div>
      <div className="lite-report-mobile-summary-score-row">
        <span className="num lite-report-mobile-summary-score">
          {composite != null ? Math.round(composite) : '—'}<span className="lite-report-mobile-summary-score-max">/100</span>
        </span>
      </div>
      <div style={{ marginTop: 14 }}>
        <div style={{ position: 'relative', height: 10, borderRadius: 5, background: 'var(--canvas-dim)', boxShadow: 'inset 0 1px 2px rgba(70,69,85,.16),inset 0 0 0 1px rgba(213,209,203,.95)' }}>
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${Math.min(100, composite ?? 0)}%`, borderRadius: 5, background: 'var(--ink)' }} />
          <span aria-hidden="true" style={{ position: 'absolute', left: `${READY_PCT}%`, top: -2, bottom: -2, width: 3, transform: 'translateX(-3px)', borderRadius: 2, background: 'var(--blue)' }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <span className="mono-label" style={{ fontSize: 9, color: 'var(--text-strong)', fontWeight: 600 }}>{composite != null ? Math.round(composite) : '—'} EARNED</span>
          <span className="mono-label" style={{ fontSize: 9, color: 'var(--muted)' }}>READY {READY_PCT}</span>
          <span className="mono-label" style={{ fontSize: 9, color: 'var(--faint)' }}>100</span>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <StatusChip tone={isAgentReady(pillars) ? 'success' : 'risk'} size="sm">{isAgentReady(pillars) ? 'Agent-ready' : 'Not agent-ready'}</StatusChip>
        {partial ? (
          <StateChip state="partial" variant="chip" size="sm">{Math.round(unmeasurable)} pts unread this run</StateChip>
        ) : (
          <StateChip state="seen" variant="chip" size="sm">Fully measured</StateChip>
        )}
      </div>
    </div>
  )
}

function MobileStickyBar({ report, primaryEntityName, visible, sheetOpen, onToggleSheet }) {
  const composite = report.composite
  return (
    <div className={`lite-report-mobile-stickybar${visible ? ' lite-report-mobile-stickybar--visible' : ''}`}>
      <BrandLogo name={primaryEntityName} src={report.brand_icon_url} domain={report.store_domain} size={20} />
      <span className="lite-report-mobile-stickybar-name">{primaryEntityName}</span>
      <span className="num lite-report-mobile-stickybar-score">
        {composite != null ? Math.round(composite) : '—'}<span className="lite-report-mobile-stickybar-score-max">/100</span>
      </span>
      <button
        type="button"
        className="lite-report-mobile-sections-btn"
        onClick={onToggleSheet}
        aria-expanded={sheetOpen}
        aria-haspopup="dialog"
      >
        <Glyph name="grid" size={12} color="var(--text-strong)" />
        Sections
      </button>
    </div>
  )
}

function SectionsSheet({ items, active, open, onClose }) {
  // Same close-then-scroll-ourselves fix MobileReportNav.jsx's own
  // SectionsSheet documents: closing the sheet unmounts the very <a>
  // the browser is mid-navigating from, so the native anchor jump loses
  // the race against React's re-render. preventDefault + an explicit
  // scrollTo one macrotask after the close has painted works reliably;
  // scrollIntoView() and requestAnimationFrame both proved unreliable
  // live for the identical case in lite's own component.
  function jumpTo(e, id) {
    e.preventDefault()
    onClose()
    setTimeout(() => {
      const el = document.getElementById(id)
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY, behavior: 'instant' })
    }, 0)
  }

  if (!open) return null
  return (
    <div className="lite-report-mobile-sheet-overlay" onClick={onClose}>
      <div className="lite-report-mobile-sheet" role="dialog" aria-modal="true" aria-label="Report sections" onClick={(e) => e.stopPropagation()}>
        <div className="lite-report-mobile-sheet-header">
          <span className="mono-label">SECTIONS</span>
          <button type="button" className="lite-report-mobile-sheet-close" onClick={onClose} aria-label="Close sections">
            <Glyph name="x" size={14} color="var(--text-strong)" />
          </button>
        </div>
        <div className="lite-report-mobile-sheet-list">
          {items.map(({ id, icon, label, score }) => {
            const on = active === id
            return (
              <a
                key={id}
                href={`#${id}`}
                className={`lite-report-mobile-sheet-item${on ? ' lite-report-mobile-sheet-item--on' : ''}`}
                onClick={(e) => jumpTo(e, id)}
              >
                <Glyph name={icon} size={14} color={on ? 'var(--blue)' : 'var(--faint)'} />
                <span className="lite-report-mobile-sheet-item-label">{label}</span>
                {score != null && <span className="num lite-report-mobile-sheet-item-score">{score}</span>}
              </a>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function FullAnalysisMobileNav({ report, primaryEntityName, exposure, active, hasContinuation, readOnly = false }) {
  const summaryRef = useRef(null)
  const pastSummary = useSummaryScrolledPast(summaryRef)
  const [sheetOpen, setSheetOpen] = useState(false)
  const pillars = report.pillars
  const composite = report.composite

  const items = filterNavItems(NAV_ITEMS, { hasContinuation, transcript: report.transcript, readOnly })
    .map(({ id, icon, label }) => ({
      id, icon, label,
      score: navScore({ id, pillars, composite, totalQueries: report.total_queries, transcript: report.transcript, exposure }),
    }))

  return (
    <div className="lite-report-mobile-nav">
      <MobileSummaryBlock report={report} primaryEntityName={primaryEntityName} summaryRef={summaryRef} />
      <MobileStickyBar
        report={report} primaryEntityName={primaryEntityName}
        visible={pastSummary} sheetOpen={sheetOpen}
        onToggleSheet={() => setSheetOpen((v) => !v)}
      />
      <SectionsSheet items={items} active={active} open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </div>
  )
}
