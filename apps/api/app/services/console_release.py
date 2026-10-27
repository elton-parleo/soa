"""
2T-1 (B3): TrueSync as a release page, for a brand at retail (supply's
`mode` manufacturer, 2R-2). The console demo's TrueSync screen
(parleohq/truesync console-demo, screens/v21.tsx and data/v2_pg.ts): the
workspace line, the current release and its surfaces, where the record goes,
the matrix one row per held record, each record's master record, what the
agents said against it (the readback), its timeline and what each surface's
compiler did, and the releases.

Every fact is one supply serves (its held rows and their journal, the
catalog, the feed, retailer-prices, the channels, the rules) or one the
newest scored cycle's answers hold (attribute answers, the price quotes, the
deals named). A demo field with no source is served as None, never filled:
`next_check` (no schedule exists), `approved_by` (no approval is recorded
for a compile), the release name (none is named), a destination's planned
date (supply has no plan record). The copy is RELEASE_TEMPLATES; the router
(app/routers/console_manufacturer.py, release_view) does the reads.
Shapes: docs/console-read-models.md, "2T-1". Deterministic; no model.
"""
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_read_models as rm
from soa_shared import attribute_accuracy, surfaces
from soa_shared import promo_pass_through as ppt
from soa_shared.possessive import possessive

#: The cell vocabulary in manufacturer mode: a held row, a published one, a
#: blocked one, and a channel the record was not compiled for. 2U-2: `live`,
#: a record Parleo serves itself (the MCP server); `next`, a channel that
#: waits on a rule (Deals API, r4); `not_for_brand`, a seller's channel (r3).
CELL_STATES = ('held', 'published', 'live', 'blocked', 'next', 'not_for_brand', 'na')

#: Channels a manufacturer's record never goes to: a seller's (Merchant
#: Center takes offers, the deal directory a seller's deals). WebMCP is not
#: listed: supply has no such channel.
SELLER_ONLY = ('merchant_center', 'deal_directory')

#: The order the demo lists the brand's surfaces in (BRAND_CHANNELS).
SURFACE_ORDER = ('schema_org', 'manufacturer_center', 'acp', 'ucp_uip', 'deals_api', 'mcp')

#: 2U-2: every channel supply has, in its registry's order (GET /channels):
#: the matrix's columns, when supply serves no order of its own.
CHANNEL_ORDER = ('schema_org', 'merchant_center', 'manufacturer_center', 'acp', 'ucp_uip', 'deals_api', 'mcp',
                 'deal_directory')

#: The demo's names for the surfaces, short.
SURFACE_SHORT = {'schema_org': 'Site markup', 'manufacturer_center': 'Manufacturer Center', 'acp': 'ACP feed',
                 'ucp_uip': 'UCP', 'deals_api': 'Deals API', 'mcp': 'MCP server',
                 'merchant_center': 'Merchant Center', 'deal_directory': 'Deal directory'}

#: 2U-2: a channel's state for a brand, one list read by the matrix, the
#: workspace, the release card, the Overview's card and Publishing.
CHANNEL_STATES = ('held', 'blocked', 'live', 'next', 'not_for_brand', 'not_compiled')
#: supply's reason codes (parleo-supply-app truesync/channels/manufacturer_mode.py
#: CHANNEL_REASONS, /tenant `channels[]`): the state a channel with no row is in.
REASON_STATE = {'not_for_brand': 'not_for_brand', 'after_rule': 'next', 'not_compiled': 'not_compiled',
                'next_pass': 'not_compiled'}
#: What supply's plan says, for a supply that serves none (before 2U-2): its
#: compiled channels and its reasons, as 2U-2's CHANNEL_REASONS has them.
FALLBACK_PLAN = {
    'schema_org': {'compiled': True, 'reason': 'held_for_merchant', 'rule': None},
    'manufacturer_center': {'compiled': True, 'reason': 'held_for_merchant', 'rule': None},
    'acp': {'compiled': True, 'reason': 'held_for_merchant', 'rule': None},
    'ucp_uip': {'compiled': True, 'reason': 'held_for_merchant', 'rule': None},
    'mcp': {'compiled': True, 'reason': 'published_by_parleo', 'rule': None},
    'merchant_center': {'compiled': False, 'reason': 'not_for_brand', 'rule': 'r3'},
    'deal_directory': {'compiled': False, 'reason': 'not_for_brand', 'rule': 'r3'},
    'deals_api': {'compiled': False, 'reason': 'after_rule', 'rule': 'r4'},
}
#: The channels Parleo publishes itself for a brand: a published row is `live`.
PARLEO_PUBLISHED = ('mcp',)
RULE_IN_NOTE = re.compile(r'\brule (r\d+)\b')
#: supply 2U-1's clause on a row a rule that is off blocked: "rule_off: rule r1 off (...)"
RULE_OFF_CLAUSE = re.compile(r'^rule_off: rule (r\d+) off\b')

#: 2U-4: supply's mcp readback (held.published.mcp) -> the cell's check. `acceptance` approved / disapproved /
#: unavailable; a disapproval whose reason is "tool not served at <url>" is the server's, not the record's.
CHECKS = ('verified', 'disagrees', 'not_reachable', 'not_served', 'unverified')
TOOL_NOT_SERVED = 'tool not served at '


def _host(url: Optional[str]) -> Optional[str]:
    """'https://mcp.parleo.io/#get_product_facts' -> 'mcp.parleo.io'."""
    text = str(url or '').split('#', 1)[0].split('//', 1)[-1].split('/', 1)[0].strip()
    return text or None


def mcp_check(served: dict) -> str:
    """2U-4: what supply's readback against the public server said: one of CHECKS."""
    acceptance = served.get('acceptance')
    if not served.get('verified_at') or acceptance is None:
        return 'unverified'
    if acceptance == 'approved':
        return 'verified'
    if acceptance == 'unavailable':
        return 'not_reachable'
    if str(served.get('reason') or '').startswith(TOOL_NOT_SERVED):
        return 'not_served'
    return 'disagrees'

#: supply's expressiveness severity -> the compiler line's mark.
MARKS = {'info': 'info', 'dropped': 'dropped', 'approximated': 'approximated', 'blocked': 'conflict'}

#: A rule that is off is journaled as an expressiveness line named so ("rule rN off: ...").
RULE_FLAG = re.compile(r'^rule_(r\d+)$')

#: 2T-3 (6): the compliance rules a manufacturer-mode compile reads on each
#: channel (parleo-supply-app truesync/channels/manufacturer_mode.py): r1 no
#: price, everywhere; r2 retailers in one order, where retailers are listed;
#: r5 one size chart per line, where a weight range goes; r6 a retired line's
#: successor, everywhere, on a record with a retired variant.
CHANNEL_RULES = {'schema_org': ('r1', 'r2', 'r5', 'r6'), 'manufacturer_center': ('r1', 'r5', 'r6'),
                 'acp': ('r1', 'r2', 'r6')}

RELEASE_TEMPLATES = {
    'workspace.mode_note': ("Manufacturer records compiled from the feed and {domain}. Nothing publishes until {brand_s} "
                            "team sends it."),
    'release.name': '{count} records, Manufacturer Center first',
    'release.status.held': 'Compiled, held',
    'release.status.sent': 'Compiled, sent by {who}',
    'release.surface.held': 'Compiled, held · {day}',
    'release.surface.blocked': 'Blocked · {day}',
    'release.surface.published': 'Published · {day}',
    'release.surface.out': 'Not in this pass',
    'release.surface.live': 'Live · {line}',
    'release.surface.not_reachable': 'Not reachable · {line}',
    'release.surface.not_served': 'Tool not served · {line}',
    'release.surface.next': 'Next release · {line}',
    'release.surface.not_for_brand': 'Not for a brand · {line}',
    'release.surface.blocked.rule': 'Blocked · rule {rule} · {day}',
    'channel.held': 'Held',
    'channel.blocked': 'Blocked',
    'channel.live': 'Live',
    'channel.check.not_reachable': 'Not reachable',
    'channel.check.not_served': 'Tool not served',
    'channel.next': 'Next release',
    'channel.not_for_brand': 'Not for a brand',
    'channel.not_compiled': 'Not in this pass',
    'channel.line.held': '{n} of {of} compiled · {day}',
    'channel.line.published': '{n} of {of} published · {day}',
    'channel.line.held.skus': '{n} of {of} SKUs held · {day}',
    'cell.skus': '{n} of {of} SKUs held',
    'channel.line.blocked': 'rule {rule}',
    'channel.line.blocked.none': 'its spec refuses the record',
    'channel.line.live': '{n} records served · verified {day}',
    'channel.line.live.at': '{n} records served · verified {day} at {host}',
    'channel.line.not_reachable': '{n} records published · {host} did not answer the check ({day})',
    'channel.line.not_served': '{n} records published · {host} does not serve get_product_facts ({day})',
    'channel.line.live.unverified': '{n} records served · not verified yet',
    'channel.line.live.short': '{n} records served · {k} of {total} resolve ({day})',
    'channel.line.failed': 'Not published: {error}',
    'channel.line.next': 'after rule {rule}',
    'channel.line.not_for_brand': "a seller's channel (rule {rule})",
    'release.note.account': "Parleo never writes into {name_s} Manufacturer Center account. TrueSync hands the file to its team.",
    'release.note.verify': ("Verification waits for the first live publish. The next check re-asks every prompt that "
                            "quotes these {n} products."),
    'releases.first': 'Feed version {feed}, first compile',
    'releases.changed': 'Feed version {feed}',
    'releases.feed_unknown': 'Feed version not recorded',
    'releases.rules': '{n} rule {changes} since the last compile',
    'releases.approvals': 'None needed yet',
    'releases.verify': 'Waits for the first live publish',
    'releases.superseded': 'Superseded',
    'destination.mc.title': '{brand} Manufacturer Center file',
    'destination.mc.from': "{name_s} feed and {domain}, {day}",
    'destination.mc.against': 'The Manufacturer Center spec ({spec})',
    'destination.mc.who': '{name_s} team',
    'destination.mc.status': 'Held for {name}',
    'destination.mc.status.sent': 'Sent by {name}, {day}',
    'destination.mc.line': "{name_s} team sends it. Parleo never writes into {name_s} accounts.",
    'destination.other.title': 'Proof of push: {name}',
    'destination.other.status': 'Compiled, not sent',
    'destination.other.line': "{name}'s compiled records go out before {brand_s} file, so the push is proven first.",
    'record.price': 'Not set. Retailers price it',
    'record.weight.none': 'No chart on {domain}',
    'record.gtin.none': 'None in the feed',
    'record.gtin.source': '{gtin} ({source})',
    'record.pack.page': '{domain} lists {counts}',
    'record.claims.note': '{domain}, {day}',
    'record.where.unread': '{names} listed. Not read yet',
    'record.unread': '{names}: not read yet',
    'record.not_in_feed': "The merchant's retailers the feed does not list for it. No shelf read says they do not carry it",
    'record.walled': '{names}: walled',
    'drift.weight.none': 'No range stated',
    'drift.shelf.truth': 'Named in {named} of {asked} answers',
    'timeline.brand_page': '{domain} read: {what}',
    'timeline.brand_page.what.chart': 'the size chart',
    'timeline.brand_page.what.claims': 'the claims',
    'timeline.brand_page.what.markup': 'the markup',
    'timeline.shelf': 'Shelf read: {read}',
    'timeline.shelf.read': '{names} read',
    'timeline.shelf.walled': '{names} walled',
    'timeline.shelf.unread': '{names} listed, not read yet',
    'timeline.readback': 'Read back: {parts}',
    'timeline.readback.weight': 'weight right {k} of {n}',
    'timeline.readback.price': 'prices right {k} of {n}',
    'timeline.readback.deals': 'live deals named {k} of {n}',
    'timeline.compiled': 'Compiled in manufacturer mode. Held on {held}{blocked}. Nothing published',
    'timeline.compiled.blocked': ', blocked on {blocked}',
    'timeline.compiled.live': 'Compiled in manufacturer mode. Held on {held}{blocked}. Live on {live}, which Parleo serves',
    'timeline.sent': '{who} says it sent the {channel} file',
    'compiler.carried': 'Validated against {spec}',
    'compiler.rules': '{rules} {verb}, {on}',
    'compiler.rules.none_on': 'none on',
    'compiler.rules.all_on': 'all on',
    'compiler.rules.some_on': '{codes} on',
    'compiler.rule.manufacturer_center': ('Manufacturer Center keys every product by GTIN and excludes price and '
                                          'availability by spec.'),
    'compiler.rule.schema_org': 'Product with its GTIN, size and pack count. No price: retailers set it.',
    'compiler.rule.acp': 'The ACP feed needs a seller and a price on every item, so manufacturer mode cannot send it.',
}

T = RELEASE_TEMPLATES


def _gtin14(value) -> Optional[str]:
    return rm._gtin14(value)


def _norm(text: Optional[str]) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


# ─── the hold ─────────────────────────────────────────────────────────────

def pass_channels(pubs: List[dict]) -> List[str]:
    """The channels this pass compiled for (the hold's rows), in the demo's order."""
    slugs = {p.get('channel_slug') or p.get('channel') for p in pubs or []}
    return sorted((s for s in slugs if s and s not in SELLER_ONLY),
                  key=lambda s: (SURFACE_ORDER.index(s) if s in SURFACE_ORDER else len(SURFACE_ORDER), s))


#: supply 2U-1: channels held one row per feed SKU (`feed:<merchant>:<variant_key>`), not per record.
PER_SKU = ('ucp_uip',)


def sku_records(pubs: List[dict]) -> Dict[str, str]:
    """{SKU ref: its record's ref}, from each record's schema_org payload: a
    variant's GTIN-14, else `sku:<sku>`, is supply's variant_key."""
    out: Dict[str, str] = {}
    for row in manu.latest_by_record(pubs, 'schema_org'):
        ref = str(row.get('record_ref') or '')
        if not ref.startswith('feed:'):
            continue
        prefix = ':'.join(ref.split(':')[:2])
        payload = row.get('payload') if isinstance(row.get('payload'), dict) else {}
        for node in payload.get('hasVariant') or []:
            gtin = next((node[k] for k in ('gtin14', 'gtin13', 'gtin12', 'gtin8', 'gtin') if node.get(k)), None)
            key = _gtin14(gtin) if gtin else (f"sku:{node['sku']}" if node.get('sku') else None)
            if key:
                out[f'{prefix}:{key}'] = ref
    return out


def _fold(rows: List[dict]) -> dict:
    """A record's cell on a per-SKU channel: its held row when any SKU is held (else its first), carrying
    every SKU's row as `sku_rows`, so the cell can say how many are held."""
    rows = sorted(rows, key=lambda r: r.get('id') or 0)
    lead = next((r for r in rows if manu.is_held(r)), rows[0])
    return {**lead, 'sku_rows': rows}


def hold(pubs: List[dict]) -> Dict[str, Dict[str, dict]]:
    """{record_ref: {channel: its newest row}} over the merchant's rows,
    records in the order supply first compiled them. 2U-2 (supply 2U-1): a
    per-SKU channel's rows (ucp_uip) fold into their record (sku_records),
    one cell per record with `sku_rows` beside it."""
    out: Dict[str, Dict[str, dict]] = {}
    skus = sku_records(pubs)
    per_sku: Dict[str, Dict[str, List[dict]]] = {}
    for channel in pass_channels(pubs):
        for row in manu.latest_by_record(pubs, channel):
            ref = row.get('record_ref') or str(row.get('listing_id'))
            if channel in PER_SKU and ref in skus:
                per_sku.setdefault(skus[ref], {}).setdefault(channel, []).append(row)
                continue
            out.setdefault(ref, {})[channel] = row
    for ref, channels in per_sku.items():
        for channel, rows in channels.items():
            out.setdefault(ref, {})[channel] = _fold(rows)
    return dict(sorted(out.items(), key=lambda kv: min(r.get('id') or 0 for r in kv[1].values())))


def cell_state(row: Optional[dict]) -> str:
    if row is None:
        return 'na'
    if row.get('status') == manu.LIVE_STATUS:
        # 2U-2: a channel Parleo publishes itself (the MCP server) is live, not "published" by the brand
        return 'live' if (row.get('channel_slug') or row.get('channel')) in PARLEO_PUBLISHED else 'published'
    if manu.is_blocked(row):
        return 'blocked'
    if manu.is_held(row):
        return 'held'
    return 'na'


def _channel_names(channels: List[dict]) -> Dict[str, dict]:
    return {c.get('slug'): c for c in channels or []}


# ─── the channels (2U-2) ──────────────────────────────────────────────────

def _blocked_rule(rows: List[dict], planned: Optional[str]) -> Optional[str]:
    """The rule a blocked channel names: supply's plan's, else the first "rule rN" its rows' lines state."""
    if planned:
        return planned
    for r in rows:
        found = RULE_OFF_CLAUSE.match(str(r.get('spec_clause') or ''))
        if found:
            return found.group(1)
    for r in rows:
        for e in r.get('expressiveness') or []:
            found = RULE_IN_NOTE.search(str(e.get('note') or ''))
            if found and e.get('field') in ('channel', 'price'):
                return found.group(1)
    return None


def channel_list(*, pubs: List[dict], channels: List[dict], plan: Optional[List[dict]],
                 held: Optional[dict]) -> List[dict]:
    """
    Every channel supply has, in supply's order, as a brand's compile left it:
    {id, channel, name, short, spec, state, label, line, reason, rule, note,
    in_pass, compiled, of, blocked}. `plan` is supply's /tenant `channels[]`
    (each {channel, compiled, reason, rule, note}; FALLBACK_PLAN when absent),
    `held` its /tenant `held` (`published.mcp`: records served, verified).

      held / blocked   from the hold's newest rows per record (blocked names
                       its rule: supply's, else the one its lines state)
      live             a channel Parleo publishes itself with published rows:
                       "<N> records served · verified <day> at <host>" (the
                       readback against the public server; 2U-4: N is SKUs).
                       `check` says what the readback found (mcp_check): a
                       server that did not answer is labelled "Not reachable",
                       one without the tool "Tool not served", never "Live"
      next             supply's reason after_rule: "after rule r4"
      not_for_brand    supply's reason not_for_brand: "a seller's channel (rule r3)"
      not_compiled     anything else: supply's note
    """
    by_slug = _channel_names(channels)
    plan_by = {p.get('channel'): p for p in plan or [] if p.get('channel')}
    order = [p['channel'] for p in plan or [] if p.get('channel')] or \
        [c['slug'] for c in channels or [] if c.get('slug') and c.get('is_active', True)] or list(CHANNEL_ORDER)
    published = (held or {}).get('published') or {}
    folded = hold(pubs)
    records = len(folded)
    # 2U-4: a supply that counts in SKUs (its held carries `lines`): every channel's cell counts SKUs, a line's
    # row as its SKUs, so a line-held channel and UCP (held per SKU) read alike ("10 of 10 SKUs held")
    in_skus = 'lines' in (held or {})
    line_skus = Counter(sku_records(pubs).values()) if in_skus else Counter()
    out = []
    for slug in order:
        entry = plan_by.get(slug) or FALLBACK_PLAN.get(slug) or {'compiled': False, 'reason': 'not_compiled'}
        # one row per record (a per-SKU channel's folded, its SKUs' rows beside it)
        rows = [per[slug] for per in folded.values() if slug in per]
        skus = [x for r in rows for x in r.get('sku_rows') or [r]]
        states = [cell_state(r) for r in rows]
        live = [r for r in rows if r.get('status') == manu.LIVE_STATUS]
        held_rows = [r for r in rows if manu.is_held(r)]
        valid = [r for r in held_rows if manu.is_valid(r)]
        blocked_rows = [r for r in rows if manu.is_blocked(r)] + [r for r in held_rows if not manu.is_valid(r)]
        failed = [r for r in rows if r.get('status') == 'failed']
        newest = max((str(r.get('compiled_at') or '') for r in rows), default=None)
        day = manu.short_day(newest) if newest else None
        rule = entry.get('rule')
        note = entry.get('note')
        if live and slug not in PARLEO_PUBLISHED:
            state, line = 'live', T['channel.line.published'].format(n=len(live), of=records, day=day)
        elif live:
            state = 'live'
            served = published.get(slug) or {}
            # 2U-4: supply counts records in SKUs (`records`); a supply before it counted lines there
            n = served.get('records') or served.get('skus') or len(live)
            verified = served.get('verified_at')
            check = mcp_check(served)
            host = _host(served.get('server') or served.get('external_ref'))
            day_v = manu.short_day(verified) if verified else None
            if check == 'verified':
                line = (T['channel.line.live.at'].format(n=n, day=day_v, host=host) if served.get('server')
                        else T['channel.line.live'].format(n=n, day=day_v))
            elif check in ('not_reachable', 'not_served'):
                line = T[f'channel.line.{check}'].format(n=n, host=host or 'the server', day=day_v)
            elif check == 'disagrees':
                k, _, total = str(served.get('verified_skus') or '0/0').partition('/')
                line = T['channel.line.live.short'].format(n=n, k=k, total=total, day=day_v)
            else:
                line = T['channel.line.live.unverified'].format(n=n)
            note = served.get('external_ref') or note
        elif valid and slug in PER_SKU:
            state = 'held'
            line = T['channel.line.held.skus'].format(n=sum(1 for x in skus if manu.is_held(x)), of=len(skus), day=day)
        elif valid and in_skus:
            state = 'held'
            n = sum(line_skus.get(r.get('record_ref'), 1) for r in held_rows)
            of = ((held or {}).get('by_channel') or {}).get(slug) or sum(line_skus.get(r.get('record_ref'), 1) for r in rows)
            line = T['channel.line.held.skus'].format(n=n, of=of, day=day)
        elif valid:
            state, line = 'held', T['channel.line.held'].format(n=len(held_rows), of=records, day=day)
        elif blocked_rows:
            state = 'blocked'
            rule = _blocked_rule([x for x in skus if manu.is_blocked(x)] or blocked_rows, rule)
            line = T['channel.line.blocked'].format(rule=rule) if rule else T['channel.line.blocked.none']
            note = next((r.get('spec_clause') for r in blocked_rows if r.get('spec_clause')), None) or \
                next((e for r in blocked_rows for e in (r.get('validation') or {}).get('errors') or []), note)
        elif failed and slug in PARLEO_PUBLISHED:
            # a publish we could not make (no public URL, a SKU that did not resolve): not live, and why
            state = 'blocked'
            line = T['channel.line.failed'].format(error=failed[-1].get('error') or 'failed')
            note = failed[-1].get('error')
        else:
            state = REASON_STATE.get(entry.get('reason'), 'not_compiled')
            if state == 'next':
                line = T['channel.line.next'].format(rule=rule)
            elif state == 'not_for_brand':
                line = T['channel.line.not_for_brand'].format(rule=rule)
            else:
                line = note or manu.T['not_compiled']
        c = by_slug.get(slug) or {}
        check = mcp_check(published.get(slug) or {}) if state == 'live' and slug in PARLEO_PUBLISHED else None
        label = T[f'channel.check.{check}'] if check in ('not_reachable', 'not_served') else T[f'channel.{state}']
        out.append({
            'id': slug, 'channel': slug, 'name': SURFACE_SHORT.get(slug) or c.get('name') or slug,
            'short': SURFACE_SHORT.get(slug) or c.get('name') or slug, 'spec': c.get('spec_version') or '',
            'state': state, 'label': label, 'line': line, 'check': check,
            'reason': entry.get('reason'), 'rule': rule, 'note': note,
            # 2U-4: why supply's readback did not approve (its words), for the cell's detail
            'check_reason': (published.get(slug) or {}).get('reason') if check else None,
            'in_pass': state in ('held', 'blocked', 'live'),
            'compiled': sum(1 for x in states if x in ('held', 'published', 'live')) if rows else 0,
            'of': records, 'blocked': sum(1 for x in states if x == 'blocked'),
        })
    return out


# ─── a record's variants ─────────────────────────────────────────────────

def _listing(catalog: Optional[dict], record_ref: str) -> Optional[dict]:
    return next((l for l in (catalog or {}).get('listings') or [] if l.get('product_id') == record_ref), None)


def _feed_row(feed_rows: List[dict], variant: dict) -> Optional[dict]:
    vid = variant.get('variant_id')
    for row in feed_rows or []:
        if row.get('variant_key') and row.get('variant_key') == vid:
            return row
        if row.get('gtin') and _gtin14(row.get('gtin')) == _gtin14(vid):
            return row
    return None


#: 2T-3 (9): a feed's variant label that says it is retired ("Size 1 (retired)"): the record says so once, itself.
_RETIRED_MARK = re.compile(r'\s*\(\s*retired\s*\)', re.I)


def record_variants(record_ref: str, catalog: Optional[dict], feed_rows: Optional[List[dict]]) -> List[dict]:
    """The held record's variants: the catalog listing whose product_id is
    the record_ref, each with its feed row. [{variant_id, label, count, gtin,
    sku, status, successor, product_name, retailers, feed}]."""
    listing = _listing(catalog, record_ref) or {}
    out = []
    for v in listing.get('variants') or []:
        row = _feed_row(feed_rows or [], v) or {}
        label = v.get('title') or row.get('variant_label')
        out.append({'variant_id': v.get('variant_id'), 'label': _RETIRED_MARK.sub('', label).strip() if label else label,
                    'count': v.get('count') if v.get('count') is not None else row.get('pack_count'),
                    'gtin': v.get('gtin') or row.get('gtin'), 'sku': row.get('sku'), 'status': v.get('status'),
                    'successor': v.get('successor'),
                    'product_name': row.get('product_name') or listing.get('title'),
                    'retailers': [r.get('domain') for r in row.get('retailers') or [] if r.get('domain')],
                    # 2T-4 (5): the page the feed row links to on each site (its product_url_<domain>)
                    'retailer_urls': {r['domain']: r['url'] for r in row.get('retailers') or []
                                      if r.get('domain') and r.get('url')},
                    'url': listing.get('product_url')})
    return out


def _row_matches(row: dict, variant: dict) -> bool:
    """A retailer-prices row is the variant's when its sku or GTIN is."""
    if variant.get('sku') and row.get('sku') == variant['sku']:
        return True
    return bool(variant.get('gtin') and row.get('gtin') and _gtin14(row['gtin']) == _gtin14(variant['gtin']))


def variant_rows(prices: Optional[List[dict]], variant: dict) -> List[dict]:
    return [r for r in prices or [] if _row_matches(r, variant)]


#: A reference read's price method when the page was walled: nothing read it.
WALLED_METHODS = (None, 'none', 'wall')


def shelf_reads(rows: Optional[List[dict]], own_domains: Iterable[str]) -> dict:
    """2T-3 (1): what the shelf reads say per retailer, the one rule the
    record timeline and the Overview's activity both read. A retailer is
    read when at least one SKU's reference read on it has a price method
    other than none (an own fetch, a hosted render), walled only when every
    read on it walled, unread when no read of it is dated. {read, walled,
    unread: [names], walled_skus: {name: SKUs walled on a retailer read}, at}."""
    own = {_domain(d) for d in own_domains or () if d}
    shelf = [r for r in rows or [] if r.get('role') != 'own' and _domain(r.get('retailer_domain')) not in own]
    by: Dict[str, List[dict]] = {}
    for r in shelf:
        by.setdefault(rm._retailer_name(_domain(r.get('retailer_domain'))), []).append(r)
    read, walled, unread, walled_skus = [], [], [], {}
    for name, mine in by.items():
        dated = [r for r in mine if r.get('observed_at')]
        if not dated:
            unread.append(name)
            continue
        walls = [r for r in dated if r.get('method') in WALLED_METHODS]
        if len(walls) == len(dated):
            walled.append(name)
        else:
            read.append(name)
            if walls:
                walled_skus[name] = len({r.get('sku') or r.get('gtin') or r.get('variant_ref') for r in walls})
    return {'read': sorted(read), 'walled': sorted(walled), 'unread': sorted(unread), 'walled_skus': walled_skus,
            'at': max((str(r['observed_at']) for r in shelf if r.get('observed_at')), default=None)}


def _chart_entry(chart: Optional[List[dict]], label: Optional[str]) -> Optional[dict]:
    size = attribute_accuracy.size_of(label)
    if size is None:
        return None
    key = {'0': 'newborn', 'p': 'preemie'}.get(size, size)
    return next((c for c in chart or [] if str(c.get('size') or '').lower() == key), None)


_MARKS = re.compile(r"[®™°℠©]")
#: A product name's first word that names the product type, not the line (supply's brand_page._GENERIC).
_GENERIC = re.compile(r"\b(?:diapers?|pull[- ]?ons?|pants|wipes|trainers?|nappies|for)\b", re.I)


def page_line(name: Optional[str]) -> Optional[str]:
    """A brand page's own line, as supply's brand_page.line_name reads it: marks out, the part
    before "|", up to the first product-type word ("Pampers® Swaddlers™ Diapers for Babies and
    Newborns" -> "Pampers Swaddlers", "Pampers® Zzz | Pampers" -> "Pampers Zzz")."""
    text = _MARKS.sub('', str(name or '')).split('|')[0]
    cut = _GENERIC.search(text)
    text = re.sub(r'\s+', ' ', text[:cut.start()] if cut else text).strip(' -,:')
    return text or None


def line_key(name: Optional[str], brand: Optional[str]) -> Optional[str]:
    """One key for a line however a feed or a page writes it."""
    line = page_line(name)
    return rm.line_of(line, brand) if line else None


def line_charts(prices: Optional[List[dict]], own_domains: Iterable[str], brand: Optional[str]) -> Dict[str, list]:
    """2T-3 (2): {line key: the size chart} from the brand's own pages, newest
    read first, each keyed by the line the page itself names (its markup's
    product name), never by the SKU whose URL led there: a URL that lands on
    another line's page (pampers.com sends Swaddlers Ultra to Swaddlers) gives
    that line's chart, not the record's. The facts supply's r5 reads (2S-1)."""
    own = {_domain(d) for d in own_domains or () if d}
    rows = [r for r in prices or [] if (r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own)
            and r.get('size_chart')]
    rows.sort(key=lambda r: str(r.get('observed_at') or ''), reverse=True)
    out: Dict[str, list] = {}
    for r in rows:
        key = line_key((r.get('json_ld') or {}).get('name'), brand)
        if key and key not in out:
            out[key] = r['size_chart']
    return out


def _url_key(url) -> Optional[str]:
    """A page's address for matching: host and path, no scheme, www, query, fragment or trailing slash."""
    text = str(url or '').strip().lower()
    if not text:
        return None
    text = text.split('//', 1)[-1].split('#', 1)[0].split('?', 1)[0].removeprefix('www.').rstrip('/')
    return text or None


def own_urls(urls: Iterable[str], own_domains: Iterable[str]) -> List[str]:
    """The addresses among `urls` on the brand's own sites."""
    own = {_domain(d) for d in own_domains or () if d}
    return [k for k in dict.fromkeys(_url_key(u) for u in urls or () if u) if k and _domain(k.split('/', 1)[0]) in own]


def page_chart(prices: Optional[List[dict]], urls: Iterable[str], *, own_domains: Iterable[str] = (),
               line: Optional[str] = None, brand: Optional[str] = None) -> Optional[List[dict]]:
    """
    2T-4 (5): the size chart of the page a feed row links to: the brand's
    own read whose `url` is one of `urls` (the row's own-site links), newest
    first. A read that landed on another page (`final_url` not its `url`)
    is that page's: its chart counts only when the page names the row's own
    `line` (2T-3's Swaddlers Ultra link that lands on the Swaddlers page gets
    nothing, never Swaddlers' chart). None when no read of the page has one.
    """
    wanted = set(own_urls(urls, own_domains))
    if not wanted:
        return None
    own = {_domain(d) for d in own_domains or () if d}
    rows = [r for r in prices or [] if (r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own)
            and r.get('size_chart') and _url_key(r.get('url')) in wanted]
    rows.sort(key=lambda r: str(r.get('observed_at') or ''), reverse=True)
    for r in rows:
        landed = _url_key(r.get('final_url'))
        if landed and landed != _url_key(r.get('url')):
            page = line_key((r.get('json_ld') or {}).get('name'), brand)
            if not page or page != line_key(line, brand):
                continue
        return r['size_chart']
    return None


def _feed_urls(variant: dict) -> List[str]:
    """Every link a record variant (record_variants) or a feed row carries."""
    urls = list((variant.get('retailer_urls') or {}).values()) + [variant.get('url')]
    urls += [r.get('url') for r in variant.get('retailers') or [] if isinstance(r, dict)]
    return [u for u in urls if u]


def chart_for(prices: Optional[List[dict]], variant: dict, *, own_domains: Iterable[str] = (),
              brand: Optional[str] = None, by_name: Optional[Dict[str, list]] = None) -> Optional[List[dict]]:
    """2T-4 (5): a feed row's (or a record variant's) chart: the page it links
    to on the brand's site (page_chart); by its line's name (line_charts) only
    when it links to no page there."""
    urls = _feed_urls(variant)
    if own_urls(urls, own_domains):
        return page_chart(prices, urls, own_domains=own_domains, line=variant.get('product_name'), brand=brand)
    charts = by_name if by_name is not None else line_charts(prices, own_domains, brand)
    return charts.get(line_key(variant.get('product_name') or variant.get('variant_label'), brand))


def feed_line_charts(prices: Optional[List[dict]], feed_rows: Optional[List[dict]], own_domains: Iterable[str],
                     brand: Optional[str]) -> Dict[str, list]:
    """2T-4 (5): {the feed's line key: its chart}, each feed line's chart the
    page its rows link to (chart_for), the first row with one; the readers of
    line_charts' keys (the lead signal, the size-chart groups) read it the
    same. Without the feed, line_charts."""
    by_name = line_charts(prices, own_domains, brand)
    if feed_rows is None:
        return by_name
    out: Dict[str, list] = {}
    for row in feed_rows:
        key = line_key(row.get('product_name'), brand)
        if not key or key in out:
            continue
        chart = chart_for(prices, row, own_domains=own_domains, brand=brand, by_name=by_name)
        if chart:
            out[key] = chart
    return out


def record_chart(prices: Optional[List[dict]], variants: List[dict], *, own_domains: Iterable[str] = (),
                 brand: Optional[str] = None) -> Optional[List[dict]]:
    """The record's size chart. 2T-4 (5): the chart of the page its feed rows
    link to on the brand's site (chart_for); by its line's name only for a
    record with no page there. Never a retailer page's, never another line's."""
    by_name = line_charts(prices, own_domains, brand)
    for v in variants:
        chart = chart_for(prices, v, own_domains=own_domains, brand=brand, by_name=by_name)
        if chart:
            return chart
    return None


def weight_of(chart: Optional[List[dict]], label: Optional[str]) -> Optional[str]:
    entry = _chart_entry(chart, label)
    return attribute_accuracy.phrase({'min': entry.get('min'), 'max': entry.get('max')}) if entry else None


def _variant_words(v: dict, chart) -> str:
    """"Size 4, 104 ct, 22 to 37 lb": the label, the count when the label does not say it, the chart's range."""
    label = v.get('label') or ''
    parts = [label] if label else []
    if v.get('count') and not re.search(r'\b\d+\s*ct\b', label):
        parts.append(f"{v['count']} ct")
    weight = weight_of(chart, label)
    if weight:
        parts.append(weight)
    return ', '.join(parts)


def _variant_short(v: dict) -> str:
    """"Newborn 84 ct": the label without its commas, the count when the label does not say it."""
    label = re.sub(r'\s*,\s*', ' ', v.get('label') or '').strip()
    if v.get('count') and not re.search(r'\b\d+\s*ct\b', label):
        label = f"{label} {v['count']} ct".strip()
    return label


def subtitle(variants: List[dict], chart) -> str:
    return ' · '.join(w for w in (_variant_words(v, chart) for v in variants) if w)


# ─── what the agents said against the record (the readback) ──────────────

def _line_size(text: Optional[str], brand: Optional[str]) -> tuple:
    return rm.line_of(text, brand), attribute_accuracy.size_label(text)


def matches_variant(variants: List[dict], *, variant_id=None, label: Optional[str] = None,
                    line_text: Optional[str] = None, brand: Optional[str] = None) -> Optional[dict]:
    """The record variant an answer is about: its variant id, else the same
    label (normalized), else the same line and size when one variant has them."""
    for v in variants:
        if variant_id is not None and variant_id in (v.get('variant_id'), v.get('sku'), f"sku:{v.get('sku')}"):
            return v
    if label:
        same = [v for v in variants if _norm(v.get('label')) == _norm(label)]
        if len(same) == 1:
            return same[0]
    if line_text:
        line, size = _line_size(line_text, brand)
        same = [v for v in variants if size and attribute_accuracy.size_label(v.get('label')) == size
                and rm.line_of(v.get('product_name'), brand) == line]
        if len(same) == 1:
            return same[0]
    return None


_VERDICT = {'match': 'right', 'mismatch': 'wrong', 'absent': 'missed'}
_PRICE_VERDICT = {'exact': 'right', 'partial': 'partial', 'wrong': 'wrong', 'stale': 'wrong'}


def readback(variants: List[dict], *, attribute_answers: List[dict], true_value_rows: List[dict],
             promo: Optional[dict], deals: Optional[dict], brand: Optional[str], charted: bool = True) -> List[dict]:
    """Every fact an agent stated about the record's variants in the cycle,
    against the record: weight (the attribute answers), price (the True
    Value quotes, against the retailer's live price), and one shelf row per
    deal live on the record's variants with how many answers named it.
    [{agent, fact, variant, said, truth, verdict (right | partial | wrong |
    missed), run}], wrong first. 2T-3 (2): a record whose line has no chart
    on the brand's page (`charted` False) has no weight to read back against."""
    out = []
    for a in (attribute_answers or []) if charted else []:
        v = matches_variant(variants, variant_id=a.get('variant_id'), line_text=a.get('variant'), brand=brand)
        if v is None or a.get('verdict') is None:
            continue
        out.append({'agent': surfaces.agent_of(a.get('platform')) or a.get('platform'), 'fact': 'weight', 'variant': v.get('label'),
                    'said': attribute_accuracy.phrase(a.get('stated')) or T['drift.weight.none'],
                    'truth': attribute_accuracy.phrase(a.get('truth')), 'verdict': _VERDICT.get(a['verdict'], 'wrong'),
                    'run': f"run-{a['run_id']}", 'surface': a.get('surface')})
    for row in true_value_rows or []:
        v = matches_variant(variants, variant_id=row.get('sku'), label=row.get('product'), brand=brand)
        if v is None:
            continue
        for col, cell in (row.get('retailer_cells') or row.get('cells') or {}).items():
            name = rm._retailer_name(col)
            for q in cell.get('quotes') or []:
                verdict = _PRICE_VERDICT.get(q.get('outcome'))
                if verdict is None or not q.get('stated'):
                    continue
                # 2T-4 (3): the truth is the read the quote was judged against (the cell's `live`), and a
                # later read of the page is its own line, never the truth beside that verdict
                out.append({'agent': q.get('agent'), 'fact': 'price', 'variant': v.get('label'),
                            'said': f"{name} ${q['stated']}",
                            'truth': f"{name} {cell['live']}" if cell.get('live') else None,
                            **({'later': cell['later']['text']} if cell.get('later') else {}),
                            'verdict': verdict, 'run': q.get('run'), 'surface': q.get('surface')})
    ids = {v.get('variant_id') for v in variants} | {v.get('sku') for v in variants if v.get('sku')}
    for deal in (deals or {}).get('deals') or []:
        mine = [e for e in deal.get('variants') or [] if any(_row_matches(e, v) for v in variants)]
        if not mine or ppt.out_of_stock(deal, mine[0]):
            continue
        did = ppt.deal_id(deal)
        judged = [j for j in (promo or {}).get('judged') or [] if did in (j.get('live') or [])
                  and (j.get('variant_id') in ids or any(_row_matches(e, {'sku': j.get('variant_id')}) for e in mine))]
        named = sum(1 for j in judged if did in j.get('named') or [])
        out.append({'agent': 'shelf', 'fact': 'deal', 'variant': mine[0].get('variant_label'),
                    'said': ppt.label(deal, mine[0]), 'truth': T['drift.shelf.truth'].format(named=named, asked=len(judged)),
                    # 2T-3 (5): the promo rule: right when every answer on the SKU named it, left out when none did
                    'verdict': 'right' if judged and named == len(judged) else 'missed' if not named else 'partial',
                    'run': None, 'surface': None,
                    'named': named, 'asked': len(judged)})
    rank = {'wrong': 0, 'partial': 1, 'missed': 2, 'right': 3}
    return sorted(out, key=lambda r: (r['agent'] == 'shelf', rank.get(r['verdict'], 4), r['fact'], str(r['agent'])))


def disagree(lines: List[dict], agents: Iterable[str]) -> dict:
    """{agents, of}: the agents with at least one fact against the record, of the cycle's agents."""
    wrong = {l['agent'] for l in lines if l['agent'] != 'shelf' and l['verdict'] in ('wrong', 'partial')}
    return {'agents': len(wrong), 'of': len(set(agents)), 'which': sorted(wrong)}


def drift_rows(lines: List[dict], shown: int = 4) -> List[dict]:
    """The demo's readback: the agents' rows first, wrong first, then the shelf rows; at most `shown` agent rows."""
    agents = [l for l in lines if l['agent'] != 'shelf'][:shown]
    return agents + [l for l in lines if l['agent'] == 'shelf']


# ─── the master record ───────────────────────────────────────────────────

def _domain(d) -> str:
    return str(d or '').lower().removeprefix('www.')


def _pack_counts(pages: List[dict], label: Optional[str]) -> List[int]:
    """The pack counts the brand page's markup lists for the variant's size."""
    size = attribute_accuracy.size_of(label)
    counts = []
    for page in pages:
        for node in manu._products((page or {}).get('json_ld')):
            words = ' '.join(str(node.get(k) or '') for k in ('name', 'size', 'sku'))
            if size and attribute_accuracy.size_of(str(node.get('size') or words)) != size:
                continue
            m = re.search(r'(\d+)\s*(?:ct|count)\b', words, re.I)
            if m and int(m.group(1)) not in counts:
                counts.append(int(m.group(1)))
    return sorted(counts)


def master_record(variants: List[dict], *, prices: Optional[List[dict]], retailers: List[str],
                  own_domains: Iterable[str], chart) -> List[dict]:
    """The demo's master record, each field {k, v, prov (brand | parleo |
    retail), note}: GTIN with its source, size and weight, pack (with the
    brand page's other counts), price (never set), claims (the brand page's
    bullets, dated), where to buy (the retailers' prices, dated), not in the
    feed (the merchant's retailers the feed does not list for it: no shelf
    read says one does not carry it, so the demo's "Not carried" is not
    claimed), couldn't read."""
    own = {_domain(d) for d in own_domains or () if d}
    domain = next(iter(sorted(own)), None) or 'the brand site'
    rows = [r for v in variants for r in variant_rows(prices, v)]
    own_rows = [r for r in rows if r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own]
    pages = [manu.row_brand_page(r) for r in own_rows if manu.row_brand_page(r)]
    many = len(variants) > 1

    def each(fn):
        parts = [(v, fn(v)) for v in variants]
        return ' · '.join(f"{v.get('label')}: {text}" if many else text for v, text in parts if text)

    out = [{'k': 'GTIN', 'prov': 'brand',
            'v': each(lambda v: T['record.gtin.source'].format(gtin=v['gtin'], source='feed') if v.get('gtin')
                      else T['record.gtin.none'])}]
    if chart:
        out.append({'k': 'Size and weight', 'prov': 'brand',
                    'v': each(lambda v: (weight_of(chart, v.get('label')) if many else
                                         ', '.join(w for w in (attribute_accuracy.size_label(v.get('label')),
                                                               weight_of(chart, v.get('label'))) if w)) or None),
                    'note': f"{domain} size chart"})
    else:
        # 2T-3 (2): no chart for the line on the brand's page: the size alone, never a range from elsewhere
        sizes = list(dict.fromkeys(s for s in (attribute_accuracy.size_label(v.get('label')) for v in variants) if s))
        out.append({'k': 'Size and weight', 'prov': 'brand', 'v': ', '.join(sizes) or None,
                    'note': T['record.weight.none'].format(domain=domain)})
    page_counts = {v.get('variant_id'): _pack_counts(pages, v.get('label')) for v in variants}
    others = [c for v in variants for c in page_counts[v.get('variant_id')] if c != v.get('count')]
    out.append({'k': 'Pack', 'prov': 'brand', 'v': each(lambda v: f"{v['count']} ct" if v.get('count') else None) or None,
                'note': T['record.pack.page'].format(domain=domain, counts=', '.join(f"{c} ct" for c in sorted(set(others))))
                if others else None})
    out.append({'k': 'Price', 'v': T['record.price'], 'prov': 'parleo', 'note': None})
    claim_rows = sorted((r for r in own_rows if r.get('bullets')), key=lambda r: str(r.get('observed_at') or ''),
                        reverse=True)
    if claim_rows:
        out.append({'k': 'Claims', 'v': ', '.join(claim_rows[0]['bullets'][:4]), 'prov': 'brand',
                    'note': T['record.claims.note'].format(domain=domain, day=manu.short_day(claim_rows[0]['observed_at']))})
    shelf = [r for r in rows if r not in own_rows]
    priced = [r for r in shelf if r.get('price') is not None]
    listed = list(dict.fromkeys(d for v in variants for d in v.get('retailers') or [] if _domain(d) not in own))
    if priced:
        day = manu.short_day(max(str(r.get('observed_at') or '') for r in priced))

        def where(v):
            mine = [r for r in variant_rows(priced, v)]
            return ', '.join(dict.fromkeys(f"{rm._retailer_name(_domain(r.get('retailer_domain')))} ${r['price']}"
                                           for r in mine)) or None
        # 2T-3 (8): per variant, "Newborn 84 ct: Amazon $27.97, Walmart $27.97 · Size 1 96 ct: ..."
        parts = [(v, where(v)) for v in variants]
        out.append({'k': f"Where to buy ({day})", 'prov': 'retail',
                    'v': ' · '.join(f"{_variant_short(v)}: {text}" if many else text for v, text in parts if text)})
    elif listed:
        out.append({'k': 'Where to buy', 'prov': 'retail',
                    'v': T['record.where.unread'].format(names=manu._and([rm._retailer_name(_domain(d)) for d in listed]))})
    # no shelf read says a retailer does not carry it: the feed only says which retailers the brand lists
    missing = [d for d in retailers or [] if _domain(d) not in {_domain(x) for x in listed} and _domain(d) not in own]
    if missing:
        out.append({'k': 'Not in the feed', 'v': ', '.join(rm._retailer_name(_domain(d)) for d in missing),
                    'prov': 'brand', 'note': T['record.not_in_feed']})
    reads = shelf_reads(shelf, own)
    walled, unread = reads['walled'], reads['unread']
    cant = [T['record.walled'].format(names=manu._and(walled))] if walled else []
    cant += [T['record.unread'].format(names=manu._and(unread))] if unread else []
    if cant:
        out.append({'k': "Couldn't read", 'v': '. '.join(cant), 'prov': 'parleo'})
    for f in out:
        f.setdefault('note', None)
    return out


# ─── timeline and compiler ───────────────────────────────────────────────

def _channel_short(slug: str, channels: Dict[str, dict]) -> str:
    return SURFACE_SHORT.get(slug) or (channels.get(slug) or {}).get('name') or slug


def timeline(variants: List[dict], rows: Dict[str, dict], *, prices: Optional[List[dict]], own_domains: Iterable[str],
             lines: List[dict], cycle: Optional[dict], channels: Dict[str, dict]) -> List[dict]:
    """The record's history, oldest first, each {at, day, what, tone}: the
    brand page read, the shelf read (walled retailers named), the read back
    (the cycle's answers against the record), the compile and its hold, any
    send the brand stated."""
    own = {_domain(d) for d in own_domains or () if d}
    domain = next(iter(sorted(own)), None) or 'the brand site'
    mine = [r for v in variants for r in variant_rows(prices, v)]
    out = []
    pages = [r for r in mine if (r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own)
             and r.get('observed_at') and manu.row_brand_page(r)]
    if pages:
        newest = max(pages, key=lambda r: str(r['observed_at']))
        page = manu.row_brand_page(newest) or {}
        what = [T[f'timeline.brand_page.what.{k}'] for k, key in (('chart', 'size_chart'), ('claims', 'bullets'),
                                                                   ('markup', 'json_ld')) if page.get(key)]
        out.append({'at': newest['observed_at'], 'what': T['timeline.brand_page'].format(domain=domain,
                                                                                          what=manu._and(what)),
                    'tone': 'neu'})
    reads = shelf_reads(mine, own)
    if reads['read'] or reads['walled'] or reads['unread']:
        read, walled, unread = reads['read'], reads['walled'], reads['unread']
        parts = ([T['timeline.shelf.read'].format(names=manu._and(read))] if read else []) + \
            ([T['timeline.shelf.walled'].format(names=manu._and(walled))] if walled else []) + \
            ([T['timeline.shelf.unread'].format(names=manu._and(unread))] if unread else [])
        out.append({'at': reads['at'], 'what': T['timeline.shelf'].format(read='. '.join(parts)),
                    'tone': 'warn' if walled or unread else 'ok'})
    if cycle is not None and lines:
        parts = []
        for fact, key in (('weight', 'weight'), ('price', 'price')):
            mine_l = [l for l in lines if l['fact'] == fact]
            if mine_l:
                parts.append(T[f'timeline.readback.{key}'].format(k=sum(1 for l in mine_l if l['verdict'] == 'right'),
                                                                  n=len(mine_l)))
        deals = [l for l in lines if l['fact'] == 'deal']
        if deals:
            parts.append(T['timeline.readback.deals'].format(k=sum(l['named'] for l in deals),
                                                             n=sum(l['asked'] for l in deals)))
        wrong = any(l['verdict'] in ('wrong', 'partial') for l in lines if l['agent'] != 'shelf')
        out.append({'at': rm._iso(cycle.get('start_date')), 'what': T['timeline.readback'].format(parts=', '.join(parts)),
                    'tone': 'bad' if wrong else 'ok', 'cycle': cycle.get('cycle_code')})
    compiled = [e for r in rows.values() for e in r.get('journal') or [] if e.get('event') == 'compiled']
    if compiled:
        held = [s for s, r in rows.items() if manu.is_held(r)]
        blocked = [s for s, r in rows.items() if manu.is_blocked(r)]
        live = [s for s, r in rows.items() if cell_state(r) == 'live']
        out.append({'at': max(str(e.get('at') or '') for e in compiled),
                    'what': T['timeline.compiled.live' if live else 'timeline.compiled'].format(
                        live=manu._and([_channel_short(s, channels) for s in live]),
                        held=manu._and([_channel_short(s, channels) for s in held]) or 'no surface',
                        blocked=T['timeline.compiled.blocked'].format(
                            blocked=manu._and([_channel_short(s, channels) for s in blocked])) if blocked else ''),
                    'tone': 'blue'})
    for e in manu.journal(rows.values()):
        if e.get('event') == manu.SENT:
            out.append({'at': e.get('sent_at') or e.get('at'), 'what': T['timeline.sent'].format(
                who=e.get('stated_by') or 'The brand', channel=_channel_short(e.get('channel'), channels)), 'tone': 'ok'})
    out = [e for e in out if e.get('at')]
    out.sort(key=lambda e: str(e['at']))
    for e in out:
        e['day'] = manu.short_day(e['at'])
    return out


def rules_line(relevant: List[str], applied: List[str]) -> Optional[str]:
    """"r1, r2, r5 apply, none on"."""
    if not relevant:
        return None
    on = T['compiler.rules.none_on'] if not applied else T['compiler.rules.all_on'] if len(applied) == len(relevant) \
        else T['compiler.rules.some_on'].format(codes=manu._and(applied))
    return T['compiler.rules'].format(rules=', '.join(relevant), verb='applies' if len(relevant) == 1 else 'apply', on=on)


def compiler(rows: Dict[str, dict], channels: Dict[str, dict], rules: Optional[List[dict]] = None,
             retired: bool = False) -> List[dict]:
    """Per surface the record was compiled for: its spec version, the
    one-line rule, the compliance rules, and the validator's and the
    expressiveness check's lines, each {mark (carried | info | approximated |
    conflict | dropped), field, note}.

    2T-3 (6): `rules_relevant` the rules that apply to the surface (a rule
    that is off says so in the compile's flags; one that is on, from
    /rules, by CHANNEL_RULES), `rules_applied` those that are on, and
    `rules_line` both in one: "r1, r2, r5 apply, none on"."""
    on = {r.get('code') for r in rules or [] if r.get('on')}
    out = []
    for slug, row in rows.items():
        spec = (channels.get(slug) or {}).get('spec_version') or row.get('spec_version')
        lines, off = [], []
        validation = row.get('validation') or {}
        carried = manu.carried_fields(row.get('payload'))
        if manu.is_valid(row) and carried:
            lines.append({'mark': 'carried', 'field': ', '.join(carried), 'note': T['compiler.carried'].format(spec=spec)})
        for err in validation.get('errors') or ([row['error']] if row.get('error') else []):
            lines.append({'mark': 'conflict', 'field': 'validation', 'note': str(err)})
        for e in row.get('expressiveness') or []:
            flag = RULE_FLAG.match(str(e.get('field') or ''))
            if flag:
                off.append(flag.group(1))
                continue
            lines.append({'mark': MARKS.get(e.get('severity'), 'info'), 'field': e.get('field'), 'note': e.get('note')})
        applies = [c for c in CHANNEL_RULES.get(slug, ()) if c in on and (c != 'r6' or retired)]
        relevant = sorted(set(off) | set(applies), key=lambda c: int(c[1:]))
        applied = [c for c in relevant if c in on and c not in off]
        out.append({'channel': slug, 'name': _channel_short(slug, channels), 'spec_version': spec,
                    'rule': T.get(f'compiler.rule.{slug}'), 'rules_relevant': relevant, 'rules_applied': applied,
                    'rules_line': rules_line(relevant, applied), 'state': cell_state(row),
                    'spec_clause': row.get('spec_clause'), 'lines': lines})
    return out


# ─── the page ────────────────────────────────────────────────────────────

def build_records(*, pubs: List[dict], catalog: Optional[dict], feed_rows: Optional[List[dict]],
                  prices: Optional[List[dict]], retailers: List[str], own_domains: Iterable[str],
                  channels: List[dict], brand: Optional[str], cycle: Optional[dict], attribute_answers: List[dict],
                  true_value_rows: List[dict], promo: Optional[dict], deals: Optional[dict],
                  agents: Iterable[str], rules: Optional[List[dict]] = None,
                  channel_states: Optional[List[dict]] = None) -> List[dict]:
    """The matrix, one row per held record (supply's record_ref): {record_ref,
    name, sub, variants, retired, successor, disagree, cells: {channel: {s,
    disagree, at, publication_id, note}}, record, drift, drift_all, timeline,
    compiler}. 2U-2: cells on every channel of `channel_states`
    (channel_list), a channel with no row for the record taking the
    channel's state (next, not_for_brand; na when not compiled) and its line
    as the note; without it, the channels in this pass only."""
    by_slug = _channel_names(channels)
    slugs = pass_channels(pubs)
    listed = {c['channel']: c for c in channel_states or []}
    columns = list(listed) if channel_states is not None else slugs
    agents = list(agents)
    out = []
    for ref, rows in hold(pubs).items():
        variants = record_variants(ref, catalog, feed_rows)
        chart = record_chart(prices, variants, own_domains=own_domains, brand=brand)
        lines = readback(variants, attribute_answers=attribute_answers, true_value_rows=true_value_rows, promo=promo,
                         deals=deals, brand=brand, charted=chart is not None)
        dis = disagree(lines, agents)
        retired = next((v for v in variants if v.get('status') == 'retired'), None)
        listing = _listing(catalog, ref) or {}
        cells = {}
        for slug in columns:
            row = rows.get(slug)
            state = cell_state(row)
            channel = listed.get(slug)
            if row is None and channel is not None and channel['state'] in ('next', 'not_for_brand'):
                cells[slug] = {'s': channel['state'], 'disagree': None, 'at': None, 'publication_id': None,
                               'note': channel['line']}
                continue
            cells[slug] = {'s': state, 'disagree': dis['agents'] if state != 'na' else None,
                           'at': (row or {}).get('compiled_at'), 'publication_id': (row or {}).get('id'),
                           'note': (row or {}).get('spec_clause') if state == 'blocked' else
                           next(iter((row or {}).get('validation', {}).get('errors') or []), None)}
            if state == 'held' and (row or {}).get('sku_rows'):
                every = row['sku_rows']
                cells[slug]['note'] = T['cell.skus'].format(n=sum(1 for x in every if manu.is_held(x)), of=len(every))
        out.append({
            'record_ref': ref, 'sku': ref, 'name': listing.get('title') or (variants[0]['product_name'] if variants else ref),
            'brand': listing.get('brand') or brand, 'sub': subtitle(variants, chart),
            'variants': [{k: v.get(k) for k in ('variant_id', 'label', 'count', 'gtin', 'sku', 'status')}
                         | {'weight': weight_of(chart, v.get('label'))} for v in variants],
            'retired': retired is not None,
            'successor': ((retired or {}).get('successor') or {}).get('product_name') if retired else None,
            'disagree': dis, 'cells': cells,
            'record': master_record(variants, prices=prices, retailers=retailers, own_domains=own_domains, chart=chart),
            'drift': drift_rows(lines), 'drift_all': lines,
            'timeline': timeline(variants, rows, prices=prices, own_domains=own_domains, lines=lines, cycle=cycle,
                                 channels=by_slug),
            # the MCP server's row is a serve check, not a compile: no compiler panel of its own
            'compiler': compiler({k: v for k, v in rows.items() if k not in PARLEO_PUBLISHED}, by_slug, rules,
                                 retired=retired is not None),
        })
    return out


def _fields(per_record: Iterable[Dict[str, dict]]) -> dict:
    """{carried, approximated, dropped}: 2T-3 (7), the distinct fields of each
    record across its held (or published) channels, summed over records, so
    the three are on one scale. A field is carried when any held channel's
    payload carries it, else approximated when one approximates it, else
    dropped when one drops it by spec. A rule's flag, an info line and a
    blocked channel's lines are not fields."""
    counts = {'carried': 0, 'approximated': 0, 'dropped': 0}
    for rows in per_record:
        held = [r for r in rows.values() if manu.is_held(r) or r.get('status') == manu.LIVE_STATUS]
        carried = {f for r in held for f in manu.carried_fields(r.get('payload'))}
        marks = [(e.get('field'), e.get('severity')) for r in held for e in r.get('expressiveness') or []
                 if e.get('field') and not RULE_FLAG.match(str(e['field']))]
        approximated = {f for f, sev in marks if sev == 'approximated'} - carried
        dropped = {f for f, sev in marks if sev in ('dropped', 'blocked')} - carried - approximated
        counts['carried'] += len(carried)
        counts['approximated'] += len(approximated)
        counts['dropped'] += len(dropped)
    return counts


def build_workspace(*, pubs: List[dict], records: List[dict], prices: Optional[List[dict]],
                    own_domains: Iterable[str], brand: Optional[str], domain: Optional[str],
                    channel_states: Optional[List[dict]] = None) -> dict:
    """The demo's "This workspace today": records, compiled of total (the
    hold's held or published cells over records x channels in this pass),
    published, fields carried / approximated / dropped, products where
    agents disagree, retailer sites walled, last verified (the newest
    reference read), next check (no schedule exists: None). 2U-2:
    `surfaces` is `channel_states` (channel_list, every channel with its
    state and line) when given, and `channels` counts them by state."""
    rows = [r for per in hold(pubs).values() for r in per.values()]
    slugs = pass_channels(pubs)
    own = {_domain(d) for d in own_domains or () if d}
    shelf = [r for r in prices or [] if r.get('role') != 'own' and _domain(r.get('retailer_domain')) not in own]
    names = shelf_reads(shelf, own)['walled']
    walled = sorted({_domain(r.get('retailer_domain')) for r in shelf
                     if rm._retailer_name(_domain(r.get('retailer_domain'))) in names})
    verified = max((str(r['observed_at']) for r in prices or [] if r.get('observed_at')), default=None)
    per_surface = []
    for slug in slugs:
        cells = [rec['cells'][slug]['s'] for rec in records]
        per_surface.append({'channel': slug, 'name': SURFACE_SHORT.get(slug, slug),
                            'compiled': sum(1 for s in cells if s in ('held', 'published')), 'of': len(records),
                            'blocked': sum(1 for s in cells if s == 'blocked')})
    for s in per_surface:
        s['line'] = f"{s['compiled']} of {s['of']} compiled"
    if channel_states is not None:
        per_surface = [dict(c) for c in channel_states]
    return {
        'records': len(records),
        'compiled': {'n': sum(1 for r in rows if manu.is_held(r) or r.get('status') == manu.LIVE_STATUS),
                     'of': len(records) * len(slugs)},
        'published': sum(1 for r in rows if r.get('status') == manu.LIVE_STATUS),
        'live': sum(1 for r in rows if cell_state(r) == 'live'),
        'blocked': sum(1 for r in rows if manu.is_blocked(r)),
        'channels': {state: sum(1 for c in channel_states or [] if c['state'] == state) for state in CHANNEL_STATES}
        if channel_states is not None else None,
        'fields': _fields(hold(pubs).values()),
        'disagree': sum(1 for rec in records if rec['disagree']['agents']),
        'walled': {'n': len(walled), 'domains': walled},
        'last_verified': verified, 'last_verified_day': manu.short_day(verified),
        'next_check': None,
        'surfaces': per_surface,
        'mode_note': T['workspace.mode_note'].format(domain=domain or 'the brand site',
                                                     brand_s=possessive(brand or 'the brand')),
    }


def _compiles(pubs: List[dict]) -> List[dict]:
    """One per compile-and-hold, oldest first: the distinct compiled_at of
    the merchant's rows, each with who pressed it (its rows' `compiled`
    journal entry) and its rows."""
    by_at: Dict[str, List[dict]] = {}
    for p in pubs or []:
        if p.get('compiled_at'):
            by_at.setdefault(str(p['compiled_at']), []).append(p)
    out = []
    for at in sorted(by_at):
        rows = by_at[at]
        who = next((e.get('by') for r in rows for e in r.get('journal') or [] if e.get('event') == 'compiled'), None)
        out.append({'compiled_at': at, 'by': who, 'rows': rows})
    return out


def build_release(*, pubs: List[dict], records: List[dict], channels: List[dict], rules: Optional[List[dict]],
                  name: str, brand: Optional[str], channel_states: Optional[List[dict]] = None) -> Optional[dict]:
    """The newest compile-and-hold as the current release: {name, compiled_at,
    rules_on: {on, of}, products, surfaces, approved_by (None: no approval is
    recorded for a compile), requested (who pressed compile, from the
    journal), status, surfaces[] with each spec version, notes}. 2U-2:
    with `channel_states` (channel_list), surfaces[] is every channel in
    supply's order, its status the channel's state and line, and `state`."""
    compiles = _compiles(pubs)
    if not compiles:
        return None
    newest = compiles[-1]
    by_slug = _channel_names(channels)
    slugs = pass_channels(pubs)
    day = manu.short_day(newest['compiled_at'])
    sent = manu.first_sent(pubs)
    surfaces = []
    for c in sorted((c for c in channels or [] if c.get('is_active', True) and c.get('slug') not in SELLER_ONLY),
                    key=lambda c: SURFACE_ORDER.index(c['slug']) if c.get('slug') in SURFACE_ORDER else 99):
        slug = c['slug']
        states = [rec['cells'][slug]['s'] for rec in records] if slug in slugs else []
        if 'published' in states:
            status = T['release.surface.published'].format(day=day)
        elif 'held' in states:
            status = T['release.surface.held'].format(day=day)
        elif 'blocked' in states:
            status = T['release.surface.blocked'].format(day=day)
        else:
            status = T['release.surface.out']
        surfaces.append({'channel': slug, 'name': SURFACE_SHORT.get(slug, c.get('name')),
                         'spec_version': c.get('spec_version'), 'status': status, 'in_pass': slug in slugs})
    if channel_states is not None:
        surfaces = [{'channel': c['channel'], 'name': c['name'], 'spec_version': (by_slug.get(c['channel']) or {}).get(
                         'spec_version'), 'status': release_status(c, day), 'state': c['state'],
                     'in_pass': c['in_pass']} for c in channel_states]
    count = len(records)
    return {
        'name': T['release.name'].format(count=manu._NUMBER_WORDS.get(count, str(count))),
        'named': False,
        'compiled_at': newest['compiled_at'], 'day': day,
        'rules_on': {'on': sum(1 for r in rules or [] if r.get('on')), 'of': len(rules or [])} if rules is not None
        else None,
        'products': count, 'surfaces_held': sum(1 for s in slugs if any(rec['cells'][s]['s'] == 'held' for rec in records)),
        'approved_by': None, 'requested': newest['by'],
        'status': T['release.status.sent'].format(who=sent.get('stated_by')) if sent else T['release.status.held'],
        'surfaces': surfaces,
        'notes': [T['release.note.account'].format(name_s=possessive(name)),
                  T['release.note.verify'].format(n=count)],
        'channels': {s: (by_slug.get(s) or {}).get('spec_version') for s in slugs},
    }


def release_status(channel: dict, day: Optional[str]) -> str:
    """The release card's words for one channel of channel_list."""
    state = channel['state']
    if state == 'held':
        return T['release.surface.held'].format(day=day)
    if state == 'blocked' and channel.get('rule'):
        return T['release.surface.blocked.rule'].format(rule=channel['rule'], day=day)
    if state == 'blocked':
        return T['release.surface.blocked'].format(day=day)
    if state == 'live' and channel.get('check') in ('not_reachable', 'not_served'):
        return T[f"release.surface.{channel['check']}"].format(line=channel['line'])
    if state in ('live', 'next', 'not_for_brand'):
        return T[f'release.surface.{state}'].format(line=channel['line'])
    return T['release.surface.out']


def build_releases(*, pubs: List[dict], feed_version: Optional[dict], rules: Optional[List[dict]]) -> List[dict]:
    """One per compile-and-hold, newest first: {version, compiled_at, day,
    what_changed, status, approvals, verification, requested}. The feed
    version is known for the newest compile only (supply serves the current
    one). No roll back in this pass."""
    compiles = _compiles(pubs)
    sent = manu.first_sent(pubs)
    out = []
    for i, c in enumerate(compiles):
        newest = i == len(compiles) - 1
        feed = (feed_version or {}).get('version_number') if newest else None
        changed = (T['releases.first'] if i == 0 else T['releases.changed']).format(feed=feed) if feed is not None \
            else T['releases.feed_unknown']
        if i > 0:
            since, until = compiles[i - 1]['compiled_at'], c['compiled_at']
            n = sum(1 for r in rules or [] for h in r.get('history') or []
                    if since < str(h.get('at') or '') <= until)
            if n:
                changed += '. ' + T['releases.rules'].format(n=n, changes='change' if n == 1 else 'changes')
        status = (T['release.status.sent'].format(who=sent.get('stated_by')) if sent else T['release.status.held']) \
            if newest else T['releases.superseded']
        out.append({'version': f"v{i + 1}", 'compiled_at': c['compiled_at'], 'day': manu.short_day(c['compiled_at']),
                    'what_changed': changed, 'status': status, 'approvals': T['releases.approvals'],
                    'verification': T['releases.verify'], 'requested': c['by'], 'current': newest,
                    'rows': len(c['rows'])})
    return list(reversed(out))


def build_destinations(*, pubs: List[dict], all_pubs: List[dict], merchants: List[dict], slug: str, name: str,
                       brand: Optional[str], domain: Optional[str], channels: List[dict]) -> List[dict]:
    """Where the record goes. Step 1, the Manufacturer Center file: compiled
    from, validated against, who sends it. Step 2 only when another merchant
    of the tenant has compiled records not yet sent (supply has no plan
    record, so its date is not served); absent otherwise."""
    mc = manu.latest_by_record(pubs, 'manufacturer_center')
    if not mc:
        return []
    by_slug = _channel_names(channels)
    compiled = max(str(r.get('compiled_at') or '') for r in mc)
    sent = (manu.first_sent(pubs) or {}) if any(e.get('event') == manu.SENT for r in mc for e in r.get('journal') or []) \
        else {}
    said = {'name': name, 'name_s': possessive(name), 'brand': brand or name, 'domain': domain or 'the brand site'}
    out = [{'step': 1, 'channel': 'manufacturer_center',
            'title': T['destination.mc.title'].format(**said),
            'facts': [{'k': 'Compiled from', 'v': T['destination.mc.from'].format(**said, day=manu.short_day(compiled))},
                      {'k': 'Validated against', 'v': T['destination.mc.against'].format(
                          spec=(by_slug.get('manufacturer_center') or {}).get('spec_version'))},
                      {'k': 'Who sends', 'v': T['destination.mc.who'].format(**said)}],
            'status': {'label': T['destination.mc.status.sent'].format(name=sent.get('stated_by'),
                                                                      day=manu.short_day(sent.get('sent_at')))
                       if sent else T['destination.mc.status'].format(name=name), 'tone': 'ok' if sent else 'blue'},
            'line': T['destination.mc.line'].format(**said)}]
    for m in merchants or []:
        if m.get('slug') == slug:
            continue
        theirs = [p for p in all_pubs or [] if str(p.get('record_ref') or '').startswith(f"feed:{m.get('slug')}:")
                  or p.get('merchant_slug') == m.get('slug')]
        waiting = [p for p in theirs if p.get('status') == manu.HELD_STATUS]
        if not waiting:
            continue
        newest = max(waiting, key=lambda p: str(p.get('compiled_at') or ''))
        out.append({'step': 2, 'merchant': m.get('slug'), 'channel': newest.get('channel_slug') or newest.get('channel'),
                    'title': T['destination.other.title'].format(name=m.get('name') or m.get('slug')),
                    'facts': [{'k': 'Brand', 'v': m.get('name') or m.get('slug')},
                              {'k': 'Destination', 'v': _channel_short(newest.get('channel_slug') or newest.get('channel'),
                                                                       by_slug)}],
                    'status': {'label': T['destination.other.status'], 'tone': 'neu',
                               'day': manu.short_day(newest.get('compiled_at'))},
                    'planned_on': None,
                    'line': T['destination.other.line'].format(name=m.get('name') or m.get('slug'),
                                                               brand_s=possessive(brand or name))})
        break
    return out
