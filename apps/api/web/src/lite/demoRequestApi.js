/**
 * Submission backend for RequestFormModal (via useDemoRequestModal.js)
 * — Formspree, not a backend route of ours (no public demo-request API,
 * no soa_demo_requests table; leads live in Formspree). FormData, not
 * JSON: Formspree's REST API expects a form submission, and requires
 * no Content-Type header of our own — the browser sets the correct
 * multipart boundary for a FormData body automatically.
 *
 * `_subject` (per-CTA, from demoRequestCtas.js) makes the notification
 * email's subject line triageable at a glance. `_gotcha` is Formspree's
 * own server-side honeypot, always sent empty — a second, independent
 * layer behind RequestFormModal's own client-side honeypot/timing
 * check (which prevents the request from ever reaching here at all;
 * this one catches anything that gets past that).
 */
import { FORMSPREE_DEMO_ENDPOINT } from './publicUrls.js'

export async function submitDemoRequest(payload) {
  const formData = new FormData()
  formData.set('name', payload.name)
  formData.set('email', payload.email)
  formData.set('company', payload.company)
  formData.set('message', payload.message)
  if (payload.source) formData.set('source', payload.source)
  if (payload.page_url) formData.set('page_url', payload.page_url)
  if (payload.brand_name) formData.set('brand_name', payload.brand_name)
  if (payload.report_token) formData.set('report_token', payload.report_token)
  formData.set('_subject', payload.subject || 'Demo request')
  formData.set('_gotcha', '')

  let res
  try {
    res = await fetch(FORMSPREE_DEMO_ENDPOINT, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: formData,
    })
  } catch (err) {
    return { ok: false, status: 0, body: null, networkError: true }
  }

  let body = null
  try {
    body = await res.json()
  } catch (_) {}

  return { ok: res.ok, status: res.status, body }
}
