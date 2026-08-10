/**
 * Restores the pre-V4 "Copy link" pill (see liteTheme.jsx's
 * ReportHeaderBar at commit b0cd8c9, dropped in the V4 rewrite) as a
 * proper DS-styled Share button, in two placements: the desktop rail
 * (full) and the mobile summary block (full) + sticky bar (compact,
 * icon-only). Hand-rolled rather than wrapping ds/Button.jsx — same
 * convention MobileReportNav.jsx's own sticky-bar "Sections" button
 * already uses, since Button's single-child-span API doesn't fit an
 * icon+label pair that also needs to swap state and carry a tooltip.
 *
 * The copied URL is always built from PUBLIC_AUDIT_BASE_URL + /r/
 * {token} (reportUrl(), publicUrls.js) — never window.location.href —
 * so a paste is always the canonical audit-host link: no query string,
 * no hash, no legacy host, regardless of what path/embed this button
 * happened to render from.
 *
 * `placement` (analytics session) identifies WHICH of the 3 call sites
 * fired a copy — `compact` alone can't, since desktop rail and mobile
 * summary both render the full (non-compact) variant.
 */
import { useEffect, useRef, useState } from 'react'
import { Glyph } from '../../ds/index.js'
import { reportUrl } from '../publicUrls.js'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

const CONFIRM_MS = 2000

function copyViaExecCommand(text) {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch (_) {
    return false
  }
}

async function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch (_) {
      // Falls through to the execCommand path below — some mobile
      // browsers reject clipboard.writeText outside a "real" user
      // gesture even though this handler IS one.
    }
  }
  return copyViaExecCommand(text)
}

const visuallyHidden = {
  position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
  overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0,
}

export function ShareReportButton({ token, compact = false, style, placement }) {
  const url = reportUrl(token)
  const [copied, setCopied] = useState(false)
  const [announce, setAnnounce] = useState('')
  const [fallbackOpen, setFallbackOpen] = useState(false)
  const timeoutRef = useRef(null)
  const buttonRef = useRef(null)
  const fallbackInputRef = useRef(null)

  useEffect(() => () => clearTimeout(timeoutRef.current), [])

  useEffect(() => {
    if (fallbackOpen && fallbackInputRef.current) {
      fallbackInputRef.current.focus()
      fallbackInputRef.current.select()
    }
  }, [fallbackOpen])

  async function handleCopy() {
    const ok = await copyToClipboard(url)
    if (!ok) {
      setFallbackOpen(true)
      return
    }
    setFallbackOpen(false)
    setCopied(true)
    track(EVENTS.SHARE_COPIED, { placement })
    // aria-live only announces on a text change — clear first so a
    // repeat click (re-copy while already in the copied state) still
    // fires a fresh announcement, not a silent no-op.
    setAnnounce('')
    setTimeout(() => setAnnounce('Link copied'), 0)
    clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setCopied(false), CONFIRM_MS)
    buttonRef.current?.focus()
  }

  return (
    <span style={{ position: 'relative', display: compact ? 'inline-block' : 'block' }}>
      {compact ? (
        <button
          ref={buttonRef}
          type="button"
          onClick={handleCopy}
          className="lite-report-mobile-sections-btn"
          aria-label={copied ? 'Link copied' : 'Share report'}
          style={style}
        >
          <Glyph name={copied ? 'check' : 'link'} size={13} color={copied ? 'var(--green)' : 'var(--text-strong)'} />
        </button>
      ) : (
        <button
          ref={buttonRef}
          type="button"
          onClick={handleCopy}
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            width: '100%', minHeight: 44, padding: '7px 16px', borderRadius: 999,
            background: 'rgba(255,255,255,.55)', border: '1px solid var(--border-strong)',
            fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 520, letterSpacing: '-0.005em',
            color: copied ? 'var(--green)' : 'var(--text-strong)', cursor: 'pointer',
            ...style,
          }}
        >
          <Glyph name={copied ? 'check' : 'link'} size={14} color={copied ? 'var(--green)' : 'var(--text-strong)'} />
          <span>{copied ? 'Copied' : 'Share report'}</span>
        </button>
      )}

      {compact && copied && (
        <span
          role="presentation"
          style={{
            position: 'absolute', bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: 6,
            background: 'var(--ink)', color: 'var(--dark-text)', fontSize: 11, fontWeight: 560,
            padding: '4px 9px', borderRadius: 6, whiteSpace: 'nowrap', pointerEvents: 'none',
          }}
        >
          Copied
        </span>
      )}

      <span aria-live="polite" style={visuallyHidden}>{announce}</span>

      {fallbackOpen && (
        <span style={{ position: 'absolute', top: '100%', left: 0, marginTop: 6, zIndex: 10, display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 10, boxShadow: 'var(--shadow-card)', padding: 6, whiteSpace: 'nowrap' }}>
          <input
            ref={fallbackInputRef}
            type="text"
            readOnly
            value={url}
            onFocus={(e) => e.target.select()}
            style={{ width: 180, fontSize: 11.5, fontFamily: 'var(--font-mono)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 8px', color: 'var(--text)' }}
          />
          <button
            type="button"
            onClick={handleCopy}
            style={{ minHeight: 32, padding: '6px 10px', borderRadius: 6, border: 'none', background: 'var(--ink)', color: '#fff', fontSize: 11.5, fontWeight: 600, cursor: 'pointer' }}
          >
            Copy
          </button>
        </span>
      )}
    </span>
  )
}
