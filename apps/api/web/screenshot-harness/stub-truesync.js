import fixture from '../../../pipeline/tests/fixtures/wiggle_and_snug_catalog.json'
export const truesyncApi = {
  getMerchants: async () => fixture.merchants,
  getMerchantCatalog: async () => fixture.catalog,
  getMerchantIncentives: async () => fixture.incentives,
}
