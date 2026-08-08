/**
 * API client for POST /api/public/demo-request — deliberately its own
 * tiny fetch wrapper rather than reusing liteApi.js's request(), which
 * collapses a FastAPI 422's structured `detail` array into a single
 * Error string. RequestFormModal needs the per-field errors intact to
 * render them inline, so this returns { ok, status, body } instead of
 * throwing.
 */
export async function submitDemoRequest(payload) {
  let res
  try {
    res = await fetch('/api/public/demo-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
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
