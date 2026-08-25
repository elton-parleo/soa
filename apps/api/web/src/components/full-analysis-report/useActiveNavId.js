/**
 * fix/full-analysis-rail-nav, 2c: the rail's "IN THIS REPORT" active
 * highlight was a hardcoded literal 'score', passed straight through
 * to FullAnalysisRail/FullAnalysisMobileNav and never updated — the
 * highlighted row never changed as the reader scrolled, regardless of
 * which section was actually on screen. Real scroll-spy, same
 * mechanism as lite's own useReportSections.js (computeActiveSectionId
 * — same ids-in-order scan, same 140px threshold), parameterized by
 * Full Analysis's own id set instead of lite's hardcoded one — this
 * report has ids (continuation/discovery/matrix/analyst/evidence) lite
 * doesn't, and no focus-mode state to carry, so this is a standalone
 * hook rather than a call into useReportSections() itself.
 */
import { useEffect, useState } from 'react'
import { computeActiveSectionId } from '../../lite/report/scrollSpy.js'

export function useActiveNavId(ids) {
  const [active, setActive] = useState(ids[0])

  useEffect(() => {
    function onScroll() {
      const cur = computeActiveSectionId(ids)
      setActive((prev) => (cur !== prev ? cur : prev))
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join('|')])

  return active
}
