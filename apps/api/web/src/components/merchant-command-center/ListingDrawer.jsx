import React, { useEffect, useState } from 'react'
import {
  parseVerification, publicationHistoryForCell, relativeTime, absoluteTime,
  gmcDeepLink, VERIFICATION_LABEL,
} from './truesyncDerive.js'

/**
 * Renders any API-supplied value as text, or `fallback` when there is
 * nothing to show.
 *
 * Every scalar in this panel goes through it. The reason is narrow and
 * concrete: React throws "Objects are not valid as a React child" the
 * moment a field the API has always sent as a string arrives as an
 * object, and that throw takes the whole panel down. TrueSync's
 * verification records are typed as free-form objects and have already
 * changed shape once (the 2026-08-24 envelope), so treating any single
 * field's type as settled is not safe.
 *
 * null, undefined and '' all read as the fallback — "—" — never as an
 * empty gap that looks like a rendering bug.
 */
function text(value, fallback = '—') {
  if (value == null || value === '') return fallback
  const type = typeof value
  if (type === 'string' || type === 'number' || type === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch (_) {
    return fallback
  }
}

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

  // Circular structures and BigInt both make JSON.stringify throw. A
  // payload we cannot pretty-print is still worth showing badly.
  let pretty
  try {
    pretty = JSON.stringify(value, null, 2)
  } catch (err) {
    pretty = `Could not serialise this payload: ${err?.message || 'unknown error'}`
  }
  if (pretty === undefined) pretty = String(value)

  return (
    <details className="mcc-artifact">
      <summary>{label}</summary>
      <pre>{pretty}</pre>
    </details>
  )
}

// GMC issue severity -> the page's status colours. 'pending' is its own
// step rather than a warning: publish -> pending -> approved is the
// expected happy path, and colouring an in-flight review amber reads as
// a problem the merchant has to act on.
const GMC_SEVERITY_CLASS = {
  error: 'fail',
  warning: 'drift',
  pending: 'hold',
  info: 'hold',
}

const GMC_SEVERITY_TICK = {
  error: 'bad',
  warning: 'warn',
  pending: 'warn',
  info: 'ok',
}

/**
 * A gmc_diagnostics record — the traceability beat the drawer spec asks
 * for: publish -> pending -> approved, with the item-level issues
 * Merchant Center reported, severity-coloured.
 *
 * Never rendered through the master-vs-surface table: a GMC record
 * carries an approval state and an issue list, not field comparisons,
 * and forcing it through the field parser is what made every GMC row
 * read as one unit of catalog drift.
 */
function GmcDiagnosticsRecord({ parsed, record }) {
  return (
    <div className="mcc-gmc">
      <div className="mcc-gmc-head">
        <span className={`mcc-badge ${parsed.approved ? 'sync' : 'fail'}`}>
          {parsed.approved ? 'Approved' : 'Not approved'}
        </span>
        {parsed.httpStatus != null && (
          <span className="mcc-gmc-status mono">HTTP {parsed.httpStatus}</span>
        )}
        {record?.created_at && (
          <span className="mcc-gmc-when" title={absoluteTime(record.created_at) || ''}>
            {relativeTime(record.created_at) || ''}
          </span>
        )}
        {record?.observed?.offerId && (
          <span className="mcc-gmc-offer mono">{text(record.observed.offerId)}</span>
        )}
      </div>

      {parsed.issues.length === 0 ? (
        <p className="mcc-empty">
          {parsed.approved
            ? 'Merchant Center reports no outstanding item issues.'
            : 'Merchant Center has not approved this item and reported no itemised issues.'}
          {parsed.httpStatus === 404 &&
            ' The item was not found in the account — it has not been accepted into the feed yet.'}
        </p>
      ) : (
        <ul className="mcc-gmc-issues">
          {parsed.issues.map((issue, i) => (
            <li key={`${issue.code}-${i}`} className={`sev-${issue.severity}`}>
              <span className={`mcc-dot ${GMC_SEVERITY_CLASS[issue.severity] || 'hold'}`} />
              <span className="mcc-gmc-issue-body">
                <span className="mcc-gmc-code mono">{text(issue.code, 'unnamed issue')}</span>
                <span className={`mcc-tick ${GMC_SEVERITY_TICK[issue.severity] || 'warn'}`}>
                  {text(issue.severity)}
                </span>
                {issue.description && <div className="detail">{text(issue.description)}</div>}
                {issue.detail && <div className="detail">{text(issue.detail)}</div>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * A record no parser understood. Visible and self-describing, and
 * counted as a warning rather than as drift — see verificationBadge().
 */
function UnparsedRecord({ parsed, record }) {
  return (
    <div className="mcc-unparsed" role="status">
      <strong>
        Couldn’t parse verification record (method: {text(parsed.method, 'none given')})
      </strong>
      <div className="detail">{text(parsed.reason)}</div>
      <div className="detail">
        Not counted as drift — this is a gap in this page, not a finding about the catalog.
      </div>
      {record?.drift != null && (
        <ArtifactBlock label="Show the raw drift payload" value={record.drift} />
      )}
    </div>
  )
}

// The master-vs-surface comparison, for records that produced real
// field-level findings.
function FindingsTable({ findings }) {
  return (
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
            <td className="field">{text(f.field)}</td>
            <td className="mcc-val">{text(f.variant)}</td>
            <td><span className="mcc-val good">{text(f.expected)}</span></td>
            <td>
              {f.observed == null
                ? <span className="mcc-val missing">missing</span>
                : <span className="mcc-val bad">{text(f.observed)}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
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

  // Previously `return null`, which made a selected row render nothing
  // at all — a dead click by another route. If the channel list is
  // empty or the selected slug has gone away, say so.
  if (!channel) {
    return (
      <div className="mcc-drawer-error mcc-panel" role="alert">
        <div className="mcc-drawer-head">
          <h3>{text(row?.name, 'This listing')} — no channel to show</h3>
          <button className="mcc-btn mcc-drawer-close" onClick={onClose}>Close</button>
        </div>
        <div className="mcc-section">
          <p className="mcc-empty">
            TrueSync returned no channels, so there is no surface to inspect this
            listing against.
          </p>
        </div>
      </div>
    )
  }

  const cell = cellFor(row, channel)
  const [badgeKind, badgeText] = statusBadge(cell)
  const history = publicationHistoryForCell(publications, row.listingId, channel.slug)
  const current = history[0] || null
  const newestVerification = (verifications || [])[0] || null
  const parsedNewest = newestVerification ? parseVerification(newestVerification) : null
  const deepLink = channel.slug === 'merchant_center' ? gmcDeepLink(cell.externalRef) : null

  return (
    <div className="mcc-drawer">
      {/* ── left: comparison + artifact + timeline ─────────────────── */}
      <div className="mcc-panel">
        <div className="mcc-drawer-head">
          <h3>{text(row.name, `Listing ${text(row.listingId)}`)} — {text(channel.name)}</h3>
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
              {text(c.name, c.slug)}
            </button>
          ))}
        </div>

        {/* What the newest verification says, rendered by the METHOD
            that produced it. The three shapes are mutually exclusive
            and each has its own renderer — nothing is forced through
            the field-comparison parser any more. */}
        <div className="mcc-section">
          <h4>
            {parsedNewest?.kind === 'gmc'
              ? 'Merchant Center status'
              : 'Master record vs. surface'}
            {newestVerification?.method && (
              <span className="mcc-method mono"> · {text(newestVerification.method)}</span>
            )}
          </h4>

          {verificationsLoading && <div className="mcc-empty">Loading verification history…</div>}

          {!verificationsLoading && !parsedNewest && (
            <div className="mcc-empty">
              No verification run has been recorded for this listing on this channel, so there is
              nothing to compare. The badge stays ○.
            </div>
          )}

          {parsedNewest?.kind === 'gmc' && (
            <GmcDiagnosticsRecord parsed={parsedNewest} record={newestVerification} />
          )}

          {parsedNewest?.kind === 'unparsed' && (
            <UnparsedRecord parsed={parsedNewest} record={newestVerification} />
          )}

          {parsedNewest?.kind === 'findings' && (
            parsedNewest.findings.length > 0
              ? <FindingsTable findings={parsedNewest.findings} />
              : <div className="mcc-empty">Newest verification recorded no drift.</div>
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
                    <strong>{text(p.status, 'unknown status')}</strong>
                    {p.spec_version && <span className="mono"> · {text(p.spec_version)}</span>}
                    {p.error && <div className="detail">{text(p.error)}</div>}
                    {p.validation && p.validation.ok === false && Array.isArray(p.validation.errors) && p.validation.errors.length > 0 && (
                      <div className="detail">Validation: {p.validation.errors.map((e) => text(e)).join('; ')}</div>
                    )}
                    {p.external_ref && <div className="detail mono">{text(p.external_ref)}</div>}
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
            {(verifications || []).map((v, i) => {
              const parsed = parseVerification(v)
              const when = v?.created_at
              return (
                // `id` is not guaranteed; the index is the fallback.
                <li key={v?.id ?? i}>
                  {/* created_at shipped with the 2026-08-24 verification
                      work. Older deployments have none, so the method
                      still stands in when there is no timestamp. */}
                  <span className="when mono" title={absoluteTime(when) || ''}>
                    {relativeTime(when) || text(v?.method)}
                  </span>
                  <span className="what">
                    <strong>{text(v?.outcome ?? v?.phase, 'unknown outcome')}</strong>
                    <span className="mcc-method mono"> · {text(v?.method)}</span>
                    {v?.gtin && <span className="mono"> · {text(v.gtin)}</span>}

                    <div className="detail">
                      {parsed.kind === 'gmc'
                        ? `${parsed.approved ? 'Approved' : 'Not approved'}`
                          + (parsed.issues.length
                              ? ` · ${parsed.issues.length} issue${parsed.issues.length === 1 ? '' : 's'}`
                              : ' · no itemised issues')
                          + (parsed.httpStatus != null ? ` · HTTP ${parsed.httpStatus}` : '')
                        : parsed.kind === 'findings'
                          ? (parsed.findings.length > 0
                              ? `${parsed.findings.length} finding${parsed.findings.length === 1 ? '' : 's'}`
                              : VERIFICATION_LABEL.verified)
                          : `Unreadable — ${parsed.reason}`}
                    </div>

                    {parsed.kind === 'gmc' && parsed.issues.length > 0 && (
                      <ul className="mcc-gmc-issues compact">
                        {parsed.issues.map((issue, n) => (
                          <li key={`${issue.code}-${n}`} className={`sev-${issue.severity}`}>
                            <span className={`mcc-dot ${GMC_SEVERITY_CLASS[issue.severity] || 'hold'}`} />
                            <span className="mcc-gmc-code mono">{text(issue.code, 'unnamed issue')}</span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {v?.observed && <ArtifactBlock label="Observed payload" value={v.observed} />}
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
                  : `Validation failed: ${
                      (Array.isArray(cell.validation.errors) ? cell.validation.errors : [])
                        .map((e) => text(e)).join('; ') || 'no detail given'
                    }`}
              </span>
            </li>
          )}

          {/* Expressiveness flags are the richest real signal this API
              gives: which fields a protocol could not carry, and why. */}
          {(Array.isArray(cell.expressiveness) ? cell.expressiveness : []).map((flag, i) => (
            <li key={`${text(flag?.field)}-${i}`}>
              <span className={`mcc-tick ${SEVERITY_TICK[flag?.severity] || 'warn'}`}>
                {flag?.severity === 'dropped' ? '✕' : '!'}
              </span>
              <span>
                <strong>{text(flag?.field)}</strong> — {text(flag?.severity, 'unspecified')}
                <br />
                {text(flag?.note, 'No detail given.')}
              </span>
            </li>
          ))}

          {!cell.validation && (Array.isArray(cell.expressiveness) ? cell.expressiveness : []).length === 0 && (
            <li className="mcc-empty">No compiler output recorded for this channel.</li>
          )}
        </ul>

        <div className="meta">
          <span>Depth: <span className="mono">{text(channel.depth_label)}</span></span>
          {channel.spec_version && <span>Spec: <span className="mono">{text(channel.spec_version)}</span></span>}
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
                  ? <a className="mono" href={deepLink} target="_blank" rel="noreferrer">{text(cell.externalRef)}</a>
                  : <span className="mono">{text(cell.externalRef)}</span>)
              : <span className="mono">—</span>}
          </span>
          {row.catalogProductId != null && (
            <span>catalog_product_id: <span className="mono">{text(row.catalogProductId)}</span></span>
          )}
          <span>listing_id: <span className="mono">{text(row.listingId)}</span></span>
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
          {/* POST /api/truesync/listings/{id}/verify shipped upstream on
              2026-08-24 ("Fetches this listing's live PDP and records
              what it served"). Still disabled because this app has no
              proxy route for it yet — but the tooltip says that, rather
              than claiming the endpoint does not exist. */}
          <button
            className="mcc-btn"
            disabled
            title={'Not wired up yet — POST /api/truesync/listings/{id}/verify exists upstream '
              + 'as of 2026-08-24, but this page has no proxy route for it yet'}
          >
            Verify now
          </button>
        </div>
      </div>
    </div>
  )
}
