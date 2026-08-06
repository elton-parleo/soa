/**
 * D2: barrel export for the ported design-system components. Every
 * file here is extracted verbatim (same render tree, restored from
 * React.createElement to JSX) from the exported bundle at
 * design-refs/20260405_Audit SOA Front-end/_ds/v4-design-system-aug-4-2026-.../
 * _ds_bundle.js — see that directory's README for why (the bundle is a
 * non-ESM IIFE targeting a global window.React, not importable directly
 * into this Vite app).
 *
 * AgentAnswer is deliberately not ported — deferred this session.
 * Delta, Stat, and PulsingDot are internal dependencies of SoAIndex/
 * LeakageEstimator/MetricRow/StatusChip, not part of the named
 * component list, but exported here too since nothing else in this
 * app needs to reach past them.
 */
export { Button } from './Button.jsx'
export { BrandLogo } from './BrandLogo.jsx'
export { Glyph } from './Glyph.jsx'
export { Delta } from './Delta.jsx'
export { SoAIndex } from './SoAIndex.jsx'
export { MonoTag } from './MonoTag.jsx'
export { ProvenanceLine } from './ProvenanceLine.jsx'
export { SectionHeading } from './SectionHeading.jsx'
export { Stat } from './Stat.jsx'
export { LeakageEstimator } from './LeakageEstimator.jsx'
export { MetricRow } from './MetricRow.jsx'
export { StateChip } from './StateChip.jsx'
export { PulsingDot } from './PulsingDot.jsx'
export { StatusChip } from './StatusChip.jsx'
export { OfferFeed } from './OfferFeed.jsx'
export { Wordmark } from './Wordmark.jsx'
export { BrowserChrome } from './BrowserChrome.jsx'
export { Container } from './Container.jsx'
export { DarkPanel } from './DarkPanel.jsx'
export { LogoMarquee } from './LogoMarquee.jsx'
