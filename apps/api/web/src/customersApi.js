/**
 * The customers this login may select, and the setup wizard's first write
 * (Step 1C). This app's own API — /api/customers — not TrueSync's, though it
 * reads each customer's merchants from TrueSync server-side with that
 * customer's token. Nothing here ever holds a token.
 */
import { apiAuthHeaders } from './api.js'
import { proxyWrite, TrueSyncError, READ_TIMEOUT_MS } from './truesyncApi.js'

/**
 * { is_operator, customers: [{ org_id, name, tenant_slug, error,
 *   merchants: [{ slug, name, domain, kind, hosting, has_record }] }] }
 */
export async function listCustomers({ signal } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), READ_TIMEOUT_MS)
  const onAbort = () => controller.abort()
  if (signal) signal.addEventListener('abort', onAbort)
  try {
    const res = await fetch('/api/customers', { headers: apiAuthHeaders(), signal: controller.signal })
    if (!res.ok) {
      let detail = `GET /api/customers → ${res.status}`
      try {
        const body = await res.json()
        if (typeof body.detail === 'string') detail = body.detail
      } catch (_) {}
      throw new TrueSyncError(detail, { status: res.status })
    }
    return await res.json()
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', onAbort)
  }
}

/**
 * Wizard step 1: the account (existing org_id, or a new name — the server
 * creates the org and its TrueSync tenant), the customer (merchant) with its
 * kind and hosting, and its retailer list. Returns { org_id, org_name,
 * tenant_slug, created_account, merchant, retailers }.
 *
 * A failure after a NEW account was created carries `orgId` on the error,
 * so the wizard can retry under that account rather than create another.
 */
export async function createCustomer(body) {
  try {
    return await proxyWrite('POST', '/api/customers', { json: body })
  } catch (err) {
    if (typeof err?.details?.org_id === 'number') err.orgId = err.details.org_id
    throw err
  }
}

export const KIND_LABEL = { seller: 'Seller', brand: 'Brand' }
export const HOSTING_LABEL = { parleo: 'Parleo-hosted', external: 'Customer-hosted' }
