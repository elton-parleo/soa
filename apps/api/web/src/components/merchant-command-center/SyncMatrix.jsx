import React from 'react'
import { relativeTime, absoluteTime } from './truesyncDerive.js'
import {
  PUBLISH_STATE, PUBLISH_STATE_LABEL, ACCEPTANCE, ACCEPTANCE_LABEL, ACCEPTANCE_TONE,
  STALE_NOTE,
} from './verificationModel.js'

/**
 * Publish state -> the mock's segment vocabulary.
 *
 * Note what is NOT here: drift, acceptance and readability no longer
 * colour this segment. The segment says what WE did; the markers beside
 * it say what was found. Merging them is what let a Merchant Center
 * "pending review" paint a cell as though the catalog were wrong.
 */
const SEG_BY_PUBLISH_STATE = {
  [PUBLISH_STATE.PUBLISHED]: 's-sync',
  [PUBLISH_STATE.FAILED]: 's-fail',
  [PUBLISH_STATE.COMPILED_NOT_PUBLISHED]: 's-pending',
  [PUBLISH_STATE.NEVER]: 's-hold',
}

// The word that qualifies a cell's timestamp. Empty for 'published': a
// time under a green segment already means "published then".
const STATE_WORD = {
  [PUBLISH_STATE.PUBLISHED]: '',
  [PUBLISH_STATE.FAILED]: 'failed',
  [PUBLISH_STATE.COMPILED_NOT_PUBLISHED]: 'compiled',
}

// Compact acceptance markers. Amber for pending, red only for a genuine
// disapproval — see docs/verification-semantics.md.
const ACCEPTANCE_GLYPH = {
  [ACCEPTANCE.APPROVED]: '◉',
  [ACCEPTANCE.PENDING]: '◐',
  [ACCEPTANCE.DISAPPROVED]: '◼',
  [ACCEPTANCE.NOT_FOUND]: '⌀',
  [ACCEPTANCE.UNAVAILABLE]: '⌀',
}

function Cell({ cell, channel }) {
  const when = relativeTime(cell.publishedAt || cell.compiledAt)
  const acceptanceGlyph = ACCEPTANCE_GLYPH[cell.acceptance]

  const title = [
    `${channel.name}: ${PUBLISH_STATE_LABEL[cell.publishState]}`,
    cell.publishReason ? `Reason: ${cell.publishReason}` : null,
    (cell.publishedAt || cell.compiledAt) ? absoluteTime(cell.publishedAt || cell.compiledAt) : null,
    '',
    `Drift: ${cell.badge.label}${cell.badge.count ? ` (${cell.badge.count})` : ''}`,
    acceptanceGlyph
      ? `Acceptance: ${ACCEPTANCE_LABEL[cell.acceptance]}${cell.issueCount ? ` — ${cell.issueCount} issue${cell.issueCount === 1 ? '' : 's'}` : ''}`
      : null,
    cell.unreadableCount > 0
      ? `${cell.unreadableCount} record${cell.unreadableCount === 1 ? '' : 's'} this page could not read`
      : null,
    cell.staleCount > 0 ? `${cell.staleCount} stale (${STALE_NOTE})` : null,
    cell.muted ? `Depth: ${channel.depth_label}` : null,
  ].filter((line) => line !== null).join('\n')

  return (
    <td className={`cell mcc-cell${cell.muted ? ' muted' : ''}`} title={title}>
      <span className="mcc-cell-stack">
        <span className="mcc-cell-row">
          <i className={`mcc-seg ${SEG_BY_PUBLISH_STATE[cell.publishState] || 's-hold'}`} aria-hidden="true" />

          {/* Dimension 2 — the primary badge, drift and only drift. */}
          <span className={`mcc-verify ${cell.badge.kind}`} aria-label={`Drift: ${cell.badge.label}`}>
            {cell.badge.glyph}
            {cell.badge.count > 0 && <span> {cell.badge.count}</span>}
          </span>

          {/* Dimension 3 — their opinion, never merged into the badge. */}
          {acceptanceGlyph && (
            <span
              className={`mcc-accept tone-${ACCEPTANCE_TONE[cell.acceptance]}`}
              aria-label={`Acceptance: ${ACCEPTANCE_LABEL[cell.acceptance]}`}
            >
              {acceptanceGlyph}
              {cell.issueCount > 0 && <span> {cell.issueCount}</span>}
            </span>
          )}

          {/* Dimension 4 — our own gap. */}
          {cell.unreadableCount > 0 && (
            <span className="mcc-verify unreadable" aria-label="Unreadable verification record">?</span>
          )}
        </span>

        <span className="mcc-cell-when">
          {cell.publishState === PUBLISH_STATE.NEVER
            ? 'never published'
            : `${STATE_WORD[cell.publishState] || ''}${when ? ` ${when}` : ''}`.trim() || '—'}
        </span>

        {/* Freshness, surfaced in the cell so a greyed drawer is never a
            surprise: these records verified a superseded artifact. */}
        {cell.staleCount > 0 && cell.badge.kind === 'unknown' && (
          <span className="mcc-stale-note">{cell.staleCount} stale — re-verify</span>
        )}

        {cell.muted && <span className="mcc-stub-label">{channel.depth_label}</span>}
      </span>
    </td>
  )
}

export default function SyncMatrix({
  rows, channels, channelState, cellFor, selectedListingId, onSelectRow,
}) {
  return (
    <div className="mcc-panel">
      <div className="mcc-panel-head">
        <h2>Syndication matrix</h2>
        <span className="hint">
          Master record vs. every agent-readable surface. Select a row to inspect.
        </span>
        <div className="mcc-spacer" />
        <div className="mcc-legend">
          <span><i className="mcc-seg s-sync" />Published</span>
          <span><i className="mcc-seg s-pending" />Compiled</span>
          <span><i className="mcc-seg s-hold" />Not published</span>
          <span><span className="mcc-verify clean">✓</span>No drift</span>
          <span><span className="mcc-verify drift">⚠</span>Drift</span>
          <span><span className="mcc-verify unknown">○</span>Unverified</span>
          <span><span className="mcc-accept tone-drift">◐</span>Pending review</span>
          <span><span className="mcc-accept tone-fail">◼</span>Not approved</span>
          <span><span className="mcc-verify unreadable">?</span>Unreadable</span>
        </div>
      </div>

      <div className="mcc-matrix-scroll">
        <table className="mcc-matrix">
          <thead>
            <tr>
              <th style={{ width: '26%' }}>Product</th>
              <th>Variants</th>
              {channels.map((channel) => {
                const muted = channelState[channel.slug]?.muted
                return (
                  <th
                    key={channel.slug}
                    className={`surface${muted ? ' muted' : ''}`}
                    title={`${channel.depth_label}${
                      channel.spec_version ? `\nspec: ${channel.spec_version}` : ''
                    }`}
                  >
                    {channel.name}
                    {channel.spec_version && (
                      <span className="spec mono">{channel.spec_version}</span>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.listingId}
                className={row.listingId === selectedListingId ? 'selected' : undefined}
                onClick={() => onSelectRow(row.listingId)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSelectRow(row.listingId)
                  }
                }}
                tabIndex={0}
                role="button"
                aria-expanded={row.listingId === selectedListingId}
              >
                <td>
                  <div className="mcc-prod">
                    {row.image
                      ? <img className="mcc-thumb" src={row.image} alt="" loading="lazy" />
                      : <span className="mcc-thumb-fallback" aria-hidden="true" />}
                    <div>
                      <div className="name">{row.name}</div>
                      {row.gtin && (
                        <div className="gtin">
                          <span className="code mono">{row.gtin}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </td>
                <td className="mcc-variant">
                  {row.variantCount} {row.variantCount === 1 ? 'variant' : 'variants'}
                  <br />
                  <span className="gtin-count">{row.gtinCount} with GTIN</span>
                </td>
                {channels.map((channel) => {
                  const cell = cellFor(row, channel)
                  return (
                    <Cell
                      key={channel.slug}
                      cell={{ ...cell, muted: channelState[channel.slug]?.muted }}
                      channel={channel}
                    />
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mcc-matrix-foot">
        The bar is what we published. The badge beside it is drift — our own
        comparison against the master record — and is <em>unknown</em> (○) until a
        verification run newer than the latest publish exists. A channel's own
        acceptance verdict and any records this page could not read are shown
        separately and never counted as drift.
      </div>
    </div>
  )
}
