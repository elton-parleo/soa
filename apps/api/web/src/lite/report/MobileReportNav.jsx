/**
 * RM1: the phone replacement for the 222px sticky sidebar (ReportRail.jsx
 * — a fixed-width column that cannot exist on a 360-390px viewport).
 * Three pieces, all hidden at desktop purely via CSS
 * (.lite-report-mobile-nav, theme.css) — never a JS viewport branch, so
 * the desktop tree renders exactly as before this stage:
 *
 *  - ReportSummaryBlock: a compact static block at the very top of the
 *    page — brand mark + name, composite/100, verdict chip. No audited
 *    date: the report payload has no date field to read today (this is
 *    a frontend-only session, no backend addition) — omitted rather
 *    than fabricated.
 *  - MobileStickyBar: appears once the summary block scrolls out of
 *    view (IntersectionObserver on the summary block, the same
 *    technique SoAIndex.jsx already uses for its reveal animation),
 *    showing brand/score/a Sections button. Height stays under the
 *    RM1 56px ceiling via theme.css.
 *  - SectionsSheet: a full-screen sheet listing the same nav items the
 *    desktop rail shows — buildNavItems (reportDerive.js) is the one
 *    source of per-section scores for both renderers, so they can never
 *    disagree. Tapping an item is a plain `<a href="#id">`; the
 *    browser's native anchor jump does the scrolling and
 *    useReportSections' existing scroll-spy picks up the new active
 *    section on its own — this component only closes the sheet, it
 *    never touches scroll position itself.
 */
import { useEffect, useRef, useState } from 'react'
import { BrandLogo, StatusChip, Glyph } from '../../ds/index.js'
import { isAgentReady, isPartialRead, buildNavItems } from './reportDerive.js'

export function ReportSummaryBlock({ report, primaryEntityName, summaryRef }) {
  const pillars = report.pillars
  const composite = report.composite
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
        {pillars.state === 'scored' && (
          <StatusChip tone={isAgentReady(pillars) ? 'success' : 'risk'} size="sm">
            {isAgentReady(pillars) ? 'Agent-ready' : 'Not agent-ready'}
          </StatusChip>
        )}
      </div>
    </div>
  )
}

// Extracted so the "should the sticky bar be up" decision is a plain
// boolean state a test can drive directly (jsdom's IntersectionObserver
// stub — src/test-setup.js — stores its callback but never invokes it,
// so a real intersection can't be simulated end-to-end in jsdom; a live
// browser check covers the real scroll behavior).
export function useSummaryScrolledPast(summaryRef) {
  const [pastSummary, setPastSummary] = useState(false)
  useEffect(() => {
    const el = summaryRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([entry]) => setPastSummary(!entry.isIntersecting), { threshold: 0 })
    io.observe(el)
    return () => io.disconnect()
  }, [summaryRef])
  return pastSummary
}

export function MobileStickyBar({ report, primaryEntityName, visible, sheetOpen, onToggleSheet }) {
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

export function SectionsSheet({ report, exposure, active, open, onClose }) {
  const pillars = report.pillars
  const composite = report.composite
  const partial = isPartialRead(pillars, report.scan?.degraded_reason)
  const navItems = buildNavItems({ pillars, composite, exposure, active, partial })

  // Closing the sheet unmounts the very <a> the browser is mid-navigating
  // from — confirmed live: the native anchor jump loses the race against
  // React's synchronous re-render and the page never actually scrolls
  // (the hash still updates, but scrollY doesn't move). preventDefault
  // and do the scroll ourselves, one frame after the close has painted,
  // so the target section is still there to scroll to and nothing is
  // racing to unmount mid-navigation.
  //
  // scrollIntoView() itself turned out to be unreliable here too —
  // confirmed live, it moved scrollY by ~20px instead of to the target,
  // despite no scrollable ancestor between #tv and the document to
  // explain it. An explicit scrollTo computed from the target's own
  // getBoundingClientRect() (the same math the browser is supposed to
  // do internally) works correctly every time, so that's what actually
  // ships rather than trusting the native shorthand.
  //
  // setTimeout, not requestAnimationFrame — confirmed live, rAF simply
  // never fires in this environment (a headless/backgrounded tab isn't
  // guaranteed to keep painting frames), which silently dropped the
  // scroll entirely. A macrotask still needs to run after the close so
  // the sheet has actually unmounted and stopped covering the page, but
  // it doesn't need to be tied to a paint — setTimeout(…, 0) covers
  // that without depending on the tab being actively rendered.
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
          {navItems.map(({ id, on, meta, score }) => (
            <a
              key={id}
              href={`#${id}`}
              className={`lite-report-mobile-sheet-item${on ? ' lite-report-mobile-sheet-item--on' : ''}`}
              onClick={(e) => jumpTo(e, id)}
            >
              <Glyph name={meta.icon} size={14} color={on ? 'var(--blue)' : 'var(--faint)'} />
              <span className="lite-report-mobile-sheet-item-label">{meta.label}</span>
              <span className="num lite-report-mobile-sheet-item-score">{score}</span>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}

export function MobileReportNav({ report, primaryEntityName, exposure, active }) {
  const summaryRef = useRef(null)
  const pastSummary = useSummaryScrolledPast(summaryRef)
  const [sheetOpen, setSheetOpen] = useState(false)

  return (
    <div className="lite-report-mobile-nav">
      <ReportSummaryBlock report={report} primaryEntityName={primaryEntityName} summaryRef={summaryRef} />
      <MobileStickyBar
        report={report}
        primaryEntityName={primaryEntityName}
        visible={pastSummary}
        sheetOpen={sheetOpen}
        onToggleSheet={() => setSheetOpen((v) => !v)}
      />
      <SectionsSheet report={report} exposure={exposure} active={active} open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </div>
  )
}
