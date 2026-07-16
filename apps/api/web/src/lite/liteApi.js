/**
 * API client for SoA Lite's public endpoints (/api/public/soa-lite/*).
 *
 * Deliberately independent of ../api.js and ../supabase.js: this widget
 * has no session, so there is no token to attach and no 401→signOut
 * path to wire up. Keeping it as its own tiny fetch wrapper means the
 * public widget never imports (or pays the module-load cost of) the
 * authed app's Supabase client.
 */
async function request(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(path, opts)

  if (!res.ok) {
    let detail = `${method} ${path} → ${res.status}`
    try {
      const err = await res.json()
      if (err.detail) detail = err.detail
    } catch (_) {}
    const error = new Error(detail)
    error.status = res.status
    error.retryAfter = res.headers.get('Retry-After')
    throw error
  }

  return res.json()
}

export const liteApi = {
  submit: (data) =>
    request('POST', '/api/public/soa-lite', data),

  getStatus: (token) =>
    request('GET', `/api/public/soa-lite/${encodeURIComponent(token)}/status`),

  getReport: (token) =>
    request('GET', `/api/public/soa-lite/${encodeURIComponent(token)}/report`),

  setEmail: (token, email) =>
    request('PATCH', `/api/public/soa-lite/${encodeURIComponent(token)}/email`, { email }),
}
