# Customer setup fixtures

- `acme-pets-10-skus.csv` is an invented feed for an invented store (`acme-pets.test`). Every GTIN is made up with a valid check digit, except row 4, which is deliberately off by one.
- `feed-preview-acme-pets.json` is what supply's 1B validator (`truesync.feed.validate.validate`) returned for that CSV. It is not hand-written.
  - The run used a reachability probe that answers 404 for row 7's URL and 200 for every other URL.
  - The result is 10 rows: 8 ready, 1 warning (`url_unreachable`) and 1 error (`gtin_check_digit`). That is the shape of `design-refs/customer-setup-mock.html`.

To regenerate it, from the supply checkout run `truesync.feed.template.parse` and then `validate`, with `MerchantContext(slug='acme-pets', kind='seller', allowed_domains=['acme-pets.test'])` and the probe described above. Then wrap the preview in the validate route's response shape (`upload_id`, `merchant`, `summary`, `file_errors`, `rows`, `incentives`).

No customer data appears here.
