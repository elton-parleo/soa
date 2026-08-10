/**
 * 1b: one shared expand/collapse primitive for every local (non-section)
 * expander on the report page — per-dimension "How it's scored" panels,
 * WHY N/A, ADJUST ASSUMPTIONS.
 *
 * The bug this replaces: several call sites passed a useState setter
 * straight to onClick (`onClick={setOpen}`). A DOM click handler is
 * always invoked with the SyntheticEvent as its first argument, so that
 * call was really `setOpen(event)` — a truthy object every time, not a
 * toggle. First click opened the panel; every click after that "set"
 * state to a new (still truthy) event object, so it could never close.
 * useCollapsible's toggle is a real closure (`setOpen(v => !v)`), so it
 * can be handed to onClick directly and still behave as a toggle no
 * matter what argument the event system passes it.
 *
 * Keyboard: the trigger is a real `<button>`, so Enter/Space already
 * fire a click via native browser semantics — no separate onKeyDown is
 * added here, since duplicating that logic would double-toggle (native
 * click firing once from the key, and a second time from a hand-rolled
 * handler) in a real browser. Tests exercise activation via click,
 * exactly how RTL recommends testing button semantics.
 *
 * Analytics session: section_expanded fires exactly once, here, inside
 * toggle() — every local expander on the report (every call site below
 * hand-rolls its own trigger button, but all of them already call this
 * hook for their open/toggle state) reports for free by passing a
 * `{section, control}` tracking id, rather than each call site adding
 * its own track() call. Fires only on the open transition, never on
 * close — "expanded" is a one-directional signal.
 */
import { useState } from 'react'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

export function useCollapsible(initialOpen = false, trackingId = null) {
  const [open, setOpen] = useState(initialOpen)
  function toggle() {
    setOpen((v) => {
      const next = !v
      if (next && trackingId) {
        track(EVENTS.SECTION_EXPANDED, { section: trackingId.section, control: trackingId.control })
      }
      return next
    })
  }
  return [open, toggle, setOpen]
}

export function CollapsibleTrigger({ open, onToggle, children, style, className }) {
  return (
    <button type="button" onClick={onToggle} aria-expanded={open} style={style} className={className}>
      {children}
    </button>
  )
}
