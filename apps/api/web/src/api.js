/**
 * API client for the SoA Platform backend.
 * BASE is empty so requests go to the same origin in production.
 * Vite dev server proxies /api → localhost:8000.
 *
 * Every request includes the Supabase JWT as a Bearer token.
 * 401 responses trigger automatic sign-out and page reload.
 */
import { supabase } from './supabase.js'

async function request(method, path, body) {
  // Get current session token
  const { data: { session } } = await supabase.auth.getSession()
  const token = session?.access_token

  const opts = {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }
  const res = await fetch(path, opts)
  if (!res.ok) {
    // If 401, session may have expired — sign out and reload
    if (res.status === 401) {
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

  // Entities
  getEntities: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v != null)
      )
    ).toString()
    return get(`/api/entities${qs ? '?' + qs : ''}`)
  },

  createEntity: (data) =>
    post('/api/entities', data),

  updateEntity: (id, data) =>
    post(`/api/entities/${id}`, data),

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

  getMetrics: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/metrics`),

  getCycleEntities: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/entities`),

  getPositions: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/positions`),
}
