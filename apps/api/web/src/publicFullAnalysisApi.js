/**
 * API client for the public, unauthenticated Full Analysis share
 * endpoint (/api/public/full-analysis/{token}).
 *
 * Deliberately independent of ./api.js and ./supabase.js — same reason
 * lite/liteApi.js is its own tiny fetch wrapper: a visitor opening a
 * share link has no session, so there's no token to attach and no
 * 401→signOut path to wire up, and this page should never pay the
 * module-load cost of the authed app's Supabase client.
 */
async function request(path) {
  const res = await fetch(path)

  if (!res.ok) {
    let detail = `GET ${path} → ${res.status}`
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

export const publicFullAnalysisApi = {
  getReport: (token) =>
    request(`/api/public/full-analysis/${encodeURIComponent(token)}`),

  // Transcript browsing (2a) — same share token, same rate limit as
  // getReport above.
  getTranscriptIndex: (token, page = 1) =>
    request(`/api/public/full-analysis/${encodeURIComponent(token)}/transcripts?page=${page}`),

  getTranscriptDetail: (token, runId) =>
    request(`/api/public/full-analysis/${encodeURIComponent(token)}/transcripts/${runId}`),
}
