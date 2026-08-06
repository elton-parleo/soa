// Maps a report check's {state: pass|fail|na|advisory|blocked} onto
// StateChip's seen/partial/invisible/unmeasured vocabulary. na/blocked
// both read unmeasured — H1: never a fabricated invisible for a check
// we didn't actually get to run.
const MAP = { pass: 'seen', fail: 'invisible', advisory: 'partial', na: 'unmeasured', blocked: 'unmeasured' }

export function toChipState(checkState) {
  return MAP[checkState] || 'unmeasured'
}
