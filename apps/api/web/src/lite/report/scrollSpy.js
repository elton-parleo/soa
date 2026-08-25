/**
 * fix/full-analysis-rail-nav: the pure "which section is the reader
 * looking at" computation, extracted out of useReportSections.js's own
 * scroll handler unchanged (same ids-in-order scan, same 140px
 * threshold) so Full Analysis's own scroll-spy (its own id set —
 * continuation/discovery/matrix/analyst/evidence, none of which lite
 * has — and no focus-mode state to carry) can reuse the identical
 * mechanism without either report importing the other's hook. Pure
 * function, no DOM writes, easy to unit test on its own.
 */
export function computeActiveSectionId(ids, offset = 140) {
  let cur = ids[0]
  for (const id of ids) {
    const el = document.getElementById(id)
    if (el && el.getBoundingClientRect().top <= offset) cur = id
  }
  return cur
}
