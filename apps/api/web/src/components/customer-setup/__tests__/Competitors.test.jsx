/**
 * 2I-6: competitors to track — the section's checks (supply's own rules),
 * the wizard saving them after the customer exists, and the Command Center
 * panel's read-back and save. Writes are mocked; the read-back is the shape
 * PUT/GET /api/customers/{org}/merchants/{slug}/competitors answers
 * (apps/api/tests/test_customers_2i6.py).
 */
import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom'

import CustomerSetupWizard from '../CustomerSetupWizard.jsx'
import CompetitorsPanel from '../CompetitorsPanel.jsx'
import { competitorProblems, filledCompetitors } from '../CompetitorsSection.jsx'
import { createCustomer, lookupDomain, getCompetitors, saveCompetitors } from '../../../customersApi.js'
import { truesyncApi } from '../../../truesyncApi.js'

vi.mock('../../../customersApi.js', () => ({
  createCustomer: vi.fn(), lookupDomain: vi.fn(), getCompetitors: vi.fn(), saveCompetitors: vi.fn(),
}))
vi.mock('../../../truesyncApi.js', () => ({ truesyncApi: { getProvenance: vi.fn(), getOwnedIncentives: vi.fn() } }))

const BRAND = { slug: 'wiggle-and-snug-brand', name: 'Wiggle & Snug Brand', domain: 'wiggleandsnug.com', kind: 'brand', hosting: 'external' }
const READ_BACK = {
  merchant: BRAND.slug, own_domains: ['wiggleandsnug.com'], retailer_domains: ['trueshopstore.com'],
  competitors: [{ domain: 'huggies.com', entity_id: 4, name: 'Huggies' }, { domain: 'kirkland.com', entity_id: null, name: null }],
}
const CREATED = { org_id: 31, org_name: 'Acme Pets', merchant: { slug: 'acme-pets', name: 'Acme Pets', domain: 'acme-pets.test', kind: 'seller', hosting: 'external' } }

beforeEach(() => {
  vi.clearAllMocks()
  createCustomer.mockResolvedValue(CREATED)
  lookupDomain.mockResolvedValue({ status: 'unknown', domain: 'acme-pets.test' })
  truesyncApi.getProvenance.mockResolvedValue(null)
  getCompetitors.mockResolvedValue(READ_BACK)
})

const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

describe('the checks (supply\'s rules, before anything is sent)', () => {
  const own = ['wiggleandsnug.com'], retailers = ['trueshopstore.com']
  it.each([
    ['https://pampers.com', 'A bare site name'], ['www.pampers.com', 'Leave out the leading www.'], ['Pampers.com', 'A bare site name'],
    ['pampers', 'A bare site name'], ['pampers.com/diapers', 'A bare site name'],
    ['wiggleandsnug.com', 'This is the customer\'s own site.'], ['trueshopstore.com', 'This is on the customer\'s retailer list.'],
  ])('%s is refused: %s', (domain, why) => {
    expect(competitorProblems([{ name: 'X', domain }], { own, retailers })[0]).toMatch(why)
  })
  it('a name is needed, a repeat is refused, blank rows are ignored', () => {
    const rows = [{ name: '', domain: 'pampers.com' }, { name: 'Huggies', domain: 'huggies.com' }, { name: 'Huggies 2', domain: 'huggies.com' }, { name: '', domain: '' }]
    expect(competitorProblems(rows, { own, retailers })).toEqual({ 0: expect.stringMatching(/^Name the competitor/), 2: 'Listed twice.' })
    expect(filledCompetitors(rows)).toHaveLength(3)
  })
})

describe('the wizard', () => {
  function fill() {
    render(<CustomerSetupWizard open customers={[]} onClose={vi.fn()} onDone={vi.fn()} />)
    type('Account name', 'Acme Pets'); type('Customer name', 'Acme Pets'); type('Domain', 'acme-pets.test')
    fireEvent.blur(screen.getByLabelText('Domain'))
    type('Competitor 1 name', 'Chewy'); type('Competitor 1 domain', 'chewy.com')
  }
  const cont = () => fireEvent.click(screen.getByRole('button', { name: /^(Continue|Claim and continue)$/ }))

  it('shows the section beside the retailers, with its one line of copy', () => {
    fill()
    expect(screen.getByTestId('competitors')).toHaveTextContent('Competitors to track')
    expect(screen.getByTestId('competitors')).toHaveTextContent('Tracked competitors get full rows on the console')
  })
  it('saves the competitors after the customer exists, for its merchant', async () => {
    saveCompetitors.mockResolvedValue({ ...READ_BACK, competitors: [{ domain: 'chewy.com', entity_id: 9, name: 'Chewy' }] })
    fill()
    await waitFor(() => expect(lookupDomain).toHaveBeenCalled())
    cont()
    await waitFor(() => expect(saveCompetitors).toHaveBeenCalledWith(31, 'acme-pets', [{ name: 'Chewy', domain: 'chewy.com' }]))
    expect(createCustomer.mock.invocationCallOrder[0]).toBeLessThan(saveCompetitors.mock.invocationCallOrder[0])
    await waitFor(() => expect(document.querySelector('.step.on')).toHaveTextContent('Product feed'))   // saved: on to step 2
  })
  it('a refusal keeps the customer, says so, and Continue saves the list again', async () => {
    saveCompetitors.mockRejectedValueOnce(new Error('TrueSync refused the competitor list, so nothing was saved: already one of this merchant\'s own or retailer domains: chewy.com (retailer)'))
    saveCompetitors.mockResolvedValueOnce({ ...READ_BACK, competitors: [{ domain: 'petco.com', entity_id: 10, name: 'Petco' }] })
    fill()
    await waitFor(() => expect(lookupDomain).toHaveBeenCalled())
    cont()
    expect(await screen.findByRole('alert')).toHaveTextContent(/^The customer was created, but its competitors were not saved: TrueSync refused/)
    expect(createCustomer).toHaveBeenCalledTimes(1)
    type('Competitor 1 name', 'Petco'); type('Competitor 1 domain', 'petco.com')
    cont()
    await waitFor(() => expect(saveCompetitors).toHaveBeenLastCalledWith(31, 'acme-pets', [{ name: 'Petco', domain: 'petco.com' }]))
    expect(createCustomer).toHaveBeenCalledTimes(1)
  })
  it('no competitor entered: nothing is saved, and the wizard goes on', async () => {
    render(<CustomerSetupWizard open customers={[]} onClose={vi.fn()} onDone={vi.fn()} />)
    type('Account name', 'Acme Pets'); type('Customer name', 'Acme Pets'); type('Domain', 'acme-pets.test')
    await waitFor(() => expect(lookupDomain).toHaveBeenCalled())
    cont()
    await waitFor(() => expect(createCustomer).toHaveBeenCalled())
    expect(saveCompetitors).not.toHaveBeenCalled()
  })
})

describe('the Command Center panel (an existing customer)', () => {
  it('reads the list back from TrueSync joined to entity names, "no entity yet" where there is none', async () => {
    render(<CompetitorsPanel open orgId={10} merchant={BRAND} onClose={vi.fn()} />)
    expect(await screen.findByTestId('competitors-saved')).toHaveTextContent('Huggies · huggies.com')
    expect(screen.getByTestId('competitors-saved')).toHaveTextContent('no entity yet · kirkland.com')
    expect(getCompetitors).toHaveBeenCalledWith(10, BRAND.slug)
    expect(screen.getByLabelText('Competitor 1 name')).toHaveValue('Huggies')
    expect(screen.getByLabelText('Competitor 2 name')).toHaveValue('')
  })
  it('save sends the rows, and an own or retailer domain cannot be saved', async () => {
    saveCompetitors.mockResolvedValue({ ...READ_BACK, competitors: [{ domain: 'huggies.com', entity_id: 4, name: 'Huggies' }, { domain: 'pampers.com', entity_id: 5, name: 'Pampers' }] })
    const onSaved = vi.fn()
    render(<CompetitorsPanel open orgId={10} merchant={BRAND} onClose={vi.fn()} onSaved={onSaved} />)
    await screen.findByTestId('competitors-saved')
    type('Competitor 2 name', 'Pampers'); type('Competitor 2 domain', 'trueshopstore.com')
    expect(screen.getByText('This is on the customer\'s retailer list.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save competitors' })).toBeDisabled()
    type('Competitor 2 domain', 'pampers.com')
    fireEvent.click(screen.getByRole('button', { name: 'Save competitors' }))
    await waitFor(() => expect(saveCompetitors).toHaveBeenCalledWith(10, BRAND.slug, [
      { name: 'Huggies', domain: 'huggies.com' }, { name: 'Pampers', domain: 'pampers.com' }]))
    expect(await screen.findByText('Pampers')).toBeInTheDocument()
    expect(onSaved).toHaveBeenCalled()
  })
})
