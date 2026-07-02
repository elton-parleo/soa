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

  updateQuery: (studyType, queryCode, data) =>
    request('PATCH', `/api/studies/${studyType}/queries/${encodeURIComponent(queryCode)}`, data),

  getQueryConstraints: () =>
    get('/api/studies/constraints'),

  getQueryRows: (studyType) =>
    get(`/api/studies/${studyType}/query-rows`),

  generateStudy: (data) =>
    post('/api/studies/generate', data),

  getGenerationStatus: (studyType) =>
    get(`/api/studies/${studyType}/generation-status`),

  uploadStudyCsv: async (file) => {
    const formData = new FormData()
    formData.append('file', file)

    const opts = {
      method: 'POST',
      headers: {
        // Do NOT set Content-Type — the browser sets the correct
        // multipart boundary automatically
        ...(_accessToken
          ? { 'Authorization': `Bearer ${_accessToken}` }
          : {}),
      },
      body: formData,
    }

    const res = await fetch('/api/studies/upload-csv', opts)

    if (!res.ok) {
      if (res.status === 401) {
        await supabase.auth.signOut()
        window.location.reload()
        return
      }
      let detail = `Upload failed (${res.status})`
      try {
        const err = await res.json()
        if (err.detail) {
          if (typeof err.detail === 'string') {
            detail = err.detail
          } else if (err.detail.errors) {
            detail = err.detail.errors.join('\n')
          }
        }
      } catch (_) {}
      throw new Error(detail)
    }

    return res.json()
  },

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
    request('PUT', `/api/entities/${id}`, data),

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

  // Truecost sweep cycles
  getCycleTruecostSnapshots: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/truecost-snapshots`),

  getScopeTiers: () =>
    get('/api/scope/tiers'),

  // Metrics
  getMetrics: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/metrics`),

  getCycleEntities: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/entities`),

  getPositions: (cycleCode) =>
    get(`/api/cycles/${cycleCode}/positions`),

  getCycleRuns: (cycleCode, filters = {}) => {
    const params = new URLSearchParams(
      Object.fromEntries(
        Object.entries(filters).filter(
          ([, v]) => v !== null && v !== undefined && v !== '' && v !== 'all' && v !== false
        )
      )
    ).toString()
    return get(`/api/cycles/${cycleCode}/runs` + (params ? '?' + params : ''))
  },

  getRunMentions: (cycleCode, runId) =>
    get(`/api/cycles/${cycleCode}/runs/${runId}/mentions`),

  updateRunMentions: (cycleCode, runId, updates) =>
    request('PATCH', `/api/cycles/${cycleCode}/runs/${runId}/mentions`, updates),

  // Scope SKUs — optional SKU-level measurement scope nested under entities
  searchScopeCatalog: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v != null && v !== '')
      )
    ).toString()
    return get(`/api/scope/catalog/search${qs ? '?' + qs : ''}`)
  },

  // Cycle scope — read returns the resolved effective scope
  // { skus, source, is_editable }; write operates on cycle snapshot rows.
  getScopeSkus: (cycleId) =>
    get(`/api/cycles/${cycleId}/scope-skus`),

  addScopeSku: (cycleId, data) =>
    post(`/api/cycles/${cycleId}/scope-skus`, data),

  deleteCycleScopeSku: (cycleId, scopeSkuId) =>
    request('DELETE', `/api/cycles/${cycleId}/scope-skus/${scopeSkuId}`),

  // Entity templates — the brand's living, editable measured-SKU set,
  // independent of any cycle.
  getEntityScopeSkus: (entityId) =>
    get(`/api/entities/${entityId}/scope-skus`),

  addEntityScopeSku: (entityId, data) =>
    post(`/api/entities/${entityId}/scope-skus`, data),

  deleteScopeSku: (scopeSkuId) =>
    request('DELETE', `/api/scope-skus/${scopeSkuId}`),

  // Actions — AC3 recommendation engine. Keyed by cycle_id (numeric,
  // cycleData.id), same convention as the scope-SKU endpoints above.
  generateActions: (cycleId) =>
    post(`/api/cycles/${cycleId}/actions/generate`, {}),

  getRecommendations: (cycleId, { includeSuppressed = false } = {}) =>
    get(`/api/cycles/${cycleId}/recommendations${includeSuppressed ? '?include_suppressed=true' : ''}`),

  getFindings: (cycleId, playId) =>
    get(`/api/cycles/${cycleId}/findings${playId ? '?play_id=' + encodeURIComponent(playId) : ''}`),

  updateRecommendation: (recommendationId, status) =>
    request('PATCH', `/api/recommendations/${recommendationId}`, { status }),
}
