/**
 * Analytics session: the ONE module allowed to import posthog-js
 * (grep-tested — see analytics.test.js). Everything else in this app
 * calls track()/identifyReport()/captureSrcParam()/getAttribution()
 * and never touches posthog directly, so the provider can change
 * without a call-site sweep, and so the privacy/registry guards in
 * track() can never be bypassed by a component reaching for
 * posthog.capture() itself.
 *
 * It also owns paid attribution (see the attribution section below):
 * captureAttribution() runs once at module init, reads the ad
 * platform's oppref/utm_* parameters off the URL into one
 * sessionStorage key, and registers them as super-properties so every
 * event carries them. That is the reason src is no longer 'direct' on
 * ad traffic, and it required no change at any call site.
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

// ─── Attribution (paid traffic) ────────────────────────────────────────
//
// ChatGPT Ads lands visitors on ?oppref=<code>&utm_source=chatgpt.
// Before this block existed, that attribution lived in exactly two
// places — the address bar, and the ad SDK's own first-party cookie —
// and neither survives into a PostHog event: our pushState navigations
// build bare paths, and the cookie is the ad platform's, not ours. So
// paid traffic read as 'direct' on every event by construction.
//
// One sessionStorage key holds the whole set, matching the
// deliberately-session-scoped soaLiteSrc above it and openaiPixel.js's
// guard keys: it survives a cold load of audit-report.html in the same
// tab (the /r/ document is served separately from the landing's), and
// dies with the tab, so a later unattributed visit never inherits a
// campaign it didn't come from.

const SRC_STORAGE_KEY = 'soaLiteSrc'
const ATTRIBUTION_STORAGE_KEY = 'soaLiteAttribution'
const ATTRIBUTION_PARAMS = ['oppref', 'utm_source', 'utm_medium', 'utm_campaign']

function normalizeAttribution(raw) {
  const out = {}
  for (const key of ATTRIBUTION_PARAMS) {
    const value = raw ? raw[key] : null
    out[key] = value === undefined || value === null || value === '' ? null : String(value)
  }
  return out
}

function hasAnyAttribution(attr) {
  return ATTRIBUTION_PARAMS.some((key) => !!attr[key])
}

let attribution = normalizeAttribution(null)

function readStoredAttribution() {
  try {
    const raw = sessionStorage.getItem(ATTRIBUTION_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const normalized = normalizeAttribution(parsed)
    return hasAnyAttribution(normalized) ? normalized : null
  } catch (_) {
    // Blocked or corrupt storage — attribution degrades to unknown,
    // never throws into a page load.
    return null
  }
}

/**
 * The attribution this session was acquired with: oppref (the ChatGPT
 * Ads click code) and the three utm_* parameters, each null when
 * absent. Read from module state, which captureAttribution() fills at
 * init from the URL or from sessionStorage — with a lazy re-read here
 * so a value written after this module loaded is still seen.
 *
 * Callers pass these as event props (LiteForm.jsx's audit_submitted)
 * or as a fallback for a parameter the address bar has already lost
 * (openaiPixel.js's withOppref). Neither identifies a person: an
 * ad-click code and a campaign source describe where the click came
 * from, not who clicked.
 */
export function getAttribution() {
  if (!hasAnyAttribution(attribution)) {
    const stored = readStoredAttribution()
    if (stored) attribution = stored
  }
  return { ...attribution }
}

function registerAttribution() {
  if (!POSTHOG_KEY) return
  // src is always derivable (it bottoms out at 'direct'); the four
  // attribution params are registered only when actually present, so a
  // direct visit's events don't all carry four null props.
  const superProps = { src: captureSrcParam() }
  for (const key of ATTRIBUTION_PARAMS) {
    if (attribution[key]) superProps[key] = attribution[key]
  }
  try {
    posthog.register(superProps)
  } catch (_) {}
}

/**
 * Reads oppref/utm_source/utm_medium/utm_campaign off the current URL,
 * persists whatever is present to sessionStorage under one key
 * (soaLiteAttribution, with a captured_at stamp), and registers them —
 * plus the derived src — as PostHog super-properties, so every event
 * in this session carries them without a single call site changing.
 * A URL carrying none of them loads whatever this session already
 * stored instead, which is what makes the value survive a client-side
 * navigation to a bare /r/{token} path.
 *
 * Called once at module init, deliberately before any component
 * mounts: the landing page's own landing_viewed fires from an effect,
 * and anything that ran earlier than this would have been registered
 * without attribution. A cold load of the report document re-runs it
 * and re-registers from sessionStorage.
 *
 * It never rewrites the address bar. Stripping the parameters here
 * would be the obvious tidy-up and would break two things at once:
 * openaiPixel.js reads oppref off window.location first, and
 * captureSrcParam's strip-only-src behavior is pinned by its own test.
 */
export function captureAttribution() {
  if (typeof window === 'undefined') return getAttribution()

  let url = null
  try {
    url = new URL(window.location.href)
  } catch (_) {
    // A URL jsdom/an exotic embed can't parse — fall back to whatever
    // this session already stored.
  }

  const fromUrl = normalizeAttribution(
    url ? Object.fromEntries(ATTRIBUTION_PARAMS.map((key) => [key, url.searchParams.get(key)])) : null,
  )

  if (hasAnyAttribution(fromUrl)) {
    attribution = fromUrl
    try {
      sessionStorage.setItem(
        ATTRIBUTION_STORAGE_KEY,
        JSON.stringify({ ...attribution, captured_at: new Date().toISOString() }),
      )
    } catch (_) {}
  } else {
    const stored = readStoredAttribution()
    if (stored) attribution = stored
  }

  registerAttribution()
  return getAttribution()
}

/**
 * Reads ?src= off the current URL, stores it in sessionStorage (so it
 * survives the client-side landing -> status -> report navigation
 * within one tab), and strips it from the address bar via
 * history.replaceState — a link copied from the bar after this runs
 * is always the bare canonical URL, never one carrying attribution.
 * ONLY src is stripped: oppref and the utm_* parameters stay exactly
 * where they are (see captureAttribution above, and this file's test).
 * Fires no event itself; callers (landing_viewed, report_viewed) pass
 * the returned value as their own `src` prop.
 *
 * The fallback chain below is what makes a paid visit stop reading as
 * 'direct'. An explicit ?src= still wins outright — it is the only one
 * we set ourselves, on the report-ready email's link — and everything
 * under it is inferred from the attribution the ad platform sent:
 *
 *   explicit src (this URL, or stored this session)
 *   -> utm_source, lowercased
 *   -> 'chatgpt' when there is an oppref but no utm_source
 *      (an oppref is a ChatGPT Ads click code; nothing else mints one)
 *   -> 'direct'
 *
 * No referrer branch: document.referrer would make organic search and
 * social guesses too, which is a separate decision from fixing paid.
 */
export function captureSrcParam() {
  if (typeof window === 'undefined') return 'direct'

  let stored = null
  try {
    stored = sessionStorage.getItem(SRC_STORAGE_KEY)
  } catch (_) {
    // Storage can throw in a locked-down embed context — fall through
    // to the derived value rather than let attribution capture break
    // the page.
  }

  let url = null
  try {
    url = new URL(window.location.href)
  } catch (_) {}

  const src = url ? url.searchParams.get('src') : null

  if (src) {
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

  if (stored) return stored

  const attr = getAttribution()
  const utmSource = (url ? url.searchParams.get('utm_source') : null) || attr.utm_source
  if (utmSource) return String(utmSource).toLowerCase()

  const oppref = (url ? url.searchParams.get('oppref') : null) || attr.oppref
  if (oppref) return 'chatgpt'

  return 'direct'
}

// Attribution is captured once, at module init, right after init() —
// see captureAttribution's own comment for why it cannot wait for a
// component to mount.
captureAttribution()

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
