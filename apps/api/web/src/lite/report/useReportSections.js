/**
 * R2/R3: section collapse + focus-mode state machine, ported faithfully
 * from the mock's own DCLogic (design-refs/.../Audit Report.dc.html) —
 * it's subtle (the scroll-anchor-holding in particular) and already
 * correct there, so this is a straight translation to a React hook, not
 * a redesign.
 *
 * NAV_IDS drives the rail's scroll-spy (every anchor a nav row can
 * point at). SECTION_KEYS is the subset with an Expand/Collapse toggle
 * — "score" and "truesync" have no collapse affordance in the mock.
 */
import { useEffect, useRef, useState } from 'react'

export const NAV_IDS = ['score', 'viz', 'acc', 'tv', 'fun', 'fix', 'truesync', 'exp']
export const SECTION_KEYS = ['viz', 'acc', 'tv', 'fun', 'fix', 'exp']

export function useReportSections() {
  const [sec, setSec] = useState({})
  const [focus, setFocus] = useState(false)
  const [active, setActive] = useState(NAV_IDS[0])
  const lockRef = useRef(false)
  const anchorRef = useRef(null)
  const vpTopRef = useRef(null)
  const focusRef = useRef(focus)
  const activeRef = useRef(active)

  useEffect(() => { focusRef.current = focus }, [focus])
  useEffect(() => { activeRef.current = active }, [active])

  useEffect(() => {
    function onScroll() {
      if (lockRef.current) return
      let cur = NAV_IDS[0]
      for (const id of NAV_IDS) {
        const el = document.getElementById(id)
        if (el && el.getBoundingClientRect().top <= 140) cur = id
      }
      if (cur !== activeRef.current) {
        if (focusRef.current) {
          const el = document.getElementById(cur)
          anchorRef.current = cur
          vpTopRef.current = el ? el.getBoundingClientRect().top : null
        }
        setActive(cur)
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // In focus mode, opening a new section changes page heights below the
  // fold — hold the section you scrolled to still by compensating the
  // scroll position after the DOM updates.
  useEffect(() => {
    if (!focus || !anchorRef.current || vpTopRef.current == null) return
    const id = anchorRef.current
    const el = document.getElementById(id)
    if (el) {
      const delta = el.getBoundingClientRect().top - vpTopRef.current
      if (Math.abs(delta) > 1) {
        lockRef.current = true
        window.scrollBy(0, delta)
        requestAnimationFrame(() => { lockRef.current = false })
      }
    }
    anchorRef.current = null
    vpTopRef.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  function isOpen(key) {
    return focus ? active === key : sec[key] !== false
  }

  function toggleSection(key) {
    setFocus(false)
    setSec((s) => ({ ...s, [key]: s[key] === false ? true : false }))
  }

  const anyOpen = SECTION_KEYS.some(isOpen)
  const allLabel = focus ? 'Expand all' : (anyOpen ? 'Collapse all' : 'Expand all')

  function toggleAll() {
    if (focus) {
      const n = {}
      for (const k of SECTION_KEYS) n[k] = true
      setFocus(false)
      setSec(n)
      return
    }
    if (anyOpen) {
      setFocus(true)
      return
    }
    const n = {}
    for (const k of SECTION_KEYS) n[k] = true
    setFocus(false)
    setSec(n)
  }

  return { active, focus, isOpen, toggleSection, allLabel, toggleAll }
}
