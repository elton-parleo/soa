import React, { useEffect, useRef, useState } from 'react'
import { relativeTime } from './truesyncDerive.js'
import { KIND_LABEL, HOSTING_LABEL } from '../../customersApi.js'

/**
 * The customer switcher (Step 1C): the generalization of the old
 * live/prospect switcher, in its slot, not a second control beside it.
 *
 * One menu, three levels:
 *   customer (an org)          — every org this login may select
 *     merchant                 — name, kind, hosting; selecting one scopes
 *                                every read and write on the page
 *     read-only prospects      — the selected customer's, a MODE within it
 *                                exactly as before: nothing publishes
 *
 * An operator sees every customer and a "New customer" footer; anyone else
 * sees their own one. A customer whose TrueSync read failed is still
 * listed with the reason, never silently dropped.
 */
export default function CustomerSwitcher({
  customers, isOperator, selection, prospects, onSelect, onNewCustomer,
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const org = customers.find((c) => c.org_id === selection?.orgId) || null
  const merchant = org?.merchants.find((m) => m.slug === selection?.merchantSlug) || null
  const prospect = (prospects || []).find((p) => p.slug === selection?.prospectSlug) || null

  function choose(next) {
    onSelect(next)
    setOpen(false)
  }

  return (
    <div className="mcc-customer" ref={rootRef}>
      <button
        type="button"
        className="mcc-customer-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Customer"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="mcc-customer-org">{org ? org.name : 'Choose a customer'}</span>
        {merchant && (
          <>
            <span className="mcc-customer-sep" aria-hidden="true">/</span>
            <span className="mcc-customer-merchant">{prospect ? prospect.prospect || prospect.slug : merchant.name}</span>
            <span className={`tag ${prospect ? 'prospect' : 'live'}`}>
              {prospect ? 'Read-only' : HOSTING_LABEL[merchant.hosting] || merchant.hosting}
            </span>
          </>
        )}
        <span className="mcc-customer-caret" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="mcc-customer-menu" role="menu" aria-label="Customers">
          {customers.length === 0 && (
            <div className="mcc-customer-empty">No customer accounts are linked to your login.</div>
          )}

          {customers.map((c) => (
            <div key={c.org_id} className="mcc-customer-group" role="group" aria-label={c.name}>
              <div className="mcc-customer-group-head">
                <span>{c.name}</span>
                <span className="mono">{c.tenant_slug}</span>
              </div>
              {c.error && <div className="mcc-customer-error">{c.error}</div>}
              {!c.error && c.merchants.length === 0 && (
                <div className="mcc-customer-empty">No customers in this account yet.</div>
              )}
              {c.merchants.map((m) => {
                const active = c.org_id === selection?.orgId && m.slug === selection?.merchantSlug
                  && !selection?.prospectSlug
                return (
                  <button
                    key={m.slug}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    className={`mcc-customer-item${active ? ' active' : ''}`}
                    onClick={() => choose({ orgId: c.org_id, merchantSlug: m.slug, prospectSlug: null })}
                  >
                    <span className="name">{m.name}</span>
                    {m.domain && <span className="domain mono">{m.domain}</span>}
                    <span className="axes">
                      <span className={`axis kind-${m.kind}`}>{KIND_LABEL[m.kind] || m.kind}</span>
                      <span className={`axis hosting-${m.hosting}`}>{HOSTING_LABEL[m.hosting] || m.hosting}</span>
                      {!m.has_record && <span className="axis norecord">no record yet</span>}
                    </span>
                  </button>
                )
              })}

              {/* Prospects are a mode within the SELECTED customer. */}
              {c.org_id === selection?.orgId && (prospects || []).length > 0 && (
                <div className="mcc-customer-prospects" role="group" aria-label="Read-only prospects">
                  <div className="mcc-customer-subhead">Read-only prospects</div>
                  {prospects.map((p) => {
                    const active = selection?.prospectSlug === p.slug
                    return (
                      <button
                        key={p.slug}
                        type="button"
                        role="menuitemradio"
                        aria-checked={active}
                        className={`mcc-customer-item prospect${active ? ' active' : ''}`}
                        onClick={() => choose({ ...selection, prospectSlug: p.slug })}
                      >
                        <span className="name">{p.prospect || p.slug}</span>
                        <span className="mcc-source-counts">
                          {p.products_observed}/{p.products_configured} products
                          {p.last_observed_at && ` · ${relativeTime(p.last_observed_at)}`}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ))}

          {isOperator && (
            <div className="mcc-customer-foot">
              <button
                type="button"
                className="mcc-btn"
                onClick={() => { setOpen(false); onNewCustomer() }}
              >
                + New customer
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
