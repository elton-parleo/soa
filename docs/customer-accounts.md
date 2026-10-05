# Customer accounts (Step 1C)

A soa org **is** a supply tenant. There is one concept, not two kept in sync.

| soa | supply |
|---|---|
| `organizations.truesync_tenant_slug` | `tenants.slug` |
| `organizations.truesync_token_sealed` (that tenant's service token) | `tenant_tokens` (hash only) |
| — | `tenants.soa_org_id` |

An org with no tenant link is not a customer and never appears in the switcher. Today that is the `Parleo` staff org and `Parleo Lead Gen`.

## Who may select what

- **Operator.** A user with any membership where `organization_members.is_operator` is true. Operators may select every linked org and use the setup wizard.
- **Everyone else.** Pinned to the linked orgs they belong to. Customer logins, when they come, are this case: an org member without the flag, who sees one entry.

`is_operator` is a membership flag, not a `role` value. It is independent of owner/member, and only `scripts/backfill_customer_accounts.py` or a deliberate update ever sets it. Auto-provisioning (`app/org_context.py`) puts new users in `Parleo` as non-operators.

## The selection

- **Client side.** The Command Center's customer switcher stores `{orgId, merchantSlug, prospectSlug}` in `sessionStorage` (`web/src/customerSelection.js`). It is cleared on sign-out.
- **On every request.** Every API request carries `X-Parleo-Customer: <orgId>`.
- **Server side.** `app/customer_context.py` resolves it against the user's rights:
  - an org the user may not select is `403`, never quietly swapped for another;
  - no header means the user's first selectable org.

  It then opens that org's token for the TrueSync proxy.

The study generator's brand dropdown lists the same customers → merchants. It reads a brand's catalog under that brand's org, and the generation job records `customer_organization_id`. The worker and the scorer read the catalog with that org's token (`TrueSyncCatalogClient.for_study`).

## The token

- **Storage.** Sealed with Fernet under `SOA_SECRET_KEY` (`soa_shared/secret_box.py`), which must be set on both Vercel and the pipeline worker.
- **Never leaves the server.** It is not in a response, a log line, a scope's `repr`, or the browser bundle (`truesyncTokenBundle.build.test.js`).
- **Fallback.** `TRUESYNC_TENANT_TOKEN` is only the fallback for a linked org with no stored token. Remove it once every linked org has one.

## Failure behaviour

A refused token fails loudly everywhere:

- **Command Center:** "Not authorized for this customer", naming the org.
- **Generation:** a failed job.
- **Scoring:** a failed cycle, with the reason on the cycle's notes.

Scoring no longer degrades around a refusal. Without the catalog, the staleness lookup has no history, and a `stale` answer would score `wrong`.

## Creating a customer

The setup wizard (`web/src/components/customer-setup/`) is operator-only and has four steps:

1. **Account & customer.** `POST /api/customers` does three things:
   1. creates the org and, if it is new, its supply tenant (supply `POST /api/truesync/tenants`, authorised by `TRUESYNC_PROVISIONING_KEY`), sealing the token onto the org in the same transaction;
   2. creates the merchant (supply `POST /api/truesync/tenant/merchants`) with its `kind` and `hosting`;
   3. writes the retailer list.
2. **Product feed.** `feed/validate`, then a preview and a gate. Errors block; warnings pass. "Continue with the valid rows" commits `all_valid_rows`; a clean file commits `require_clean`. Hidden for `hosting=parleo`.
3. **Customer-owned offers.** Rows are read into structured owned incentives (`offerRows.js`).
4. **Review.** "Create customer" commits the feed and `PUT`s the offers.

From the Command Center, a customer-hosted merchant's feed can be re-uploaded as a new version, and its offers edited, through the same screens.
