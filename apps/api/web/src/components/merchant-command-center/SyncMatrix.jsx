import React from 'react'
import {
  VERIFICATION_GLYPH, VERIFICATION_LABEL, relativeTime, absoluteTime,
} from './truesyncDerive.js'

// Publish state -> the mock's segment vocabulary (sync / drift /
// pending / hold, plus fail). Drift wins over "published" on the
// segment itself: a row that published and then drifted is not in sync,
// and the mock colours that case amber.
function segClass(cell) {
  if (cell.publishState === 'published') {
    return cell.verification.kind === 'drift' ? 's-drift'
      : cell.verification.kind === 'failed' ? 's-fail'
      : 's-sync'
  }
  if (cell.publishState === 'failed') return 's-fail'
  if (cell.publishState === 'compiled_not_published') return 's-pending'
  return 's-hold'   // never published, or withdrawn
}

// The word that qualifies a cell's timestamp. Empty for 'published':
// a time under a green segment already means "published then".
const STATE_WORD = {
  published: '',
  failed: 'failed',
  compiled_not_published: 'compiled',
  withdrawn: 'withdrawn',
}

function Cell({ cell, channel }) {
  const when = relativeTime(cell.at)
  const glyph = VERIFICATION_GLYPH[cell.verification.kind]

  // The whole cell's tooltip. Built from what the API actually said —
  // publish state, when, the verification badge, and (for a channel
  // that has never published anything) the channel's own depth label,
  // so the muted treatment always explains itself.
  const title = [
    `${channel.name}: ${cell.publishLabel}`,
    cell.at ? absoluteTime(cell.at) : null,
    `${VERIFICATION_LABEL[cell.verification.kind]}${
      cell.verification.findingCount ? ` (${cell.verification.findingCount})` : ''
    }`,
    cell.error ? `Error: ${cell.error}` : null,
    cell.muted ? `Depth: ${channel.depth_label}` : null,
  ].filter(Boolean).join('\n')

  return (
    <td className={`cell mcc-cell${cell.muted ? ' muted' : ''}`} title={title}>
      <span className="mcc-cell-stack">
        <span className="mcc-cell-row">
          <i className={`mcc-seg ${segClass(cell)}`} aria-hidden="true" />
          <span
            className={`mcc-verify ${cell.verification.kind}`}
            aria-label={VERIFICATION_LABEL[cell.verification.kind]}
          >
            {glyph}
            {cell.verification.kind === 'drift' && cell.verification.findingCount > 0 && (
              <span> {cell.verification.findingCount}</span>
            )}
          </span>
        </span>

        {/* Freshness, always qualified by the state it belongs to. A
            bare "1d ago" under a failed cell reads as "published 1d
            ago", which is the opposite of what happened — so only a
            genuinely published cell gets to show a time on its own. */}
        <span className="mcc-cell-when">
          {cell.publishState === 'never'
            ? 'never published'
            : `${STATE_WORD[cell.publishState] || ''}${when ? ` ${when}` : ''}`.trim() || '—'}
        </span>

        {/* The honest stub treatment: a channel with no successful
            publication anywhere carries its depth label in the cell, so
            the column is never silently green or silently blank. */}
        {cell.muted && (
          <span className="mcc-stub-label">{channel.depth_label}</span>
        )}
      </span>
    </td>
  )
}

/**
 * The syndication matrix — rows are the merchant's listings, columns
 * are the channels the API reports, real surfaces first.
 *
 * Selecting a row opens the drift inspector below it (the mock's
 * interaction pattern): the table stays put and the detail renders
 * underneath, rather than an overlay that hides the matrix you are
 * comparing against.
 */
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
          <span><i className="mcc-seg s-sync" />In sync</span>
          <span><i className="mcc-seg s-drift" />Drift</span>
          <span><i className="mcc-seg s-fail" />Failed</span>
          <span><i className="mcc-seg s-pending" />Compiled</span>
          <span><i className="mcc-seg s-hold" />Not published</span>
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
                    // Depth label as the column tooltip, per spec.
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
                  {/* GTIN coverage, stated as a fraction rather than a
                      badge — 0 of 12 is a finding, and rounding it into
                      a tick would hide it. */}
                  <span className="gtin-count">{row.gtinCount} with GTIN</span>
                </td>
                {channels.map((channel) => (
                  <Cell key={channel.slug} cell={cellFor(row, channel)} channel={channel} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mcc-matrix-foot">
        Publish state and freshness come from the publication log; the ○ / ✓ / ⚠ / ✕
        badge comes from verification runs recorded against each surface. A channel
        that has never published anything is shown muted with its depth label.
      </div>
    </div>
  )
}
