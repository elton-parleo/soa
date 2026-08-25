/**
 * fix/full-analysis-mobile, 1c: the platform matrix can't fit 7 columns
 * at 375px — the wrapper already had overflow-x:auto (pre-existing);
 * this pins the addition, a sticky Platform column so scrolling the
 * other 6 never loses the row label.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { PlatformMatrixSection } from '../PlatformMatrixSection.jsx'

function _row(overrides = {}) {
  return {
    platform: 'chatgpt', platform_name: 'ChatGPT', total_runs: 10,
    share_of_mentions: { value: 50, numerator: 5, denominator: 10, state: 'measured' },
    recommendation_strength_band: 'Listed',
    agent_access: 'allowed',
    price_truth_said: { value: 20, numerator: 1, denominator: 5, state: 'measured' },
    deal_citability: { value: 0, numerator: 0, denominator: 5, state: 'measured' },
    member_value: 'never_cited',
    ...overrides,
  }
}

describe('PlatformMatrixSection — sticky first column', () => {
  it('renders nothing when the matrix is empty', () => {
    const { container } = render(<PlatformMatrixSection matrix={[]} open onToggle={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('the Platform header cell and every row\'s platform_name cell carry position:sticky, left:0', () => {
    render(<PlatformMatrixSection matrix={[_row(), _row({ platform: 'claude', platform_name: 'Claude' })]} open onToggle={() => {}} />)
    const headerCell = screen.getByText('Platform')
    expect(headerCell).toHaveStyle({ position: 'sticky', left: '0px' })
    const chatgptCell = screen.getByText('ChatGPT')
    expect(chatgptCell).toHaveStyle({ position: 'sticky', left: '0px' })
    const claudeCell = screen.getByText('Claude')
    expect(claudeCell).toHaveStyle({ position: 'sticky', left: '0px' })
  })

  it('the table sits inside a horizontal-scroll wrapper (pre-existing — never squashes columns to illegibility)', () => {
    const { container } = render(<PlatformMatrixSection matrix={[_row()]} open onToggle={() => {}} />)
    const wrapper = container.querySelector('table').parentElement
    expect(wrapper).toHaveStyle({ overflowX: 'auto' })
  })

  it('never hides a True Value column — all three (price truth, deal citability, member value) always render, one per row', () => {
    render(<PlatformMatrixSection matrix={[_row()]} open onToggle={() => {}} />)
    expect(screen.getByText('Price truth · said')).toBeInTheDocument()
    expect(screen.getByText('Deal citability')).toBeInTheDocument()
    expect(screen.getByText('Member value')).toBeInTheDocument()
  })
})
