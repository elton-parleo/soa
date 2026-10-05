// Two customers for the Command Center's switcher: an invented customer-
// hosted store (Acme Pets, its record the 1B fixture feed) and W&S.
export const KIND_LABEL = { seller: 'Seller', brand: 'Brand' }
export const HOSTING_LABEL = { parleo: 'Parleo-hosted', external: 'Customer-hosted' }

export const CUSTOMERS = {
  is_operator: true,
  customers: [
    {
      org_id: 31, name: 'Acme Pets', tenant_slug: 'acme-pets', error: null,
      merchants: [{ slug: 'acme-pets', name: 'Acme Pets', domain: 'acme-pets.test',
                    kind: 'seller', hosting: 'external', has_record: true }],
    },
    {
      org_id: 7, name: 'Wiggle & Snug', tenant_slug: 'wiggle-and-snug', error: null,
      merchants: [{ slug: 'wiggle-and-snug', name: 'Wiggle & Snug', domain: 'trueshopstore.com',
                    kind: 'seller', hosting: 'parleo', has_record: true }],
    },
  ],
}

export async function listCustomers() { return CUSTOMERS }

export async function createCustomer(body) {
  return {
    org_id: 31, org_name: body.account.name || 'Acme Pets', tenant_slug: 'acme-pets',
    created_account: !body.account.org_id,
    merchant: { slug: 'acme-pets', name: body.merchant.name, domain: body.merchant.domain,
                kind: body.merchant.kind, hosting: body.merchant.hosting, has_record: false },
    retailers: { domains: body.retailers },
  }
}
