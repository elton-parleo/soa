/**
 * API client for the SoA Platform backend.
 * BASE is empty so requests go to the same origin in production.
 * Vite dev server proxies /api → localhost:8000.
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

  // Cycles
  checkCycleCode: (code) =>
    get(`/api/cycles/check?code=${encodeURIComponent(code)}`),

  createCycle: (data) =>
    post('/api/cycles', data),

  getCycles: () =>
    get('/api/cycles'),

  getCycle: (code) =>
    get(`/api/cycles/${code}`),
}
