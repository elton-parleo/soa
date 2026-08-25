import React, { useState } from 'react'

/**
 * Sync rules — per listing x channel enable/disable.
 *
 * The honest shape of this tab is dictated by what the API offers. As
 * of 2026-08-22 TrueSync exposes:
 *
 *   PUT /api/truesync/sync-rules     write, keyed by catalog_product_id
 *   (no GET equivalent, and no sync-rule field on any read endpoint)
 *
 * So the WRITE is real and wired through the proxy — this is not a
 * stub. What does not exist is any way to READ the current rule. That
 * leaves each toggle in a genuine third state on load: not on, not off,
 * unknown. It renders as a hatched toggle with an "unknown" label and a
 * tooltip saying why, and it only ever shows on/off after a write, from
 * the SyncRuleResponse the server echoed back.
 *
 * The alternative — defaulting every toggle to "on" because a
 * publication row exists — would be inventing state, which is the one
 * thing this page is not allowed to do.
 *
 * That unknown start is also why the first write of a session asks for
 * confirmation. Everywhere else on this page a toggle's position tells
 * you what a click will do; here it cannot, so the first click is the
 * one place an operator can change what publishes to a live surface
 * without having meant to. One confirm per session, not per click —
 * enough to establish that these are real writes, not so much that it
 * becomes something to dismiss on reflex.
 */
export default function SyncRulesTab({
  rows, channels, channelState, ruleState, onToggle, pendingKey,
}) {
  // null when nothing is awaiting confirmation; otherwise the pending
  // write: { row, channel, next }.
  const [pendingConfirm, setPendingConfirm] = useState(null)
  const [confirmedThisSession, setConfirmedThisSession] = useState(false)

  function requestToggle(row, channel, next) {
    if (confirmedThisSession) {
      onToggle(row, channel.slug, next)
      return
    }
    setPendingConfirm({ row, channel, next })
  }

  function confirmPending() {
    const { row, channel, next } = pendingConfirm
    setConfirmedThisSession(true)
    setPendingConfirm(null)
    onToggle(row, channel.slug, next)
  }

  return (
    <>
      <div className="mcc-banner warn" role="status">
        <span>
          <strong>Current rules cannot be read back.</strong>{' '}
          TrueSync has no GET for sync rules and no read endpoint carries them, so every
          toggle starts as <em>unknown</em>. Setting one is a real write
          (<span className="mono">PUT /api/truesync/sync-rules</span>, proxied server-side)
          and the state shown afterwards is the one the API returned.
        </span>
      </div>

      {pendingConfirm && (
        <div className="mcc-confirm" role="alertdialog" aria-modal="false"
             aria-labelledby="mcc-confirm-title">
          <div className="mcc-confirm-body">
            <h3 id="mcc-confirm-title">
              This is a real write — {pendingConfirm.channel.name} will be{' '}
              {pendingConfirm.next ? 'enabled' : 'disabled'} for future publishes
            </h3>
            <p>
              Applies to <strong>{pendingConfirm.row.name}</strong>{' '}
              (<span className="mono">catalog_product_id {pendingConfirm.row.catalogProductId}</span>).
              It changes what TrueSync publishes to a live surface from now on; it does not
              publish or withdraw anything right now.
            </p>
            <p className="mcc-confirm-note">
              Asked once per session — later toggles apply immediately.
            </p>
          </div>
          <div className="mcc-confirm-actions">
            <button className="mcc-btn" onClick={() => setPendingConfirm(null)}>Cancel</button>
            <button className="mcc-btn primary" onClick={confirmPending}>
              {pendingConfirm.next ? 'Enable' : 'Disable'} {pendingConfirm.channel.name}
            </button>
          </div>
        </div>
      )}

      <div className="mcc-panel" style={{ marginTop: 14 }}>
        <div className="mcc-panel-head">
          <h2>Sync rules</h2>
          <span className="hint">What publishes automatically, per product and channel</span>
        </div>

        {rows.map((row) => (
          <div key={row.listingId}>
            <div className="mcc-rule-group-head">
              {row.name}
              <span className="mono" style={{ fontWeight: 400, fontSize: '.78rem', color: 'var(--ink-faint)' }}>
                {row.catalogProductId != null
                  ? `catalog_product_id ${row.catalogProductId}`
                  : 'catalog_product_id unavailable'}
              </span>
            </div>

            <ul className="mcc-rules">
              {channels.map((channel) => {
                const key = `${row.catalogProductId}:${channel.slug}`
                const known = ruleState[key]
                const pending = pendingKey === key
                // No catalog_product_id means the listing's detail fetch
                // failed; the write API is keyed by it, so there is
                // nothing valid to send.
                const disabled = pending || row.catalogProductId == null

                return (
                  <li key={channel.slug}>
                    <div className="desc">
                      {channel.name}
                      <small>{channel.depth_label}</small>
                    </div>

                    <span className={`mcc-rule-state ${known === undefined ? '' : known ? 'on' : 'off'}`}>
                      {pending ? 'saving…' : known === undefined ? 'unknown' : known ? 'on' : 'off'}
                    </span>

                    <button
                      type="button"
                      role="switch"
                      aria-checked={known === undefined ? 'mixed' : String(known)}
                      aria-label={`${channel.name} sync for ${row.name}`}
                      className={`mcc-toggle${known === undefined ? ' unknown' : ''}`}
                      disabled={disabled}
                      title={
                        row.catalogProductId == null
                          ? 'This listing’s canonical record could not be loaded, so its catalog_product_id is unknown'
                          : known === undefined
                            ? 'Current value unknown — TrueSync has no sync-rule read endpoint. Click to set it.'
                            : `Currently ${known ? 'enabled' : 'disabled'} — click to ${known ? 'disable' : 'enable'}`
                      }
                      onClick={() => requestToggle(row, channel, known === undefined ? true : !known)}
                    />
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>
    </>
  )
}
