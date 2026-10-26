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
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_read_models as rm
from soa_shared import attribute_accuracy, surfaces
from soa_shared import promo_pass_through as ppt
from soa_shared.possessive import possessive

#: The cell vocabulary in manufacturer mode: a held row, a published one, a
#: blocked one, and a channel the record was not compiled for.
CELL_STATES = ('held', 'published', 'blocked', 'na')

#: Channels a manufacturer's record never goes to: a seller's (Merchant
#: Center takes offers, the deal directory a seller's deals). WebMCP is not
#: listed: supply has no such channel.
SELLER_ONLY = ('merchant_center', 'deal_directory')

#: The order the demo lists the brand's surfaces in (BRAND_CHANNELS).
SURFACE_ORDER = ('schema_org', 'manufacturer_center', 'acp', 'ucp_uip', 'deals_api', 'mcp')

#: The demo's names for the surfaces, short.
SURFACE_SHORT = {'schema_org': 'Site markup', 'manufacturer_center': 'Manufacturer Center', 'acp': 'ACP feed',
                 'ucp_uip': 'UCP', 'deals_api': 'Deals API', 'mcp': 'MCP server'}

#: supply's expressiveness severity -> the compiler line's mark.
MARKS = {'info': 'info', 'dropped': 'dropped', 'approximated': 'approximated', 'blocked': 'conflict'}

#: The rules a compile applied are journaled as expressiveness lines named so.
RULE_FLAG = re.compile(r'^rule_(r\d+)$')

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
    'timeline.sent': '{who} says it sent the {channel} file',
    'compiler.carried': 'Validated against {spec}',
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


def hold(pubs: List[dict]) -> Dict[str, Dict[str, dict]]:
    """{record_ref: {channel: its newest row}} over the merchant's rows,
    records in the order supply first compiled them."""
    out: Dict[str, Dict[str, dict]] = {}
    for channel in pass_channels(pubs):
        for row in manu.latest_by_record(pubs, channel):
            out.setdefault(row.get('record_ref') or str(row.get('listing_id')), {})[channel] = row
    return dict(sorted(out.items(), key=lambda kv: min(r.get('id') or 0 for r in kv[1].values())))


def cell_state(row: Optional[dict]) -> str:
    if row is None:
        return 'na'
    if row.get('status') == manu.LIVE_STATUS:
        return 'published'
    if manu.is_blocked(row):
        return 'blocked'
    if manu.is_held(row):
        return 'held'
    return 'na'


def _channel_names(channels: List[dict]) -> Dict[str, dict]:
    return {c.get('slug'): c for c in channels or []}


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


def record_variants(record_ref: str, catalog: Optional[dict], feed_rows: Optional[List[dict]]) -> List[dict]:
    """The held record's variants: the catalog listing whose product_id is
    the record_ref, each with its feed row. [{variant_id, label, count, gtin,
    sku, status, successor, product_name, retailers, feed}]."""
    listing = _listing(catalog, record_ref) or {}
    out = []
    for v in listing.get('variants') or []:
        row = _feed_row(feed_rows or [], v) or {}
        out.append({'variant_id': v.get('variant_id'), 'label': v.get('title') or row.get('variant_label'),
                    'count': v.get('count') if v.get('count') is not None else row.get('pack_count'),
                    'gtin': v.get('gtin') or row.get('gtin'), 'sku': row.get('sku'), 'status': v.get('status'),
                    'successor': v.get('successor'),
                    'product_name': row.get('product_name') or listing.get('title'),
                    'retailers': [r.get('domain') for r in row.get('retailers') or [] if r.get('domain')],
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


def record_chart(prices: Optional[List[dict]], variants: List[dict]) -> Optional[List[dict]]:
    """The line's size chart: the one the brand page served on any of the
    record's own rows (2O-6's size_chart), newest read first."""
    rows = [r for v in variants for r in variant_rows(prices, v) if r.get('size_chart')]
    rows.sort(key=lambda r: str(r.get('observed_at') or ''), reverse=True)
    return rows[0]['size_chart'] if rows else None


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
             promo: Optional[dict], deals: Optional[dict], brand: Optional[str]) -> List[dict]:
    """Every fact an agent stated about the record's variants in the cycle,
    against the record: weight (the attribute answers), price (the True
    Value quotes, against the retailer's live price), and one shelf row per
    deal live on the record's variants with how many answers named it.
    [{agent, fact, variant, said, truth, verdict (right | partial | wrong |
    missed), run}], wrong first."""
    out = []
    for a in attribute_answers or []:
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
                out.append({'agent': q.get('agent'), 'fact': 'price', 'variant': v.get('label'),
                            'said': f"{name} ${q['stated']}",
                            'truth': f"{name} {cell['live']}" if cell.get('live') else None,
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
                    'said': ppt.title(deal), 'truth': T['drift.shelf.truth'].format(named=named, asked=len(judged)),
                    'verdict': 'right' if named else 'missed', 'run': None, 'surface': None,
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
    out.append({'k': 'Size and weight', 'prov': 'brand',
                'v': each(lambda v: (weight_of(chart, v.get('label')) if many else
                                     ', '.join(w for w in (attribute_accuracy.size_label(v.get('label')),
                                                           weight_of(chart, v.get('label'))) if w)) or None),
                'note': f"{domain} size chart" if chart else None})
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
        out.append({'k': f"Where to buy ({day})", 'prov': 'retail',
                    'v': ' · '.join(f"{rm._retailer_name(_domain(r.get('retailer_domain')))} ${r['price']}" for r in priced)})
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
        out.append({'at': max(str(e.get('at') or '') for e in compiled),
                    'what': T['timeline.compiled'].format(
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


def compiler(rows: Dict[str, dict], channels: Dict[str, dict]) -> List[dict]:
    """Per surface the record was compiled for: its spec version, the
    one-line rule, the compliance rules the compile applied, and the
    validator's and the expressiveness check's lines, each {mark (carried |
    info | approximated | conflict | dropped), field, note}."""
    out = []
    for slug, row in rows.items():
        spec = (channels.get(slug) or {}).get('spec_version') or row.get('spec_version')
        lines, applied = [], []
        validation = row.get('validation') or {}
        carried = manu.carried_fields(row.get('payload'))
        if manu.is_valid(row) and carried:
            lines.append({'mark': 'carried', 'field': ', '.join(carried), 'note': T['compiler.carried'].format(spec=spec)})
        for err in validation.get('errors') or ([row['error']] if row.get('error') else []):
            lines.append({'mark': 'conflict', 'field': 'validation', 'note': str(err)})
        for e in row.get('expressiveness') or []:
            flag = RULE_FLAG.match(str(e.get('field') or ''))
            if flag:
                applied.append(flag.group(1))
                continue
            lines.append({'mark': MARKS.get(e.get('severity'), 'info'), 'field': e.get('field'), 'note': e.get('note')})
        out.append({'channel': slug, 'name': _channel_short(slug, channels), 'spec_version': spec,
                    'rule': T.get(f'compiler.rule.{slug}'), 'rules_applied': applied, 'state': cell_state(row),
                    'spec_clause': row.get('spec_clause'), 'lines': lines})
    return out


# ─── the page ────────────────────────────────────────────────────────────

def build_records(*, pubs: List[dict], catalog: Optional[dict], feed_rows: Optional[List[dict]],
                  prices: Optional[List[dict]], retailers: List[str], own_domains: Iterable[str],
                  channels: List[dict], brand: Optional[str], cycle: Optional[dict], attribute_answers: List[dict],
                  true_value_rows: List[dict], promo: Optional[dict], deals: Optional[dict],
                  agents: Iterable[str]) -> List[dict]:
    """The matrix, one row per held record (supply's record_ref), cells for
    the channels in this pass only: {record_ref, name, sub, variants,
    retired, successor, disagree, cells: {channel: {s, disagree, at,
    publication_id, note}}, record, drift, drift_all, timeline, compiler}."""
    by_slug = _channel_names(channels)
    slugs = pass_channels(pubs)
    agents = list(agents)
    out = []
    for ref, rows in hold(pubs).items():
        variants = record_variants(ref, catalog, feed_rows)
        chart = record_chart(prices, variants)
        lines = readback(variants, attribute_answers=attribute_answers, true_value_rows=true_value_rows, promo=promo,
                         deals=deals, brand=brand)
        dis = disagree(lines, agents)
        retired = next((v for v in variants if v.get('status') == 'retired'), None)
        listing = _listing(catalog, ref) or {}
        cells = {}
        for slug in slugs:
            row = rows.get(slug)
            state = cell_state(row)
            cells[slug] = {'s': state, 'disagree': dis['agents'] if state != 'na' else None,
                           'at': (row or {}).get('compiled_at'), 'publication_id': (row or {}).get('id'),
                           'note': (row or {}).get('spec_clause') if state == 'blocked' else
                           next(iter((row or {}).get('validation', {}).get('errors') or []), None)}
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
            'compiler': compiler(rows, by_slug),
        })
    return out


def _fields(rows: Iterable[dict]) -> dict:
    """{carried, approximated, dropped} over the rows' expressiveness lines
    (a rule the compile applied is not a field)."""
    counts = {'carried': 0, 'approximated': 0, 'dropped': 0}
    for row in rows:
        for e in row.get('expressiveness') or []:
            if RULE_FLAG.match(str(e.get('field') or '')):
                continue
            sev = e.get('severity')
            key = 'carried' if sev == 'info' else 'approximated' if sev == 'approximated' else 'dropped'
            counts[key] += 1
    return counts


def build_workspace(*, pubs: List[dict], records: List[dict], prices: Optional[List[dict]],
                    own_domains: Iterable[str], brand: Optional[str], domain: Optional[str]) -> dict:
    """The demo's "This workspace today": records, compiled of total (the
    hold's held or published cells over records x channels in this pass),
    published, fields carried / approximated / dropped, products where
    agents disagree, retailer sites walled, last verified (the newest
    reference read), next check (no schedule exists: None)."""
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
    return {
        'records': len(records),
        'compiled': {'n': sum(1 for r in rows if manu.is_held(r) or r.get('status') == manu.LIVE_STATUS),
                     'of': len(records) * len(slugs)},
        'published': sum(1 for r in rows if r.get('status') == manu.LIVE_STATUS),
        'blocked': sum(1 for r in rows if manu.is_blocked(r)),
        'fields': _fields(rows),
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
                  name: str, brand: Optional[str]) -> Optional[dict]:
    """The newest compile-and-hold as the current release: {name, compiled_at,
    rules_on: {on, of}, products, surfaces, approved_by (None: no approval is
    recorded for a compile), requested (who pressed compile, from the
    journal), status, surfaces[] with each spec version, notes}."""
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
