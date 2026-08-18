/**
 * Owner-side Share control for a Full Analysis report — the "Share
 * report" button (creates the link lazily on first click, via
 * ShareReportButton's resolveToken/buildUrl extension — see that
 * file's docstring) plus a small "Manage link" affordance with Revoke
 * once a link is active. Fetches the current share status on mount
 * (read-only — GET never creates) so a returning owner sees "Manage
 * link" immediately rather than "Share report" flashing first.
 *
 * `key={shareToken || 'none'}` on ShareReportButton below is load-
 * bearing, not decoration: ShareReportButton seeds its own internal
 * resolved-token state from its `token` prop only once, at mount
 * (exactly like it always has for lite). Without the key, revoking
 * here would update shareToken to null in THIS component but leave
 * the button holding the stale, now-invalid token in its own state —
 * the key forces a clean remount whenever the share identity itself
 * changes (created, revoked, or swapped), not on every render.
 */
import { useEffect, useState } from 'react'
import { api } from '../../api.js'
import { ShareReportButton } from '../../lite/report/ShareReportButton.jsx'
import { fullAnalysisReportUrl } from '../../publicFullAnalysisUrls.js'

export function FullAnalysisShareControl({ cycleCode }) {
  const [shareToken, setShareToken] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [revoking, setRevoking] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoaded(false)
    api.getShareLink(cycleCode)
      .then((link) => { if (!cancelled) setShareToken(link?.token || null) })
      .catch(() => { if (!cancelled) setShareToken(null) })
      .finally(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
  }, [cycleCode])

  async function ensureToken() {
    const link = await api.createShareLink(cycleCode)
    setShareToken(link.token)
    return link.token
  }

  async function handleRevoke() {
    setRevoking(true)
    try {
      await api.revokeShareLink(cycleCode)
      setShareToken(null)
    } catch (err) {
      alert(`Could not revoke the share link: ${err.message}`)
    } finally {
      setRevoking(false)
    }
  }

  if (!loaded) return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
      <ShareReportButton
        key={shareToken || 'none'}
        token={shareToken}
        resolveToken={shareToken ? undefined : ensureToken}
        buildUrl={fullAnalysisReportUrl}
        placement="full_analysis_owner"
        style={{ width: 'auto' }}
      />
      {shareToken && (
        <button
          type="button"
          onClick={handleRevoke}
          disabled={revoking}
          style={{
            background: 'none', border: 'none', color: 'var(--faint)', fontSize: 12,
            cursor: revoking ? 'default' : 'pointer', padding: 0, textDecoration: 'underline',
          }}
        >
          {revoking ? 'Revoking…' : 'Revoke link'}
        </button>
      )}
    </div>
  )
}
