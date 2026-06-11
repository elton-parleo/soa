/**
 * API client for the SoA Platform backend.
 * BASE is empty so requests go to the same origin in production.
 * Vite dev server proxies /api → localhost:8000.
 *
 * Token management: the auth context calls setApiToken() synchronously
 * inside onAuthStateChange so _accessToken is always current before any
 * React render triggered by a session change fires API calls. This avoids
 * the async session-lookup race condition that caused 401s after OAuth.
 */
import { supabase } from './supabase.js'

// Module-level token store.
// Updated by setApiToken() which is called from the auth provider whenever
// the session changes. Avoids async session-lookup on every request,
// which races with OAuth redirect session initialisation.
let _accessToken = null

export function setApiToken(token) {
  _accessToken = token
}

async function request(method, path, body) {
  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(_accessToken
        ? { 'Authorization': `Bearer ${_accessToken}` }
        : {}
      ),
    },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(path, opts)

  if (!res.ok) {
    if (res.status === 401) {
      // Token is invalid or expired.
      // Sign out and reload to return to login page.
      // The auth provider clears the token via onAuthStateChange.
      await supabase.auth.signOut()
      window.location.reload()
      return
    }
    let detail = `${method} ${path} → ${res.status}`
    try {
      const err = await res.json()
      if (err.detail) detail = err.detail
    } catch (_) {}
    throw new Error(detail)
  }

  return res.json()
}

const get  = (path)       => request('GET',  path)
const post = (path, body) => request('POST', path, body)

export const api = {
  // Studies
  getStudies: () =>
    get('/api/studies'),

  getStudyQueries: (studyType) =>
    get(`/api/studies/${studyType}/queries`),

  createQuery: (studyType, data) =>
    post(`/api/studies/${studyType}/queries`, data),

  // Entities
  getEntities: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v != null && v !== '')
      )
    ).toString()
    return get(`/api/entities${qs ? '?' + qs : ''}`)
  },

  createEntity: (data) =>
    post('/api/entities', data),

  updateEntity: (id, data) =>
    request('POST', `/api/entities/${id}`, data),

  deleteEntity: (id) =>
    request('DELETE', `/api/entities/${id}`),

  // Cycles
  checkCycleCode: (code) =>
    get(`/api/cycles/check?code=${encodeURIComponent(code)}`),

  createCycle: (data) =>
    post('/api/cycles', data),

  getCycles: () =>
    get('/api/cycles'),

  getCycle: (code) =>
    get(`/api/cycles/${code}`),

  resumeCycle: (cycleCode) =>
    post(`/api/cycles/${cycleCode}/resume`, {}),

  // Metrics
  getMetrics: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/metrics`),

  getCycleEntities: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/entities`),

  getPositions: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/positions`),
}
