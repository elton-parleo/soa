/**
 * Parity guard for the JS mirror of soa_shared/scan_dimensions.py —
 * mirrors apps/pipeline/tests/test_scan_dimensions_parity.py's own
 * numbers by hand (no codegen bridge between the two). A future weight
 * change that touches only one side fails here instead of silently
 * drifting between the report's Python-computed numbers and the
 * landing page's illustrative copy.
 */
import { describe, it, expect } from 'vitest'
import {
  SCORER_VERSION, DIMENSIONS, DIMENSIONS_BY_CODE, PILLAR_WEIGHTS, TOTAL_MAX,
  PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE,
  VERDICT_COMPOSITE_THRESHOLD, VERDICT_TRUE_VALUE_RATIO_THRESHOLD,
} from '../scanDimensionsRegistry.js'

describe('scanDimensionsRegistry — parity with soa_shared/scan_dimensions.py', () => {
  it('SCORER_VERSION matches the current re-weighting session', () => {
    expect(SCORER_VERSION).toBe('5')
  })

  it('pillar weights sum to the re-weighted spec: Visibility 32 / Accessibility 18 / True Value 50', () => {
    expect(PILLAR_WEIGHTS[PILLAR_VISIBILITY]).toBe(32)
    expect(PILLAR_WEIGHTS[PILLAR_ACCESSIBILITY]).toBe(18)
    expect(PILLAR_WEIGHTS[PILLAR_TRUE_VALUE]).toBe(50)
    expect(TOTAL_MAX).toBe(100)
  })

  it('True Value dimension weight ordering encodes universality — Member Value is never the biggest', () => {
    const memberValue = DIMENSIONS_BY_CODE.member_value.weight
    expect(DIMENSIONS_BY_CODE.deal_citability.weight).toBeGreaterThan(memberValue)
    expect(DIMENSIONS_BY_CODE.value_protocols.weight).toBeGreaterThan(memberValue)
  })

  it.each([
    ['share_of_mentions', 22],
    ['recommendation_strength', 10],
    ['agent_access', 5],
    ['catalog_context', 8],
    ['protocol_feed', 5],
    ['price_truth', 16],
    ['member_value', 8],
    ['deal_citability', 12],
    ['value_protocols', 14],
  ])('%s weight matches spec (%i)', (code, expectedWeight) => {
    expect(DIMENSIONS_BY_CODE[code].weight).toBe(expectedWeight)
  })

  it('every seen+said split sums to its dimension weight', () => {
    for (const d of DIMENSIONS) {
      if (d.seenMax != null && d.saidMax != null) {
        expect(d.seenMax + d.saidMax).toBe(d.weight)
      }
    }
  })

  it.each([
    ['price_truth', 7, 9],
    ['member_value', 5, 3],
    ['deal_citability', 7, 5],
  ])('%s seen/said split matches spec (%i/%i)', (code, seen, said) => {
    expect(DIMENSIONS_BY_CODE[code].seenMax).toBe(seen)
    expect(DIMENSIONS_BY_CODE[code].saidMax).toBe(said)
  })

  it('value_protocols is seen-only, seenMax equal to its full weight', () => {
    const vp = DIMENSIONS_BY_CODE.value_protocols
    expect(vp.seenMax).toBe(vp.weight)
    expect(vp.saidMax).toBeNull()
  })

  it('the verdict gate thresholds are unchanged by the re-weighting session', () => {
    expect(VERDICT_COMPOSITE_THRESHOLD).toBe(60)
    expect(VERDICT_TRUE_VALUE_RATIO_THRESHOLD).toBe(0.25)
  })
})
