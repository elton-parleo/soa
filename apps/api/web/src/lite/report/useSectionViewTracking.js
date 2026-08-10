/**
 * Analytics session (Q2 — which sections actually get read): fires
 * section_viewed once per section id per report load, when that
 * section is at least 50% visible for a continuous 1s. One hook, one
 * IntersectionObserver per id, wired centrally in LiteFullReportV4.jsx
 * — not per-section-component — over the report's own existing
 * section ids (NAV_IDS, useReportSections.js), which every top-level
 * section already renders as a real DOM id (ReportSection's `id`
 * prop, ScoreHero's `id="score"`, TrueSyncBand's `id="truesync"`).
 * A section that doesn't render this run (e.g. `why`/DiscoveryFinding
 * on a fully-scored report) simply has no element to observe and is
 * silently skipped.
 */
import { useEffect } from 'react'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

const DWELL_MS = 1000
const VISIBLE_THRESHOLD = 0.5

export function useSectionViewTracking(sectionIds) {
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return undefined

    const seen = new Set()
    const timers = new Map()
    const observers = []

    sectionIds.forEach((id) => {
      const el = document.getElementById(id)
      if (!el) return

      const observer = new IntersectionObserver(
        ([entry]) => {
          if (seen.has(id)) return
          const visibleEnough = entry.isIntersecting && entry.intersectionRatio >= VISIBLE_THRESHOLD
          if (visibleEnough) {
            if (!timers.has(id)) {
              const timerId = setTimeout(() => {
                timers.delete(id)
                if (!seen.has(id)) {
                  seen.add(id)
                  track(EVENTS.SECTION_VIEWED, { section: id })
                }
              }, DWELL_MS)
              timers.set(id, timerId)
            }
          } else if (timers.has(id)) {
            clearTimeout(timers.get(id))
            timers.delete(id)
          }
        },
        { threshold: VISIBLE_THRESHOLD },
      )
      observer.observe(el)
      observers.push(observer)
    })

    return () => {
      observers.forEach((o) => o.disconnect())
      timers.forEach((t) => clearTimeout(t))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
