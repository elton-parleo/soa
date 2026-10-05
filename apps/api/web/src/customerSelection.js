/**
 * The selected customer: which org (and which of its merchants) every
 * TrueSync read and write on the page is scoped to (Step 1C).
 *
 * Persisted per browser session (sessionStorage), so a reload keeps it and
 * a new sign-in starts fresh. Sent to this app's API as X-Parleo-Customer
 * on every request; the server checks it against the user's rights
 * (app/customer_context.py) and refuses a customer the user may not select
 * — it never trusts this value, it only reads which one the page means.
 *
 * Holds ids, never a token: the token is resolved server-side from the org.
 *
 * Storage can be missing or throw (private windows, blocked site data), so
 * every access is guarded and the page works without it — it just forgets
 * the selection on reload.
 */
export const CUSTOMER_HEADER = 'X-Parleo-Customer'
const STORAGE_KEY = 'parleo.customerSelection'
const EVENT = 'parleo:customer-selection'

let memory = null

function read() {
  try {
    // Storage works: it is the truth, including when it is empty (cleared,
    // signed out). Memory is only the stand-in for storage that does not.
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (_) {
    return memory
  }
}

/** { orgId, merchantSlug, prospectSlug? } or null. */
export function getSelection() {
  const value = read()
  if (!value || typeof value.orgId !== 'number') return null
  return value
}

export function setSelection(selection) {
  memory = selection
  try {
    if (selection) window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(selection))
    else window.sessionStorage.removeItem(STORAGE_KEY)
  } catch (_) { /* memory still holds it for this page */ }
  try {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: selection }))
  } catch (_) {}
}

export function clearSelection() {
  setSelection(null)
}

/** Listen for selection changes; returns the unsubscribe. */
export function onSelectionChange(handler) {
  const listener = (event) => handler(event.detail)
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}

/**
 * The header naming the customer a request is for. `orgId` overrides the
 * stored selection — the Create Study modal reads a brand's catalog under
 * the org that brand belongs to, which need not be the page's selection.
 */
export function customerHeaders(orgId) {
  const id = orgId ?? getSelection()?.orgId
  return typeof id === 'number' ? { [CUSTOMER_HEADER]: String(id) } : {}
}

/**
 * The selection to use given the customers list: the stored one if it
 * still names a listed org and merchant, else the first org's first
 * merchant. A stored selection that no longer resolves (signed in as
 * someone else, customer removed) is replaced, never sent on.
 */
export function resolveSelection(customers, stored = getSelection()) {
  const list = Array.isArray(customers) ? customers : []
  const org = stored && list.find((c) => c.org_id === stored.orgId)
  if (org) {
    const merchant = org.merchants.find((m) => m.slug === stored.merchantSlug)
    return {
      orgId: org.org_id,
      merchantSlug: merchant ? merchant.slug : (org.merchants[0]?.slug ?? null),
      prospectSlug: merchant ? (stored.prospectSlug ?? null) : null,
    }
  }
  const first = list[0]
  return first
    ? { orgId: first.org_id, merchantSlug: first.merchants[0]?.slug ?? null, prospectSlug: null }
    : null
}
