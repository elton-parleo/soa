import React, { useEffect, useState } from 'react'
import {
  publicationHistoryForCell, relativeTime, absoluteTime,
  gmcExternalRefs, gmcAccountId, gmcOfferLink,
} from './truesyncDerive.js'
import {
  PUBLISH_STATE, PUBLISH_STATE_LABEL, ACCEPTANCE, ACCEPTANCE_LABEL, ACCEPTANCE_TONE,
  STALE_NOTE,
} from './verificationModel.js'

/**
 * Renders any API-supplied value as text, or `fallback` when there is
 * nothing to show. Every scalar in this panel goes through it — React
 * throws "Objects are not valid as a React child" the moment a field
 * the API has always sent as a string arrives as an object, and that
 * throw takes the whole panel down.
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

function ArtifactBlock({ label, value }) {
  if (value == null) return null
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

const EXPRESSIVENESS_TICK = { dropped: 'bad', approximate: 'warn', lossy: 'warn' }

// ─── Dimension 2 — drift ─────────────────────────────────────────────

function DriftSection({ cell }) {
  const probe = cell.driftRecord

  return (
    <div className="mcc-section">
      <h4>
        Drift — master record vs. surface
        {probe?.method && <span className="mcc-method mono"> · {text(probe.method)}</span>}
      </h4>

      {!probe && (
        <div className="mcc-empty">
          {cell.staleCount > 0
            ? `No verification run newer than the latest publish. ${cell.staleCount} older record${cell.staleCount === 1 ? '' : 's'} ${cell.staleCount === 1 ? 'pre-dates' : 'pre-date'} it, so drift stays unknown until a fresh run.`
            : 'No verification run has been recorded for this listing on this channel, so drift is unknown. The badge stays ○.'}
        </div>
      )}

      {probe && (
        <>
          <div className="mcc-probe">
            <span className={`mcc-badge ${probe.integrity === false ? 'drift' : 'sync'}`}>
              {probe.integrity === false ? 'Structured data differs' : 'Structured data matches'}
            </span>
            {probe.outcome && <span className="mcc-probe-meta mono">outcome: {text(probe.outcome)}</span>}
            {probe.bytesIdentical === false && (
              <span
                className="mcc-probe-meta"
                title="The served bytes differ (ordering, whitespace) while the structured data matches — the normal state, not a problem."
              >
                bytes differ
              </span>
            )}
            {probe.url && (
              <a className="mcc-probe-meta mono" href={probe.url} target="_blank" rel="noreferrer">
                fetched page ↗
              </a>
            )}
          </div>

          {cell.drift === 0 ? (
            <div className="mcc-empty">Newest verification recorded no drift.</div>
          ) : (
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
                {probe.findings.map((f, i) => (
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
          )}
        </>
      )}
    </div>
  )
}

// ─── Dimension 3 — surface acceptance ────────────────────────────────

function AcceptanceSection({ cell, accountId }) {
  if (!cell.hasAcceptanceAuthority) return null

  const record = cell.acceptanceRecord
  const offerId = record?.record?.observed?.offerId
  const offerLink = gmcOfferLink(accountId, offerId)

  return (
    <div className="mcc-section">
      <h4>
        Surface acceptance
        {record?.method && <span className="mcc-method mono"> · {text(record.method)}</span>}
      </h4>

      {!record && (
        <div className="mcc-empty">
          {cell.staleCount > 0
            ? `No acceptance record newer than the latest publish — ${STALE_NOTE}.`
            : 'The channel has not reported an acceptance state for this item.'}
        </div>
      )}

      {record && (
        <>
          <div className="mcc-gmc-head">
            <span className={`mcc-badge ${ACCEPTANCE_TONE[cell.acceptance]}`}>
              {ACCEPTANCE_LABEL[cell.acceptance]}
            </span>
            {record.httpStatus != null && (
              <span className="mcc-gmc-status mono">HTTP {record.httpStatus}</span>
            )}
            {record.createdAt && (
              <span className="mcc-gmc-when" title={absoluteTime(record.createdAt) || ''}>
                {relativeTime(record.createdAt) || ''}
              </span>
            )}
            {offerId && (
              offerLink
                ? <a className="mcc-gmc-offer mono" href={offerLink} target="_blank" rel="noreferrer">
                    {text(offerId)} ↗
                  </a>
                : <span className="mcc-gmc-offer mono">{text(offerId)}</span>
            )}
          </div>

          {cell.acceptance === ACCEPTANCE.UNAVAILABLE && (
            <p className="mcc-empty">
              No acceptance opinion could be obtained: {text(record.reason, 'the publish never landed')}.
              Nothing is counted for this cell.
            </p>
          )}

          {record.issues.length === 0 && cell.acceptance !== ACCEPTANCE.UNAVAILABLE && (
            <p className="mcc-empty">
              {cell.acceptance === ACCEPTANCE.APPROVED
                ? 'No outstanding item issues.'
                : cell.acceptance === ACCEPTANCE.NOT_FOUND
                  ? 'The item was not found in the account — it has not been accepted into the feed yet.'
                  : 'Not approved, and the channel gave no reason.'}
            </p>
          )}

          {record.issues.length > 0 && (
            <ul className="mcc-gmc-issues">
              {record.issues.map((issue, i) => (
                <li key={`${issue.code}-${i}`} className={`sev-${issue.tone}`}>
                  <span className={`mcc-dot ${issue.tone === 'pending' ? 'drift' : 'fail'}`} />
                  <span className="mcc-gmc-issue-body">
                    <span className="mcc-gmc-code mono">{text(issue.code, 'unnamed issue')}</span>
                    <span className={`mcc-tick ${issue.tone === 'pending' ? 'warn' : 'bad'}`}>
                      {issue.tone === 'pending' ? 'pending review' : 'action needed'}
                    </span>
                    {issue.description && <div className="detail">{text(issue.description)}</div>}
                    {issue.detail && <div className="detail">{text(issue.detail)}</div>}
                    {/* Stated openly where we override the channel: a
                        lifecycle code reported as DISAPPROVED is still
                        just an item awaiting review. */}
                    {issue.lifecycle && issue.reportedSeverity
                      && issue.reportedSeverity.toUpperCase() !== 'PENDING' && (
                      <div className="detail mcc-override">
                        Reported by the channel as{' '}
                        <span className="mono">{text(issue.reportedSeverity)}</span> — shown as pending
                        because this is a lifecycle code, not a policy rejection.
                      </div>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

// ─── Dimension 4 — observability ─────────────────────────────────────

function UnreadableSection({ cell }) {
  if (cell.unreadableCount === 0) return null

  return (
    <div className="mcc-section">
      <h4>Records this page could not read</h4>
      {cell.unreadableRecords.map((record, i) => (
        <div className="mcc-unparsed" role="status" key={record.record?.id ?? i}>
          <strong>
            Couldn’t parse verification record (method: {text(record.method, 'none given')})
          </strong>
          <div className="detail">{text(record.reason)}</div>
          <div className="detail">
            Not counted as drift and not counted as a surface issue — this is a gap in this
            page, not a finding about the catalog.
          </div>
          {record.record?.drift != null && (
            <ArtifactBlock label="Show the raw drift payload" value={record.record.drift} />
          )}
        </div>
      ))}
    </div>
  )
}

// ─── Stale records ───────────────────────────────────────────────────

function StaleSection({ cell }) {
  if (cell.staleCount === 0) return null

  return (
    <div className="mcc-section mcc-stale">
      <h4>Superseded verification records ({cell.staleCount})</h4>
      <p className="mcc-empty">
        These ran before the latest publish at{' '}
        <span className="mono">{absoluteTime(cell.publishedAt) || '—'}</span>, so they describe an
        artifact that has since been replaced. They count towards nothing.
      </p>
      <ul className="mcc-timeline">
        {cell.staleRecords.map((record, i) => (
          <li key={record.record?.id ?? i}>
            <span className="when mono" title={absoluteTime(record.createdAt) || ''}>
              {relativeTime(record.createdAt) || text(record.method)}
            </span>
            <span className="what">
              <strong>{text(record.record?.outcome ?? record.kind, 'unknown outcome')}</strong>
              <span className="mcc-method mono"> · {text(record.method)}</span>
              <div className="detail">{STALE_NOTE}</div>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ─── The drawer ──────────────────────────────────────────────────────

/**
 * The drift inspector — per-channel detail for one listing.
 *
 * Structured as the model is: one section per dimension, in the order
 * they answer questions. Nothing here counts anything; every number
 * comes from `aggregateCell` (see docs/verification-semantics.md).
 */
export default function ListingDrawer({
  row, channels, channelState, cellFor, publications,
  onClose, onPublish, publishPending, onVerify, verifyPending,
}) {
  const [channelSlug, setChannelSlug] = useState(channels[0]?.slug)

  useEffect(() => { setChannelSlug(channels[0]?.slug) }, [row.listingId, channels])

  const channel = channels.find((c) => c.slug === channelSlug)

  if (!channel) {
    return (
      <div className="mcc-drawer-error mcc-panel" role="alert">
        <div className="mcc-drawer-head">
          <h3>{text(row?.name, 'This listing')} — no channel to show</h3>
          <button className="mcc-btn mcc-drawer-close" onClick={onClose}>Close</button>
        </div>
        <div className="mcc-section">
          <p className="mcc-empty">
            TrueSync returned no channels, so there is no surface to inspect this listing against.
          </p>
        </div>
      </div>
    )
  }

  const cell = cellFor(row, channel)
  const history = publicationHistoryForCell(publications, row.listingId, channel.slug)
  const current = history[0] || null
  const gmcRefs = channel.slug === 'merchant_center' ? gmcExternalRefs(cell.externalRef) : []
  const gmcAccount = channel.slug === 'merchant_center' ? gmcAccountId(cell.externalRef) : null

  // The headline badge is the publish state plus, where they exist, the
  // other dimensions as separate chips. Never one merged verdict.
  const publishTone = cell.publishState === PUBLISH_STATE.PUBLISHED ? 'sync'
    : cell.publishState === PUBLISH_STATE.FAILED ? 'fail'
    : 'hold'

  return (
    <div className="mcc-drawer">
      <div className="mcc-panel">
        <div className="mcc-drawer-head">
          <h3>{text(row.name, `Listing ${text(row.listingId)}`)} — {text(channel.name)}</h3>
          <span className={`mcc-badge ${publishTone}`}>{PUBLISH_STATE_LABEL[cell.publishState]}</span>
          <span className={`mcc-badge ${cell.badge.kind === 'drift' ? 'drift' : cell.badge.kind === 'clean' ? 'sync' : 'hold'}`}>
            Drift: {cell.drift == null ? 'unknown' : cell.drift}
          </span>
          {cell.hasAcceptanceAuthority && cell.acceptance !== ACCEPTANCE.UNKNOWN && (
            <span className={`mcc-badge ${ACCEPTANCE_TONE[cell.acceptance]}`}>
              {ACCEPTANCE_LABEL[cell.acceptance]}
              {cell.issueCount > 0 && ` · ${cell.issueCount}`}
            </span>
          )}
          {cell.unreadableCount > 0 && (
            <span className="mcc-badge hold">{cell.unreadableCount} unreadable</span>
          )}
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

        <DriftSection cell={cell} />
        <AcceptanceSection cell={cell} accountId={gmcAccount} />
        <UnreadableSection cell={cell} />
        <StaleSection cell={cell} />

        <div className="mcc-section">
          <h4>Published artifact</h4>
          {current?.payload != null
            ? <ArtifactBlock label="Show compiled payload (JSON)" value={current.payload} />
            : <div className="mcc-empty">Nothing has been compiled for this channel yet.</div>}
        </div>

        <div className="mcc-section">
          <h4>Publish timeline</h4>
          {history.length === 0 && (
            <div className="mcc-empty">No publication events recorded for this channel.</div>
          )}
          <ul className="mcc-timeline">
            {history.map((p) => {
              const at = p.published_at || p.compiled_at
              const dot = p.status === 'published' ? 'sync' : p.status === 'failed' ? 'fail' : 'hold'
              return (
                <li key={p.id ?? `${p.channel_slug}-${at}`}>
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
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>

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

          {cell.expressiveness.map((flag, i) => (
            <li key={`${text(flag?.field)}-${i}`}>
              <span className={`mcc-tick ${EXPRESSIVENESS_TICK[flag?.severity] || 'warn'}`}>
                {flag?.severity === 'dropped' ? '✕' : '!'}
              </span>
              <span>
                <strong>{text(flag?.field)}</strong> — {text(flag?.severity, 'unspecified')}
                <br />
                {text(flag?.note, 'No detail given.')}
              </span>
            </li>
          ))}

          {!cell.validation && cell.expressiveness.length === 0 && (
            <li className="mcc-empty">No compiler output recorded for this channel.</li>
          )}
        </ul>

        <div className="meta">
          <span>Depth: <span className="mono">{text(channel.depth_label)}</span></span>
          {channel.spec_version && <span>Spec: <span className="mono">{text(channel.spec_version)}</span></span>}
          <span>Compiled: <span className="mono">{absoluteTime(cell.compiledAt) || '—'}</span></span>
          <span>Published: <span className="mono">{absoluteTime(cell.publishedAt) || 'never'}</span></span>

          {gmcRefs.length > 0 ? (
            <span>
              {`Merchant Center items (${gmcRefs.length}):`}
              <span className="mcc-reflist">
                {gmcRefs.map((entry) => (
                  <span key={entry.ref}>
                    {entry.url
                      ? <a className="mono" href={entry.url} target="_blank" rel="noreferrer">
                          {text(entry.offerId, entry.ref)} ↗
                        </a>
                      : <span className="mono" title="Not a resource name this page can map to a Merchant Center URL">
                          {text(entry.ref)}
                        </span>}
                  </span>
                ))}
              </span>
            </span>
          ) : (
            <span>external_ref: <span className="mono">{text(cell.externalRef)}</span></span>
          )}

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
          <button
            className="mcc-btn"
            onClick={() => onVerify(row)}
            disabled={verifyPending}
            title="Fetch this listing's live PDP and record what it served"
          >
            {verifyPending ? <><span className="mcc-spinner" /> Verifying…</> : 'Verify now'}
          </button>
        </div>
      </div>
    </div>
  )
}
