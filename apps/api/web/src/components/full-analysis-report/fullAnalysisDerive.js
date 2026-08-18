// Pure helpers for the full-analysis-only report elements — the
// counterparts to lite's reportDerive.js/liteDerive.js for pieces that
// don't exist in the lite payload at all (platform matrix, stage-driven
// competitor set, evidence, continuation deltas). Mirrors those files'
// conventions: no DOM, no fetches, every function a straight function
// of already-serialized report fields.

// Same rank computation LiteFullReportV4.jsx's own shareOfMentionsRank
// uses, fed competitor_set.overall (the full-analysis payload's
// equivalent of visibility_breakdown.share_of_mentions — both are
// lite_visibility.py::build_visibility_payload's own output shape).
export function shareOfMentionsRank(shareOfMentionsRows) {
  // < 2, not just 0: a scope of just the primary (no competitors — a
  // legacy/invalid launch, see NewCycleFlow.jsx's own Step3 gate) has
  // nothing to rank against. "1st of 1" / 100% share is a real number
  // but a misleading one — an honest null (no rank badge) is correct
  // here, same as an empty scope.
  if (!shareOfMentionsRows || shareOfMentionsRows.length < 2) return null
  const sorted = [...shareOfMentionsRows].sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))
  const idx = sorted.findIndex((e) => e.is_primary)
  if (idx === -1) return null
  const n = idx + 1
  const suffix = n === 1 ? 'st' : n === 2 ? 'nd' : n === 3 ? 'rd' : 'th'
  return `${n}${suffix} of ${sorted.length}`
}

// Envelope {value, numerator, denominator, state} -> StateChip's
// seen/partial/invisible/unmeasured vocabulary — na/not_measured both
// read unmeasured (H1 convention, same as checkState.js's toChipState):
// never a fabricated invisible for something the run didn't actually
// measure. 'measured' bands on the value itself, same seen/partial
// split VisibilitySection.jsx's own share-of-mentions meter uses.
export function envelopeChipState(envelope) {
  if (!envelope || envelope.state === 'na' || envelope.state === 'not_measured') return 'unmeasured'
  if (envelope.value == null) return 'unmeasured'
  return envelope.value >= 50 ? 'seen' : envelope.value > 0 ? 'partial' : 'invisible'
}

export function envelopeLabel(envelope, suffix = '%') {
  if (!envelope || envelope.value == null) return '—'
  return `${Math.round(envelope.value)}${suffix}`
}

// Discovery steps (positive framing — DiscoverySection.jsx, distinct
// from lite's DiscoveryFinding.jsx, which only ever renders the FAILURE
// framing for a partial/degraded lite crawl). Reads the same scan.
// discovery_trace/pages_fetched shape build_scan_payload always writes;
// a step is included only when its underlying fact was actually
// recorded — never an asserted outcome the record doesn't establish.
export function buildDiscoverySteps(scan) {
  const trace = scan?.discovery_trace
  const pagesFetched = scan?.pages_fetched
  if (!trace) return []
  const steps = []
  if (trace.robots_ok != null) {
    steps.push({
      key: 'robots', n: '01', label: 'ROBOTS.TXT', good: trace.robots_ok,
      fact: trace.robots_ok ? 'Read fine. Product paths allowed.' : 'Blocked or rate-limited before it could be read.',
    })
  }
  if (trace.homepage_fetched != null) {
    steps.push({
      key: 'homepage', n: '02', label: 'HOMEPAGE', good: trace.homepage_fetched,
      fact: trace.homepage_fetched ? 'Fetched fine.' : 'Could not be fetched this run.',
    })
  }
  if (trace.sitemaps_read != null && trace.product_urls_found != null) {
    steps.push({
      key: 'sitemaps', n: '03', label: 'SITEMAPS', good: trace.product_urls_found > 0,
      fact: `${trace.sitemaps_read} resolved · ${trace.product_urls_found} product URL${trace.product_urls_found === 1 ? '' : 's'} listed.`,
    })
  }
  const sampled = trace.product_pages_fetched
  const parsed = Array.isArray(pagesFetched) ? pagesFetched.length : null
  if (sampled != null) {
    steps.push({
      key: 'productPages', n: '04', label: 'PRODUCT PAGES', good: sampled > 0,
      fact: parsed != null ? `${sampled} sampled, ${parsed} parsed.` : `${sampled} sampled.`,
    })
  }
  return steps
}
