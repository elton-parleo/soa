/**
 * Analytics session: the ONE module allowed to import posthog-js
 * (grep-tested — see analytics.test.js). Everything else in this app
 * calls track()/identifyReport()/captureSrcParam() and never touches
 * posthog directly, so the provider can change without a call-site
 * sweep, and so the privacy/registry guards in track() can never be
 * bypassed by a component reaching for posthog.capture() itself.
 *
 * Ships dark without VITE_POSTHOG_KEY, exactly like logoProvider.js's
 * VITE_LOGO_DEV_TOKEN gate: every exported function becomes a no-op
 * (init() never runs, track() returns immediately) rather than the
 * app crashing or silently pointing at a shared/default project.
 *
 * Init is deliberately conservative for a report a merchant forwards
 * to their CMO with no warning:
 *   - persistence: 'memory' — cookieless, no consent banner. A repeat
 *     visit in a new tab counts as a new anonymous visitor; that's the
 *     right trade for a link that gets forwarded around a company
 *     rather than a product a single person logs into.
 *   - autocapture/capture_pageview: false — this file's whole point is
 *     that every event is explicit and in the registry; autocapture
 *     and pageview capture would both bypass it.
 *   - session_recording stays on (disable_session_recording: false)
 *     but maskAllInputs — no field ever shows up in a replay, on top
 *     of the registry already forbidding email/name/company/message
 *     as an EVENT prop.
 *   - respect_dnt — a real posthog-js init option; if the browser
 *     sends Do Not Track, PostHog itself no-ops, so this file doesn't
 *     need its own DNT branch.
 *   - Session-replay SAMPLING (target: 20%) is a PostHog **project**
 *     setting (Settings -> Replay -> ingestion controls), not a
 *     posthog-js init key — posthog-js has no client-side sample_rate
 *     option as of this writing. Set it in the dashboard when the
 *     project is created; see the ops note in this PR and
 *     docs/analytics.md.
 */
import posthog from 'posthog-js'
import { EVENT_REGISTRY } from './analyticsEvents.js'

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY
const POSTHOG_HOST = import.meta.env.VITE_POSTHOG_HOST || 'https://us.i.posthog.com'
const IS_DEV = !!import.meta.env.DEV

let initialized = false

function init() {
  if (initialized || !POSTHOG_KEY) return
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    persistence: 'memory',
    autocapture: false,
    capture_pageview: false,
    disable_session_recording: false,
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: '*',
    },
    respect_dnt: true,
  })
  initialized = true
}

init()

/**
 * Records `event` with `props`, both validated against EVENT_REGISTRY.
 * An event not in the registry, or a prop key the registry doesn't
 * list for that event, is dropped — loudly (console.error) in dev,
 * silently in prod, so a typo'd event name fails a local run without
 * ever reaching PostHog as noise. A no-op entirely when
 * VITE_POSTHOG_KEY is unset.
 */
export function track(event, props = {}) {
  if (!POSTHOG_KEY) return

  const allowedProps = EVENT_REGISTRY[event]
  if (!allowedProps) {
    if (IS_DEV) console.error(`[analytics] unknown event "${event}" — not in EVENT_REGISTRY, dropped`)
    return
  }

  const safeProps = {}
  for (const key of Object.keys(props)) {
    const value = props[key]
    if (value === undefined) continue
    if (!allowedProps.includes(key)) {
      if (IS_DEV) console.error(`[analytics] unknown prop "${key}" for event "${event}" — dropped`)
      continue
    }
    safeProps[key] = value
  }

  posthog.capture(event, safeProps)
}

/**
 * Tags every subsequent event in this pageview with report_token as a
 * super-property (posthog.register, not a per-event prop) — this is
 * the mechanism that lets PostHog data join back to soa_demo_requests/
 * soa_lite_requests by token later, without report_token needing to
 * be threaded through every individual event's own prop list.
 */
export function identifyReport(token) {
  if (!POSTHOG_KEY || !token) return
  posthog.register({ report_token: token })
}

const SRC_STORAGE_KEY = 'soaLiteSrc'

/**
 * Reads ?src= off the current URL, stores it in sessionStorage (so it
 * survives the client-side landing -> status -> report navigation
 * within one tab), and strips it from the address bar via
 * history.replaceState — a link copied from the bar after this runs
 * is always the bare canonical URL, never one carrying attribution.
 * Fires no event itself; callers (landing_viewed, report_viewed) pass
 * the returned value as their own `src` prop. Falls back to whatever
 * was already stored this session, then to 'direct'.
 */
export function captureSrcParam() {
  if (typeof window === 'undefined') return 'direct'

  let stored = null
  try {
    stored = sessionStorage.getItem(SRC_STORAGE_KEY)
  } catch (_) {
    // Storage can throw in a locked-down embed context — fall through
    // to 'direct' rather than let attribution capture break the page.
  }

  let url
  try {
    url = new URL(window.location.href)
  } catch (_) {
    return stored || 'direct'
  }

  const src = url.searchParams.get('src')
  if (!src) return stored || 'direct'

  try {
    sessionStorage.setItem(SRC_STORAGE_KEY, src)
  } catch (_) {}

  url.searchParams.delete('src')
  const query = url.searchParams.toString()
  const cleanUrl = `${url.pathname}${query ? `?${query}` : ''}${url.hash}`
  try {
    window.history.replaceState(window.history.state, '', cleanUrl)
  } catch (_) {}

  return src
}

const OWNED_TOKENS_KEY = 'soaLiteOwnedTokens'
const MAX_OWNED_TOKENS = 20

/**
 * Part 3b (owner vs visitor): sessionStorage['soaLiteToken']
 * (LiteWidget.jsx) can't answer "did THIS browser submit this run" —
 * it's overwritten unconditionally on every visit to any /r/{token}
 * URL, including someone else's shared link. This is a genuinely
 * separate signal: a small, capped localStorage list of tokens this
 * browser has itself submitted (LiteForm.jsx's success path calls
 * recordOwnedToken), checked by isTokenOwned at report-view time.
 * localStorage (not sessionStorage) deliberately — an owner checking
 * their own report's status a week later, in a new tab, should still
 * read as 'owner'.
 */
export function recordOwnedToken(token) {
  if (!token || typeof window === 'undefined') return
  try {
    const raw = localStorage.getItem(OWNED_TOKENS_KEY)
    const tokens = raw ? JSON.parse(raw) : []
    if (!Array.isArray(tokens)) throw new Error('corrupt')
    if (!tokens.includes(token)) {
      tokens.push(token)
      while (tokens.length > MAX_OWNED_TOKENS) tokens.shift()
      localStorage.setItem(OWNED_TOKENS_KEY, JSON.stringify(tokens))
    }
  } catch (_) {
    // Corrupt/blocked storage — ownership degrades to 'visitor', never throws.
  }
}

export function isTokenOwned(token) {
  if (!token || typeof window === 'undefined') return false
  try {
    const raw = localStorage.getItem(OWNED_TOKENS_KEY)
    const tokens = raw ? JSON.parse(raw) : []
    return Array.isArray(tokens) && tokens.includes(token)
  } catch (_) {
    return false
  }
}
