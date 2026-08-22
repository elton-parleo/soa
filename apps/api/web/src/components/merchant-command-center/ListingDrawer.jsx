import React, { useEffect, useState } from 'react'
import {
  driftFindings, publicationHistoryForCell, relativeTime, absoluteTime,
  gmcDeepLink, VERIFICATION_LABEL,
} from './truesyncDerive.js'

// Publish status -> the badge vocabulary the mock uses.
function statusBadge(cell) {
  if (cell.publishState === 'failed') return ['fail', 'Publish failed']
  if (cell.publishState === 'never') return ['hold', 'Never published']
  if (cell.publishState === 'compiled_not_published') return ['hold', 'Compiled — not published']
  if (cell.publishState === 'withdrawn') return ['hold', 'Withdrawn']
  if (cell.verification.kind === 'drift') {
    return ['drift', `Drift · ${cell.verification.findingCount} field${cell.verification.findingCount === 1 ? '' : 's'}`]
  }
  if (cell.verification.kind === 'failed') return ['fail', 'Verification failed']
  if (cell.verification.kind === 'verified') return ['sync', 'In sync']
  return ['hold', 'Published — not yet verified']
}

// Expressiveness severity -> the checklist's tick style. These come
// straight off the publication row: real, live data describing what a
// protocol could not carry (e.g. "GMC: no amount-off field; carried as
// sale_price, so the mechanic is lost").
const SEVERITY_TICK = { dropped: 'bad', approximate: 'warn', lossy: 'warn' }

function ArtifactBlock({ label, value }) {
  if (value == null) return null
  return (
    <details className="mcc-artifact">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

/**
 * The drift inspector — per-channel detail for one listing, opened by
 * selecting a matrix row. Follows the mock's two-column detail layout:
 * the comparison table on the left, the compiler/validator card on the
 * right.
 *
 * The mock's separate Publications tab lives here instead, as the
 * publish timeline: every publication event for the selected cell is
 * already in the payload the matrix loaded, so folding it into the
 * drawer costs one map() and puts the log next to the artifact it
 * describes — rather than a fourth tab that reloads the same rows.
 */
export default function ListingDrawer({
  row, channels, channelState, cellFor, publications, verificationsByCell,
  onClose, onPublish, publishPending,
}) {
  const [channelSlug, setChannelSlug] = useState(channels[0]?.slug)

  // Reset the channel selection when a different row is opened, so the
  // drawer never shows row B against the channel tab row A was on.
  useEffect(() => { setChannelSlug(channels[0]?.slug) }, [row.listingId, channels])

  // Verification history comes from the page's matrix-wide load rather
  // than a fetch of its own — one source, so the drawer can never
  // disagree with the badge on the row that opened it. `undefined`
  // means that pass has not finished yet; [] means it finished and
  // found nothing.
  const cellKey = `${row.listingId}:${channelSlug}`
  const verifications = verificationsByCell?.[cellKey]
  const verificationsLoading = verifications === undefined

  const channel = channels.find((c) => c.slug === channelSlug)
  if (!channel) return null

  const cell = cellFor(row, channel)
  const [badgeKind, badgeText] = statusBadge(cell)
  const history = publicationHistoryForCell(publications, row.listingId, channel.slug)
  const current = history[0] || null
  const newestVerification = (verifications || [])[0] || null
  const findings = newestVerification ? driftFindings(newestVerification) : []
  const deepLink = channel.slug === 'merchant_center' ? gmcDeepLink(cell.externalRef) : null

  return (
    <div className="mcc-drawer">
      {/* ── left: comparison + artifact + timeline ─────────────────── */}
      <div className="mcc-panel">
        <div className="mcc-drawer-head">
          <h3>{row.name} — {channel.name}</h3>
          <span className={`mcc-badge ${badgeKind}`}>{badgeText}</span>
          <button className="mcc-btn mcc-drawer-close" onClick={onClose}>Close</button>
        </div>

        <div className="mcc-chanpicker" role="tablist" aria-label="Channel">
          {channels.map((c) => (
            <button
              key={c.slug}
              role="tab"
              aria-selected={c.slug === channelSlug}
              className={`${c.slug === channelSlug ? 'active' : ''} ${channelState[c.slug]?.muted ? 'muted' : ''}`}
              title={c.depth_label}
              onClick={() => setChannelSlug(c.slug)}
            >
              {c.name}
            </button>
          ))}
        </div>

        {/* Master vs surface. Rendered only when a verification run
            actually produced findings — there is nothing to compare
            against otherwise, and an empty table with green ticks in it
            would be an invention. */}
        <div className="mcc-section">
          <h4>Master record vs. surface</h4>
          {verificationsLoading && <div className="mcc-empty">Loading verification history…</div>}
          {!verificationsLoading && findings.length === 0 && (
            <div className="mcc-empty">
              {newestVerification
                ? 'Newest verification recorded no drift.'
                : 'No verification run has been recorded for this listing on this channel, so there is nothing to compare. The badge stays ○.'}
            </div>
          )}
          {findings.length > 0 && (
            <table className="mcc-kv">
              <thead>
                <tr>
                  <th style={{ width: '22%' }}>Field</th>
                  <th>Variant</th>
                  <th>Master record</th>
                  <th>On surface</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f, i) => (
                  <tr key={`${f.field}-${f.variant}-${i}`}>
                    <td className="field">{f.field}</td>
                    <td className="mcc-val">{f.variant || '—'}</td>
                    <td><span className="mcc-val good">{String(f.expected ?? '—')}</span></td>
                    <td>
                      {f.observed == null
                        ? <span className="mcc-val missing">missing</span>
                        : <span className="mcc-val bad">{String(f.observed)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Published artifact — what was actually sent to this surface. */}
        <div className="mcc-section">
          <h4>Published artifact</h4>
          {current?.payload != null
            ? <ArtifactBlock label="Show compiled payload (JSON)" value={current.payload} />
            : <div className="mcc-empty">Nothing has been compiled for this channel yet.</div>}
        </div>

        {/* The publish timeline — the mock's Publications tab, folded in. */}
        <div className="mcc-section">
          <h4>Publish timeline</h4>
          {history.length === 0 && (
            <div className="mcc-empty">No publication events recorded for this channel.</div>
          )}
          <ul className="mcc-timeline">
            {history.map((p) => {
              const at = p.published_at || p.compiled_at
              const dot = p.status === 'published' ? 'sync'
                : p.status === 'failed' ? 'fail'
                : 'hold'
              return (
                <li key={p.id ?? `${p.channel_slug}-${at}`}>
                  <span className="mcc-dot" style={{ display: 'none' }} />
                  <span className="when mono" title={absoluteTime(at) || ''}>
                    {relativeTime(at) || '—'}
                  </span>
                  <span className="what">
                    <span className={`mcc-dot ${dot}`} style={{ display: 'inline-block', marginRight: 8 }} />
                    <strong>{p.status}</strong>
                    {p.spec_version && <span className="mono"> · {p.spec_version}</span>}
                    {p.error && <div className="detail">{p.error}</div>}
                    {p.validation && p.validation.ok === false && Array.isArray(p.validation.errors) && p.validation.errors.length > 0 && (
                      <div className="detail">Validation: {p.validation.errors.join('; ')}</div>
                    )}
                    {p.external_ref && <div className="detail mono">{p.external_ref}</div>}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>

        {/* Verification timeline. For Merchant Center this is where the
            item-level diagnostics land (publish -> pending -> approved);
            the same rendering serves every channel, since the endpoint
            and its record shape are the same for all of them. */}
        <div className="mcc-section">
          <h4>
            Verification history
            {channel.slug === 'merchant_center' && ' · Merchant Center item issues'}
          </h4>
          {(verifications || []).length === 0 && !verificationsLoading && (
            <div className="mcc-empty">
              No verification runs recorded.
              {channel.slug === 'merchant_center' &&
                ' Use "Refresh Google diagnostics" above to ask TrueSync to read Merchant Center statuses back.'}
            </div>
          )}
          <ul className="mcc-timeline">
            {(verifications || []).map((v) => {
              const drift = driftFindings(v)
              return (
                <li key={v.id}>
                  <span className="when mono">{v.method || '—'}</span>
                  <span className="what">
                    <strong>{v.phase}</strong>
                    {v.gtin && <span className="mono"> · {v.gtin}</span>}
                    <div className="detail">
                      {drift.length > 0
                        ? `${drift.length} finding${drift.length === 1 ? '' : 's'}`
                        : VERIFICATION_LABEL.verified}
                    </div>
                    {v.observed && <ArtifactBlock label="Observed payload" value={v.observed} />}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>

      {/* ── right: compiler & validator ────────────────────────────── */}
      <div className="mcc-panel mcc-side">
        <h3>Compiler &amp; validator</h3>

        <ul className="mcc-checklist">
          {cell.validation && (
            <li>
              <span className={`mcc-tick ${cell.validation.ok ? 'ok' : 'bad'}`}>
                {cell.validation.ok ? '✓' : '✕'}
              </span>
              <span>
                {cell.validation.ok
                  ? 'Payload validates against the channel spec'
                  : `Validation failed: ${(cell.validation.errors || []).join('; ') || 'no detail given'}`}
              </span>
            </li>
          )}

          {/* Expressiveness flags are the richest real signal this API
              gives: which fields a protocol could not carry, and why. */}
          {(cell.expressiveness || []).map((flag, i) => (
            <li key={`${flag.field}-${i}`}>
              <span className={`mcc-tick ${SEVERITY_TICK[flag.severity] || 'warn'}`}>
                {flag.severity === 'dropped' ? '✕' : '!'}
              </span>
              <span>
                <strong>{flag.field}</strong> — {flag.severity}
                <br />
                {flag.note}
              </span>
            </li>
          ))}

          {!cell.validation && (cell.expressiveness || []).length === 0 && (
            <li className="mcc-empty">No compiler output recorded for this channel.</li>
          )}
        </ul>

        <div className="meta">
          <span>Depth: <span className="mono">{channel.depth_label}</span></span>
          {channel.spec_version && <span>Spec: <span className="mono">{channel.spec_version}</span></span>}
          <span>
            Compiled: <span className="mono">{absoluteTime(current?.compiled_at) || '—'}</span>
          </span>
          <span>
            Published: <span className="mono">{absoluteTime(current?.published_at) || 'never'}</span>
          </span>
          <span>
            external_ref:{' '}
            {cell.externalRef
              ? (deepLink
                  ? <a className="mono" href={deepLink} target="_blank" rel="noreferrer">{cell.externalRef}</a>
                  : <span className="mono">{cell.externalRef}</span>)
              : <span className="mono">—</span>}
          </span>
          {row.catalogProductId != null && (
            <span>catalog_product_id: <span className="mono">{row.catalogProductId}</span></span>
          )}
          <span>listing_id: <span className="mono">{row.listingId}</span></span>
          {row.productUrl && (
            <span><a href={row.productUrl} target="_blank" rel="noreferrer">Open product page ↗</a></span>
          )}
        </div>

        <div style={{ marginTop: 14, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="mcc-btn primary"
            onClick={() => onPublish(row, channel.slug)}
            disabled={publishPending}
          >
            {publishPending ? <><span className="mcc-spinner" /> Publishing…</> : 'Publish now'}
          </button>
          {/* No "Verify now": TrueSync exposes no verify endpoint at all
              (no POST /listings/{id}/verify, no POST /verify-all — see
              the report). A button that did nothing, or that quietly
              called something else, would be worse than its absence. */}
          <button
            className="mcc-btn"
            disabled
            title="Wire-up pending — TrueSync exposes no per-listing verify endpoint yet"
          >
            Verify now
          </button>
        </div>
      </div>
    </div>
  )
}
