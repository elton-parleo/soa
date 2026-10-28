"""
2R-2: manufacturer mode, a brand at retail. The read models behind the
console's TrueSync, Rules, Publishing and Impact screens when supply says the
merchant's `mode` is `manufacturer` (supply 2R-1, parleo-supply-app#33,
docs/truesync/manufacturer-mode.md there).

A manufacturer never sets a price and Parleo never writes into its accounts:
supply compiles the brand's records from its SKU feed and HOLDS them (status
`compiled_not_published`, reason `held_for_merchant`, or `blocked` where the
channel's spec cannot take the record); the brand's own team sends the file.
So nothing here is a publish state Parleo caused, and "sent" is a fact the
brand states (`sent_by_merchant` in supply's journal), never one soa observed.

Every state is derived from supply's rows and the cycles' answers. The rules'
own words (name, detail, scope, audience, outcome) are supply's; soa's copy,
MANUFACTURER_TEMPLATES, is only what soa derives: the surface notes, the
backtest notes and Impact's locked block. The router
(app/routers/console_manufacturer.py) does the reads; these are the pure
builders. Shapes: docs/console-read-models.md, "2R-2". Deterministic; no model.
"""
import re
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from app.services import console_days
from app.services import console_read_models as rm
from soa_shared import attribute_accuracy, retailers as retailer_names
from soa_shared.possessive import possessive

MANUFACTURER = 'manufacturer'

#: supply's publication status for every row of a hold; its `reason` says which kind.
HELD_STATUS = 'compiled_not_published'
HELD_REASON = 'held_for_merchant'
BLOCKED_REASON = 'blocked'
LIVE_STATUS = 'published'

#: supply's publication journal (`journal[]` on each row), the events soa reads.
JOURNAL_EVENTS = ('compiled', 'held_for_merchant', 'blocked', 'sent_by_merchant')
SENT = 'sent_by_merchant'

#: The channels supply compiles in manufacturer mode (#33: the three).
COMPILED_CHANNELS = ('schema_org', 'manufacturer_center', 'acp')

#: The rule whose approval the brand-funded deals surface waits on.
DEALS_RULE = 'r4'
#: supply's rule approval states, and the console's look for each (the demo's chips).
APPROVAL_STATES = ('needs_approval', 'approved', 'declined')
APPROVAL_LOOK = {'needs_approval': 'needs_legal', 'approved': 'approved', 'declined': 'returned'}

#: The backtest's attribute row: the size rule r5's outcome names.
BACKTEST_SIZE = 'Size 4'

MANUFACTURER_TEMPLATES = {
    'mfc.name': 'Google Manufacturer Center',
    'mfc.last': 'File compiled {day}',
    'mfc.last.sent': 'File compiled {day}, sent {sent}',
    'mfc.note': "The brand's own team sends it. Parleo never writes into its account",
    'mfc.records': '{valid} of {total} valid',
    'mfc.no_image': '{n} with no image yet: the brand page served none',
    'oai.name': 'OpenAI product feed (brand)',
    'oai.last': 'Compiled {day}',
    'oai.note': 'Brand feed, retailer-neutral',
    'markup.name': 'Site markup ({domain})',
    'markup.last': 'Read {day}',
    'markup.drift': '{lines} markup {verb} the wrong {sizes} {weights}',
    'markup.drift.sizes': '{lines} markup {verb} the wrong {weights}',
    'markup.gtin': '{lines} {gtins} {verb} {digits} digits',
    'markup.none': "The markup states the record's weight ranges and GTINs",
    'markup.unread': 'Not read yet',
    'ucp.name': 'UCP profile ({domain})',
    'ucp.last': 'Live, version {version}',
    'ucp.none': 'Not in this pass',
    'coupons.name': 'Brand-funded deals',
    'coupons.last': 'Next release',
    'coupons.fields': 'terms, retailers, end dates',
    'coupons.note.pending': 'Publishes after Legal approves rule 4',
    'coupons.note.approved': 'Legal approved rule 4{on}. Publishes in the next release',
    'coupons.note.declined': 'Legal returned rule 4. It publishes once approved',
    'coupons.note.unread': "Publishes after Legal approves rule 4. Rule 4's approval could not be read",
    'not_compiled': 'Not compiled yet',
    'mcp.name': 'Parleo MCP server',
    'mcp.fields': 'size, pack count, GTIN, weight range, claims, lifecycle, retailers',
    'mcp.note': "Served by get_product_facts on Parleo's own server. Nothing is sent to anyone's account",
    'gmc.name': 'Google Merchant Center',
    'directory.name': 'Deal directory',
    'seller.note': "A seller's channel (rule {rule}): a brand's record goes to Manufacturer Center instead",
    'diff.lifecycle.was': 'sold, per {named} of {of} agents',
    'diff.lifecycle.now': 'retired, successor {successor}',
    'diff.lifecycle.now_none': 'retired',
    'preview.title': '{count} {brand} records, Manufacturer Center first',
    'diff.gtin.zero': '{n} {sizes} {verb} the leading zero',
    'diff.gtin.bad': '{n} {sizes} carry a GTIN that is not one as written',
    'diff.gtin.now.zero': 'leading zero restored',
    'diff.gtin.now.bad': 'the corrected GTIN',
    'preview.title.none': 'No {brand} record compiled yet',
    'preview.note': "Compiled {day} from {name_s} feed and {domain}. {valid}. Held until {name_s} team sends it.",
    'preview.note.blocked': "Compiled {day} from {name_s} feed and {domain}. {valid}, so nothing is ready to send: {error}",
    'preview.note.sent': "Compiled {day} from {name_s} feed and {domain}. {valid}. {name_s} team says it sent it on {sent}.",
    'backtest.attribute': "{size} weight answers giving only the chart's range",
    'backtest.retired': 'Category answers naming {line}',
    'backtest.promo': 'Cheapest-place answers naming a live deal',
    'backtest.attribute.note': '{lines}, {day}',
    'backtest.retired.note': '{successor} named in {k}, {day}',
    'backtest.promo.note': '{deals}, {day}',
    'backtest.not_measured': 'Not measured',
    'backtest.next': 'Next read',
    'backtest.after.unsent': ("After is the first cycle scored after {name_s} team sends the file. A held file changes "
                              "nothing an agent reads, so holding it starts no clock."),
    'backtest.after.waiting': 'After is the first cycle scored after the send on {sent}. None has run yet.',
    'backtest.after.read': 'After is {code} ({day}), the first cycle scored after the send on {sent}.',
    'locked.title': 'Cause shows once {name} publishes the record',
    'locked.text': ("TrueSync can tie a change in these answers to a fix only after {name_s} team publishes the {brand} "
                    "record to Manufacturer Center and {domain}. Until then every figure here is a count of answers "
                    "you can audit."),
    'unlocked.title': 'What moved since the record was sent ({sent})',
    'unlocked.waiting': 'The first cycle scored after {sent} has not run yet. Each figure moves on that read.',
    'unlocked.no_before': 'No cycle was scored before {sent}, so there is nothing to compare against.',
}

T = MANUFACTURER_TEMPLATES

_NUMBER_WORDS = {1: 'One', 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight',
                 9: 'Nine', 10: 'Ten'}


def is_manufacturer(merchant_record: Optional[dict]) -> bool:
    """supply 2R-1: the merchant's `mode` on its /tenant record."""
    return (merchant_record or {}).get('mode') == MANUFACTURER


def short_day(value) -> Optional[str]:
    """"Oct 4" from a date or a stamp, None when there is none. 2U-5 (B3): a stamp's day in the workspace's
    timezone (console_days)."""
    return console_days.short_day(value)


def _and(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


# ─── supply's publications ────────────────────────────────────────────────

def merchant_publications(publications: Iterable[dict], listing_ids: Iterable, slug: str) -> List[dict]:
    """The merchant's publications: a hold's rows are feed records
    (`record_ref` "feed:<slug>:…", no listing), a hosted merchant's are its
    catalog's listings."""
    ids = {i for i in listing_ids if i is not None}
    prefix = f"feed:{slug}:"
    return [p for p in publications or []
            if p.get('listing_id') in ids or str(p.get('record_ref') or '').startswith(prefix)]


def is_held(p: dict) -> bool:
    return p.get('status') == HELD_STATUS and p.get('reason') == HELD_REASON


def is_blocked(p: dict) -> bool:
    return p.get('status') == HELD_STATUS and p.get('reason') == BLOCKED_REASON


def is_valid(p: dict) -> bool:
    validation = p.get('validation') or {}
    return bool(validation.get('ok', not p.get('error')))


def latest_by_record(publications: Iterable[dict], channel: str) -> List[dict]:
    """The newest row per record on `channel` (supply's "held now": per record,
    per channel, the newest row)."""
    best: Dict[object, dict] = {}
    for p in publications or []:
        if (p.get('channel_slug') or p.get('channel')) != channel:
            continue
        key = p.get('record_ref') or p.get('listing_id')
        have = best.get(key)
        if have is None or (rm._ts(p.get('compiled_at')), p.get('id') or 0) > \
                (rm._ts(have.get('compiled_at')), have.get('id') or 0):
            best[key] = p
    return sorted(best.values(), key=lambda p: p.get('id') or 0)


def journal(publications: Iterable[dict]) -> List[dict]:
    """Every journal entry on the rows, each with its row's id and channel,
    oldest first."""
    out = []
    for p in publications or []:
        for e in p.get('journal') or []:
            if isinstance(e, dict) and e.get('event') in JOURNAL_EVENTS:
                out.append({**e, 'publication_id': p.get('id'), 'channel': p.get('channel_slug') or p.get('channel')})
    return sorted(out, key=lambda e: (str(e.get('sent_at') or e.get('at') or ''), e.get('publication_id') or 0))


def sent_facts(publications: Iterable[dict]) -> List[dict]:
    """The brand's statements that it sent a held file, one per (channel,
    sent_at), oldest first: {channel, sent_at, stated_by, by, note, at,
    publication_ids}."""
    out: Dict[tuple, dict] = {}
    for e in journal(publications):
        if e.get('event') != SENT:
            continue
        key = (e.get('channel'), str(e.get('sent_at')))
        fact = out.setdefault(key, {'channel': e.get('channel'), 'sent_at': e.get('sent_at'),
                                    'stated_by': e.get('stated_by'), 'by': e.get('by'), 'note': e.get('note'),
                                    'at': e.get('at'), 'publication_ids': []})
        fact['publication_ids'].append(e.get('publication_id'))
    return sorted(out.values(), key=lambda f: str(f['sent_at']))


def first_sent(publications: Iterable[dict]) -> Optional[dict]:
    """The first send the brand stated, on any channel: the clock starts there."""
    facts = sent_facts(publications)
    return facts[0] if facts else None


def carried_fields(payload) -> List[str]:
    """The field names a compiled payload actually carries: Manufacturer
    Center's products[].attributes, a feed's items[] keys, schema.org's
    variants' keys, else the payload's own keys. In first-seen order."""
    names: List[str] = []

    def add(keys):
        for k in keys:
            if k not in names:
                names.append(k)
    if isinstance(payload, dict):
        products, items, variants = payload.get('products'), payload.get('items'), payload.get('hasVariant')
        if isinstance(products, list) and products:
            for p in products:
                add(((p or {}).get('attributes') or {}).keys() if isinstance(p, dict) else ())
        elif isinstance(items, list) and items:
            for i in items:
                add(i.keys() if isinstance(i, dict) else ())
        elif isinstance(variants, list) and variants:
            for v in variants:
                add(k for k in (v.keys() if isinstance(v, dict) else ()) if not k.startswith('@'))
        else:
            add(k for k in payload.keys() if not str(k).startswith('@'))
    return names


def _flags(p: dict) -> List[str]:
    return [f.get('field') for f in p.get('expressiveness') or [] if isinstance(f, dict)]


def _errors(p: dict) -> List[str]:
    return [str(e) for e in (p.get('validation') or {}).get('errors') or []] or ([p['error']] if p.get('error') else [])


def no_image(p: dict) -> bool:
    """A record with no image yet: the compile took none from the brand page
    (no `image_from_brand_page` flag) and its validator names the image."""
    return 'image_from_brand_page' not in _flags(p) and any('image' in e.lower() for e in _errors(p))


# ─── GTINs ────────────────────────────────────────────────────────────────

def _check_digit_ok(digits: str) -> bool:
    if len(digits) not in (8, 12, 13, 14) or not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def gtin_correction(value) -> Optional[str]:
    """The GTIN `value` should be when as written it is not one (11 digits,
    a lost leading zero): the shortest zero-padded form whose check digit
    holds. None when it is a GTIN as written, or no padding makes it one."""
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits or _check_digit_ok(digits) or len(digits) >= 14:
        return None
    for width in (12, 13, 14):
        if width > len(digits) and _check_digit_ok(digits.zfill(width)):
            return digits.zfill(width)
    return None


def _brand_word(rows: List[dict]) -> Optional[str]:
    firsts = {(v.get('product_name') or '').split(' ')[0] for v in rows if v.get('product_name')}
    return next(iter(firsts)) if len(firsts) == 1 else None


def _line_display(product_name: Optional[str], brand: Optional[str]) -> str:
    """"Pampers Cruisers 360" -> "Cruisers 360": the line as the copy names it."""
    head = re.split(r',|\bsize\b|\|', product_name or '', maxsplit=1, flags=re.I)[0]
    words = [w for w in head.replace('®', ' ').replace('™', ' ').split()
             if w.lower() not in {(brand or '').lower(), 'diapers', 'diaper'}]
    return ' '.join(words) or (product_name or '')


def _field_base(product_name: Optional[str], label: Optional[str], brand: Optional[str]) -> str:
    size = attribute_accuracy.size_label(label)
    return f"{rm.line_of(product_name or label, brand)}.{rm._slug(size or label)}"


#: What supply's retailer-prices row says of a brand's own page (2O-6): served
#: on the row itself, beside its observed_at, not under a `brand_page` key.
BRAND_PAGE_FIELDS = ('json_ld', 'size_chart', 'bullets')


def row_brand_page(row: dict) -> Optional[dict]:
    """The brand page a retailer-prices row carries: its `brand_page`, else
    2O-6's fields on the row ({json_ld, size_chart, bullets}); None when it
    carries neither."""
    page = row.get('brand_page')
    if isinstance(page, dict):
        return page
    fields = {k: row.get(k) for k in BRAND_PAGE_FIELDS}
    return fields if any(v is not None for v in fields.values()) else None


def brand_page_read_at(prices: Optional[List[dict]]) -> Optional[str]:
    """The newest read of a brand page across the merchant's retailer-prices
    rows (its observed_at), None when no row carries one. Supply serves a
    brand page only on its own pages, so no domain is matched here."""
    return max((str(r['observed_at']) for r in prices or [] if r.get('observed_at') and row_brand_page(r)),
               default=None)


def brand_pages(prices: Optional[List[dict]], own_domains: Iterable[str]) -> List[dict]:
    """The brand's own pages supply read (2O-6, row_brand_page on its
    retailer-prices rows), one per page URL, newest read first:
    [{url, observed_at, brand_page}]."""
    own = {str(d).lower().removeprefix('www.') for d in own_domains or () if d}
    seen: Dict[str, dict] = {}
    for r in sorted(prices or [], key=lambda r: str(r.get('observed_at') or ''), reverse=True):
        page = row_brand_page(r)
        domain = str(r.get('retailer_domain') or '').lower().removeprefix('www.')
        if isinstance(page, dict) and (domain in own or r.get('role') == 'own'):
            seen.setdefault(r.get('final_url') or r.get('url') or str(len(seen)),
                            {'url': r.get('final_url') or r.get('url'), 'observed_at': r.get('observed_at'),
                             'brand_page': page})
    return list(seen.values())


def _products(node) -> List[dict]:
    """Every schema.org Product node in a JSON-LD value (a ProductGroup's hasVariant included)."""
    out = []
    if isinstance(node, list):
        for n in node:
            out += _products(n)
    elif isinstance(node, dict):
        kind = node.get('@type')
        if kind == 'Product' or (isinstance(kind, list) and 'Product' in kind):
            out.append(node)
        for key in ('hasVariant', '@graph'):
            out += _products(node.get(key))
    return out


def markup_gtins(pages: List[dict]) -> List[dict]:
    """The GTINs the brand page's markup states (brand_page.json_ld's Product
    nodes, `gtin13` / `gtin12` / `gtin14` / `gtin`): [{line, size, gtin}]."""
    out = []
    for page in pages:
        bp = page.get('brand_page') or {}
        ld = bp.get('json_ld')
        line = bp.get('line') or (ld.get('name') if isinstance(ld, dict) else None)
        for node in _products(bp.get('json_ld')):
            gtin = next((node.get(k) for k in ('gtin13', 'gtin12', 'gtin14', 'gtin') if node.get(k)), None)
            if gtin:
                size = str(node.get('size') or node.get('name') or '')
                out.append({'line': line, 'size': f"Size {size}" if size.isdigit() else size, 'gtin': str(gtin)})
    return out


def gtin_flags(pages: List[dict], feed_rows: Optional[List[dict]] = None, brand: Optional[str] = None) -> List[dict]:
    """GTINs that are not GTINs as written: the brand page markup's
    (json_ld, 2O-6) and the feed's as given. [{field, was, now, prov, kind,
    where, line, digits}]; one per (field, was)."""
    out, seen = [], set()

    def add(field, was, now, where, line):
        if (field, str(was)) in seen:
            return
        seen.add((field, str(was)))
        out.append({'field': field, 'was': str(was), 'now': now, 'prov': 'parleo', 'kind': 'gtin', 'where': where,
                    'line': line, 'digits': len(''.join(ch for ch in str(was) if ch.isdigit()))})
    for g in markup_gtins(pages):
        now = gtin_correction(g['gtin'])
        if now:
            line = _line_display(g['line'], brand)
            add(f"{rm._slug(line)}.{rm._slug(g['size'])}.gtin (markup)", g['gtin'], now, 'markup', line)
    feed_brand = _brand_word(feed_rows or []) or brand
    for row in feed_rows or []:
        was = row.get('gtin')
        now = gtin_correction(was)
        if now:
            add(f"{_field_base(row.get('product_name'), row.get('variant_label'), feed_brand)}.gtin", was, now, 'feed',
                _line_display(row.get('product_name'), feed_brand))
    return out


# ─── the surfaces ─────────────────────────────────────────────────────────

def markup_reason(drift: List[dict], reference: Optional[dict], flags: List[dict]) -> Optional[str]:
    """The site markup surface's reason, from the weight rows whose markup
    disagrees with the chart and the markup's GTIN flags: "Zzz and Cruisers
    360 markup carry the wrong Size 4 and Size 3 weights. AMORE GTIN has 11
    digits". None when neither."""
    by_ref = {v.get('variant_ref'): v for v in (reference or {}).get('attributes') or []}
    brand = _brand_word(list(by_ref.values()))
    pairs: List[tuple] = []
    for row in drift or []:
        if row.get('kind') != 'markup':
            continue
        v = by_ref.get(row.get('variant_ref')) or {}
        pair = (_line_display(v.get('product_name') or v.get('variant_label'), brand),
                attribute_accuracy.size_label(v.get('variant_label')) or v.get('variant_label'))
        if pair not in pairs:
            pairs.append(pair)
    parts = []
    lines = list(dict.fromkeys(line for line, _size in pairs))
    if pairs and len(lines) == len(pairs):
        # one size per line: "Zzz and Cruisers 360 markup carry the wrong Size 4 and Size 3 weights"
        parts.append(T['markup.drift'].format(lines=_and(lines), verb='carry' if len(lines) > 1 else 'carries',
                                              sizes=_and([size for _line, size in pairs]),
                                              weights='weights' if len(pairs) > 1 else 'weight'))
    elif pairs:
        # a line with more than one: each line with its sizes, "Swaddlers Size 4 and Size 5 and Zzz Size 4 ..."
        named = [f"{line} {_and([size for l2, size in pairs if l2 == line])}" for line in lines]
        parts.append(T['markup.drift.sizes'].format(lines=_and(named), verb='carry' if len(pairs) > 1 else 'carries',
                                                    weights='weights' if len(pairs) > 1 else 'weight'))
    marked = [f for f in flags if f.get('where') == 'markup']
    if marked:
        glines = list(dict.fromkeys(f['line'] for f in marked))
        digits = sorted({f['digits'] for f in marked})
        parts.append(T['markup.gtin'].format(lines=_and(glines), gtins='GTINs' if len(marked) > 1 else 'GTIN',
                                             verb='have' if len(marked) > 1 else 'has',
                                             digits=_and([str(d) for d in digits])))
    return '. '.join(parts) or None


def _newest(rows: List[dict], key: str = 'compiled_at') -> Optional[dict]:
    rows = [r for r in rows if r.get(key)]
    return max(rows, key=lambda r: (rm._ts(r.get(key)), r.get('id') or 0)) if rows else None


def _fields_of(rows: List[dict]) -> List[str]:
    fields: List[str] = []
    for p in rows:
        for f in carried_fields(p.get('payload')):
            if f not in fields:
                fields.append(f)
    return fields


#: 2U-2: each channel's Publishing surface id (the five the demo named, and the three 2U-2 adds).
SURFACE_IDS = {'manufacturer_center': 'mfc', 'acp': 'oai', 'schema_org': 'markup', 'ucp_uip': 'ucp',
               'deals_api': 'coupons', 'mcp': 'mcp', 'merchant_center': 'gmc', 'deal_directory': 'directory'}


def build_surfaces(*, pubs: List[dict], channels: List[dict], drift: List[dict], reference: Optional[dict],
                   pages: List[dict], flags: List[dict], own_domain: Optional[str], rules: Optional[List[dict]],
                   held: Optional[dict], read_at: Optional[str] = None,
                   channel_states: Optional[List[dict]] = None) -> List[dict]:
    """The Publishing screen's five surfaces, in the demo's order, each {id,
    name, status, last, fields, note} with the facts it was derived from
    beside. `pubs` are the merchant's rows; `held` supply's /tenant `held`
    (its counts and the newest stated send per channel); `rules` supply's
    rules (None when unread); `pages` the brand pages supply read;
    `read_at` the newest brand-page read (brand_page_read_at), else the
    newest of `pages`. 2U-2: with `channel_states` (console_release.
    channel_list), every channel in supply's order, each carrying the
    list's state, label, line, reason and rule (with_channel_states)."""
    by_slug = {c.get('slug'): c for c in channels or []}
    domain = own_domain or 'the brand site'
    held = held or {}
    sent_on = held.get('sent') or {}
    out = []

    # Manufacturer Center: held only when at least one held record is valid
    mc = latest_by_record(pubs, 'manufacturer_center')
    held_mc = [p for p in mc if is_held(p)]
    valid = [p for p in held_mc if is_valid(p)]
    live = [p for p in mc if p.get('status') == LIVE_STATUS]
    if live:
        status = 'live'
    elif valid:
        status = 'held'
    elif held_mc or any(is_blocked(p) for p in mc):
        status = 'blocked'
    else:
        status = 'not_compiled'
    compiled_at = held.get('compiled_at') or (_newest(held_mc or mc) or {}).get('compiled_at')
    day = short_day(compiled_at)
    sent = sent_on.get('manufacturer_center')
    total = (held.get('by_channel') or {}).get('manufacturer_center', len(held_mc))
    first_error = next((e for p in held_mc if not is_valid(p) for e in _errors(p)), None)
    missing_image = sum(1 for p in held_mc if no_image(p))
    note = first_error if status == 'blocked' and first_error else T['mfc.note']
    if missing_image and status != 'blocked':
        note += '. ' + T['mfc.no_image'].format(n=missing_image)
    if status == 'not_compiled':
        last = T['not_compiled']
    elif sent:
        last = T['mfc.last.sent'].format(day=day, sent=short_day(sent))
    else:
        last = T['mfc.last'].format(day=day)
    out.append({'id': 'mfc', 'name': T['mfc.name'], 'status': status, 'last': last,
                'fields': ', '.join(_fields_of(valid or held_mc)), 'note': note,
                # beside the typed fields
                'channel': 'manufacturer_center', 'connected': (by_slug.get('manufacturer_center') or {}).get('connected'),
                'compiled_at': compiled_at, 'records': T['mfc.records'].format(valid=len(valid), total=total) if total else None,
                'records_total': total, 'records_valid': len(valid), 'errors': [e for p in held_mc for e in _errors(p)],
                'images_from_brand_page': sum(1 for p in held_mc if 'image_from_brand_page' in _flags(p)),
                'no_image': missing_image, 'sent': sent,
                'publication_ids': [p['id'] for p in held_mc if p.get('id') is not None]})

    # the brand's OpenAI (ACP) feed: blocked with supply's clause, never a placeholder price
    acp = latest_by_record(pubs, 'acp')
    blocked = [p for p in acp if is_blocked(p)]
    held_acp = [p for p in acp if is_held(p)]
    if any(p.get('status') == LIVE_STATUS for p in acp):
        status = 'live'
    elif blocked:
        status = 'blocked'
    elif held_acp:
        status = 'held'
    else:
        status = 'not_compiled'
    newest = _newest(acp)
    clause = next((p.get('spec_clause') for p in blocked if p.get('spec_clause')), None)
    out.append({'id': 'oai', 'name': T['oai.name'], 'status': status,
                'last': T['not_compiled'] if status == 'not_compiled' else
                T['oai.last'].format(day=short_day((newest or {}).get('compiled_at'))),
                'fields': ', '.join(_fields_of(held_acp or acp)),
                'note': clause if status == 'blocked' and clause else T['oai.note'],
                'channel': 'acp', 'compiled_at': (newest or {}).get('compiled_at'), 'spec_clause': clause,
                'records_total': (held.get('by_channel') or {}).get('acp', len(acp)), 'blocked': len(blocked),
                'sent': sent_on.get('acp')})

    reason = markup_reason(drift, reference, flags)
    read_at = read_at or max((str(p['observed_at']) for p in pages if p.get('observed_at')), default=None)
    out.append({'id': 'markup', 'channel': 'schema_org', 'name': T['markup.name'].format(domain=domain),
                'status': 'drift' if reason else 'none',
                'last': T['markup.last'].format(day=short_day(read_at)) if read_at else T['markup.unread'],
                'fields': ', '.join(['weight range'] + (['gtin'] if markup_gtins(pages) else [])),
                'note': reason or T['markup.none'],
                'read_at': read_at, 'pages': len(pages),
                'markup_rows': sum(1 for r in drift or [] if r.get('kind') == 'markup'),
                'gtin_flags': sum(1 for f in flags if f.get('where') == 'markup')})

    ucp = [p for p in latest_by_record(pubs, 'ucp_uip') if p.get('status') == LIVE_STATUS]
    live = _newest(ucp, 'published_at') or _newest(ucp)
    version = (live or {}).get('spec_version') or short_day((live or {}).get('published_at'))
    out.append({'id': 'ucp', 'name': T['ucp.name'].format(domain=domain), 'status': 'live' if live else 'none',
                'last': T['ucp.last'].format(version=version) if live else T['ucp.none'],
                'fields': ', '.join(carried_fields((live or {}).get('payload'))) if live else '',
                'note': '' if live else T['ucp.none'],
                'channel': 'ucp_uip', 'published_at': (live or {}).get('published_at')})

    rule = next((r for r in rules or [] if r.get('code') == DEALS_RULE), None)
    approval = (rule or {}).get('approval')
    if rules is None:
        note = T['coupons.note.unread']
    elif approval == 'approved':
        on = short_day((rule or {}).get('approved_at'))
        note = T['coupons.note.approved'].format(on=f" on {on}" if on else '')
    elif approval == 'declined':
        note = T['coupons.note.declined']
    else:
        note = T['coupons.note.pending']
    out.append({'id': 'coupons', 'channel': 'deals_api', 'name': T['coupons.name'], 'status': 'next',
                'last': T['coupons.last'],
                'fields': T['coupons.fields'], 'note': note, 'rule': DEALS_RULE, 'approval': approval,
                'approval_look': APPROVAL_LOOK.get(approval) if approval else None})
    return out if channel_states is None else with_channel_states(out, channel_states)


def with_channel_states(surfaces: List[dict], channel_states: List[dict]) -> List[dict]:
    """
    The surfaces in the list's order, one per channel. The demo's five keep
    their own reading (the markup's is the live site's, not the compile's)
    and gain the list's state; Manufacturer Center, the ACP feed and UCP (held
    per SKU since supply 2U-1) take their status from it, so the two cannot
    disagree. The MCP server, Merchant
    Center and the deal directory are the list's entry with their words.
    """
    by_channel = {s.get('channel'): s for s in surfaces}
    out = []
    for c in channel_states:
        slug, state = c['channel'], c['state']
        s = by_channel.get(slug)
        if s is None and slug == 'mcp':
            s = {'name': T['mcp.name'], 'fields': T['mcp.fields'] if state == 'live' else '',
                 'note': T['mcp.note'] if state != 'blocked' else (c.get('note') or c['line']),
                 'external_ref': c.get('note') if state == 'live' else None,
                 # 2U-4: what the readback against the public server found (console_release.mcp_check)
                 'check': c.get('check'), 'check_reason': c.get('check_reason')}
        elif s is None and state == 'not_for_brand':
            s = {'name': T['gmc.name'] if slug == 'merchant_center' else T['directory.name'] if
                 slug == 'deal_directory' else c['name'], 'fields': '',
                 'note': T['seller.note'].format(rule=c.get('rule') or 'r3')}
        elif s is None:
            s = {'name': c['name'], 'fields': '', 'note': c.get('note') or c['line']}
        s = dict(s)
        if slug in ('manufacturer_center', 'acp'):
            s['status'] = state
        elif slug == 'ucp_uip' and state in ('held', 'blocked'):
            # supply 2U-1 compiles UCP per SKU for a brand: the list's state, line and clause
            s.update(status=state, last=c['line'], note=c.get('note') or s.get('note'))
        elif slug == 'ucp_uip':
            s['status'] = 'live' if state == 'live' else 'none'
        elif 'status' not in s:
            s['status'] = state
        s.setdefault('last', c['line'] if state in ('live', 'blocked') else c['label'])
        s.update({'id': SURFACE_IDS.get(slug, slug), 'channel': slug, 'state': state, 'label': c['label'],
                  'line': c['line'], 'reason': c.get('reason'), 'rule': c.get('rule')})
        out.append(s)
    return out


# ─── what changes on publish ──────────────────────────────────────────────

def _source(cycle: Optional[dict], read: Optional[str] = None, what: str = 'answers') -> dict:
    code = (cycle or {}).get('cycle_code')
    return {'cycle': code, 'day': short_day((cycle or {}).get('start_date')), 'read': short_day(read), 'what': what}


def lifecycle_rows(retired_named: Optional[dict], cycle: Optional[dict]) -> List[dict]:
    """A retired line agents still pick: was "sold, per N of M agents" (the
    cycle's brand-choice answers, every agent together), now "retired,
    successor AMORE". None when no agent named it."""
    out = []
    for line in (retired_named or {}).get('lines') or []:
        agents = line.get('agents') or {}
        if not agents.get('named'):
            continue
        succ = (line.get('successor') or {}).get('label')
        out.append({'field': f"{rm._slug(line.get('line'))}.status",
                    'was': T['diff.lifecycle.was'].format(named=agents['named'], of=agents['of']),
                    'now': T['diff.lifecycle.now'].format(successor=succ) if succ else T['diff.lifecycle.now_none'],
                    'prov': 'brand', 'kind': 'lifecycle', 'source': _source(cycle)})
    return out


def store_name(domain: Optional[str]) -> Optional[str]:
    """supply gives domains ("amazon.com"); the console names them as the
    Overview does (soa_shared/retailers.retailer_name)."""
    d = str(domain or '').lower().removeprefix('www.')
    return retailer_names.retailer_name(d) or d or None


def seller_rows(named: Dict[str, List[str]], feed_rows: Optional[List[dict]], cycle: Optional[dict],
                own_domains: Iterable[str] = ()) -> List[dict]:
    """A SKU whose stores the agents named (the cycle's where-to-buy and
    cheapest-place answers about it, `named_stores`, most named first) are
    not the feed's retailer list for it: was the agents', now the feed's.
    Only SKUs both sides list; the brand's own site is neither."""
    own = {str(d).lower().removeprefix('www.') for d in own_domains or () if d}
    own_names = {store_name(d) for d in own}
    brand = _brand_word(feed_rows or [])
    out = []
    for row in feed_rows or []:
        keys = [k for k in (row.get('sku'), row.get('variant_key'), f"sku:{row['sku']}" if row.get('sku') else None,
                            rm._gtin14(row.get('gtin14') or row.get('gtin'))) if k]
        agents = next((named[k] for k in keys if named.get(k)), None)
        listed = [store_name(r.get('domain')) for r in row.get('retailers') or []
                  if str(r.get('domain') or '').lower().removeprefix('www.') not in own]
        listed = list(dict.fromkeys(n for n in listed if n))
        if not agents or not listed:
            continue
        agents = [a for a in agents if a not in own_names]
        if set(agents) == set(listed):
            continue
        out.append({'field': f"{_field_base(row.get('product_name'), row.get('variant_label'), brand)}.sellers",
                    'was': ', '.join(agents) or 'no store', 'now': ', '.join(listed), 'prov': 'brand',
                    'kind': 'sellers', 'variant_ref': row.get('sku'), 'source': _source(cycle)})
    return out


def build_diff(*, drift: List[dict], flags: List[dict], lifecycle: List[dict], sellers: List[dict],
               cycle: Optional[dict], read_at: Optional[str]) -> List[dict]:
    """The Publishing diff, {field, was, now, prov} each with its `source`
    (the cycle whose read or answers the "was" is): 2M-1's weight rows (the
    markup or a retailer page against the chart), the GTIN corrections, the
    retired lines, the sellers."""
    out = [{**r, 'source': _source(cycle, read_at, 'supply read')} for r in drift or []]
    out += [{**{k: v for k, v in f.items() if k not in ('line', 'digits')},
             'source': _source(cycle, read_at, 'brand page' if f['where'] == 'markup' else 'feed')} for f in flags]
    return out + list(lifecycle) + list(sellers)


def collapse_gtin_rows(diff: List[dict]) -> tuple:
    """2T-8 (B3): (diff, gtin_line). The diff's GTIN rows become one row per product line ("Swaddlers Ultra: 9
    sizes drop the leading zero"), in the order the lines first appear; every other row stays where it is.
    `gtin_line` joins the lines' counts ("Swaddlers Ultra: 9 sizes drop the leading zero · AMORE: 8"). The per-size
    rows are the caller's `diff_all`."""
    groups: Dict[str, List[dict]] = {}
    for r in diff:
        if r.get('kind') == 'gtin':
            groups.setdefault(r.get('line') or r['field'].split('.')[0], []).append(r)
    out, done = [], set()
    for r in diff:
        if r.get('kind') != 'gtin':
            out.append(r)
            continue
        line = r.get('line') or r['field'].split('.')[0]
        if line in done:
            continue
        done.add(line)
        rows = groups[line]
        zeros = all(x.get('digits') == 11 for x in rows)
        n = len(rows)
        out.append({'field': f"{rm._slug(line)}.gtin ({'markup' if all(x.get('where') == 'markup' for x in rows) else 'feed' if all(x.get('where') == 'feed' for x in rows) else 'markup and feed'})",
                    'was': T['diff.gtin.zero' if zeros else 'diff.gtin.bad'].format(n=n, sizes='size' if n == 1 else 'sizes',
                                                                                  verb='drops' if n == 1 else 'drop'),
                    'now': T['diff.gtin.now.zero' if zeros else 'diff.gtin.now.bad'], 'prov': 'parleo', 'kind': 'gtin',
                    'line': line, 'count': n, 'source': rows[0].get('source'), 'rows': len(rows)})
    parts = [f"{line}: {T['diff.gtin.zero' if all(x.get('digits') == 11 for x in rows) else 'diff.gtin.bad'].format(n=len(rows), sizes='size' if len(rows) == 1 else 'sizes', verb='drops' if len(rows) == 1 else 'drop')}"
             if i == 0 else f"{line}: {len(rows)}" for i, (line, rows) in enumerate(groups.items())]
    return out, (' · '.join(parts) or None)


def build_preview(*, surfaces: List[dict], brand: Optional[str], name: Optional[str],
                  domain: Optional[str], skus: Optional[int] = None) -> dict:
    """{title, note, records, valid, compiled_at, held, sent}: Manufacturer
    Center's held file, its counts from supply's /tenant `held`."""
    mfc = next(s for s in surfaces if s['id'] == 'mfc')
    n, day = mfc['records_total'] or 0, short_day(mfc.get('compiled_at'))
    brand = brand or name or 'the brand'
    name = name or brand
    if not n:
        return {'title': T['preview.title.none'].format(brand=brand), 'note': T['not_compiled'], 'records': 0,
                'valid': 0, 'compiled_at': None, 'held': False, 'sent': None}
    domain = domain or 'the brand site'
    said = {'day': day, 'name': name, 'name_s': possessive(name), 'domain': domain, 'valid': mfc['records']}
    if mfc['status'] == 'blocked':
        note = T['preview.note.blocked'].format(**said, error=(mfc['errors'] or [''])[0])
    elif mfc.get('sent'):
        note = T['preview.note.sent'].format(**said, sent=short_day(mfc['sent']))
    else:
        note = T['preview.note'].format(**said)
    # 2T-8 (B3): the title counts the feed's SKUs (the demo's "Ten Pampers records"), the note the held file's records
    count = skus or n
    return {'title': T['preview.title'].format(count=_NUMBER_WORDS.get(count, str(count)), brand=brand), 'note': note,
            'skus': skus, 'records': n, 'valid': mfc['records_valid'], 'compiled_at': mfc.get('compiled_at'),
            'held': mfc['status'] == 'held' and not mfc.get('sent'), 'sent': mfc.get('sent')}


def build_artifacts(merchant: str, pubs: List[dict], channels: List[dict], held: Optional[dict] = None) -> List[dict]:
    """One entry per channel supply compiled for the merchant, its soa URL
    (B4): the file comes through soa with the org's token. A blocked channel
    (ACP) is listed with its clause: soa answers it as JSON, never a file."""
    names = {c.get('slug'): c.get('name') or c.get('slug') for c in channels or []}
    by_channel = (held or {}).get('by_channel') or {}
    out = []
    slugs = list(dict.fromkeys(p.get('channel_slug') or p.get('channel') for p in pubs or []))
    order = ('manufacturer_center', 'schema_org', 'acp')
    for slug in sorted(slugs, key=lambda s: (order.index(s) if s in order else len(order), str(s))):
        if slug == 'mcp':
            # 2U-2: Parleo serves the brand's records on its own MCP server: nothing is held, and supply serves no file
            continue
        rows = [p for p in latest_by_record(pubs, slug) if is_held(p) or is_blocked(p) or p.get('status') == LIVE_STATUS]
        newest = _newest(rows)
        if newest is None:
            continue
        blocked = [p for p in rows if is_blocked(p)]
        out.append({'channel': slug, 'name': names.get(slug, slug), 'records': by_channel.get(slug, len(rows)),
                    'compiled_at': newest.get('compiled_at'), 'held': any(is_held(p) for p in rows),
                    'blocked': bool(blocked), 'spec_clause': next((p.get('spec_clause') for p in blocked), None),
                    'url': f"/api/console/truesync/artifact?merchant={merchant}&channel={slug}"})
    return out


# ─── Rules and their backtest ─────────────────────────────────────────────

def build_rules(supply_rules: Optional[List[dict]]) -> List[dict]:
    """supply's rules as the console's Rule: every word supply's, `id` the
    code, `audience` the console's list of names (supply's is one string,
    names joined with ", "), the approval with the demo's look beside."""
    out = []
    for r in supply_rules or []:
        audience = r.get('audience')
        names = [a.strip() for a in audience.split(',')] if isinstance(audience, str) else \
            [a.get('name') if isinstance(a, dict) else str(a) for a in audience or []]
        out.append({'id': r.get('code'), 'name': r.get('name') or '', 'detail': r.get('detail') or '',
                    'on': bool(r.get('on')), 'scope': r.get('scope') or '',
                    'audience': [{'name': n} for n in names if n], 'outcome': r.get('outcome') or '',
                    # beside the typed fields
                    'code': r.get('code'), 'audience_text': audience if isinstance(audience, str) else None,
                    'approval': r.get('approval'), 'approval_look': APPROVAL_LOOK.get(r.get('approval')),
                    'approved_by': r.get('approved_by'), 'approved_at': r.get('approved_at'), 'note': r.get('note'),
                    'compiled': r.get('compiled'), 'stored': r.get('stored'), 'history': r.get('history') or []})
    return out


def _lines_matched(answers: List[dict]) -> List[str]:
    variants = [a for a in answers if a.get('variant')]
    firsts = {a['variant'].split(' ')[0] for a in variants}
    brand = next(iter(firsts)) if len(firsts) == 1 else None
    out = []
    for a in answers:
        if a.get('verdict') != 'match':
            continue
        line = _line_display((a.get('variant') or '').replace(a.get('size') or '\0', ''), brand).strip()
        if line and line not in out:
            out.append(line)
    return out


def backtest_counts(*, attribute_answers: List[dict], retired_named: Optional[dict], promo: Optional[dict]) -> dict:
    """The three counts the backtest reads, from the Overview's own helpers'
    output: {attribute: (k, n, lines), retired: (k, n, label, successor,
    successor_k), promo: (k, n, deals)}; a part the cycle did not measure is None."""
    size = [a for a in attribute_answers or [] if a.get('size') == BACKTEST_SIZE and a.get('verdict') is not None]
    attribute = (sum(1 for a in size if a['verdict'] == 'match'), len(size), _lines_matched(size)) if size else None
    line = ((retired_named or {}).get('lines') or [None])[0]
    retired = None
    if line:
        top = (line.get('brand_choice') or {}).get('all') or next(iter((line.get('brand_choice') or {}).values()), None)
        if top:
            retired = (top.get('named') or 0, top.get('answers') or 0, line.get('label') or line.get('line'),
                       (line.get('successor') or {}).get('label'), top.get('successor_named'))
    deals = None
    if promo:
        named = [d for d in promo.get('per_deal') or [] if d.get('named')]
        deals = (promo.get('k') or 0, promo.get('n') or 0,
                 _and([f"{d.get('short') or d.get('title')} {d['named']}" for d in named[:2]]))
    return {'attribute': attribute, 'retired': retired, 'promo': deals}


def build_backtest(before: dict, before_cycle: dict, after: Optional[dict], after_cycle: Optional[dict],
                   sent: Optional[dict], name: str) -> List[dict]:
    """Rules' backtest: before measured on `before_cycle`; after "Next read"
    until the brand states a send, then the first cycle scored after it."""
    day = short_day(before_cycle.get('start_date'))
    if sent is None:
        rule = T['backtest.after.unsent'].format(name=name, name_s=possessive(name))
    elif after_cycle is None:
        rule = T['backtest.after.waiting'].format(sent=short_day(sent['sent_at']))
    else:
        rule = T['backtest.after.read'].format(code=after_cycle['cycle_code'], day=short_day(after_cycle.get('start_date')),
                                               sent=short_day(sent['sent_at']))

    def value(counts, key):
        c = (counts or {}).get(key)
        return f"{c[0]} of {c[1]}" if c else T['backtest.not_measured']

    def after_value(key):
        return T['backtest.next'] if after is None else value(after, key)

    def row(key, label, note):
        return {'key': key, 'label': label, 'before': value(before, key), 'after': after_value(key),
                'note': (note + '. ' if note else '') + rule, 'cycle': before_cycle['cycle_code'],
                'after_cycle': (after_cycle or {}).get('cycle_code') if after else None}
    a, r, p = before.get('attribute'), before.get('retired'), before.get('promo')
    return [
        row('attribute', T['backtest.attribute'].format(size=BACKTEST_SIZE),
            T['backtest.attribute.note'].format(lines=_and(a[2]) or 'None', day=day) if a else None),
        row('retired', T['backtest.retired'].format(line=r[2] if r else 'the retired line'),
            T['backtest.retired.note'].format(successor=r[3], k=r[4] or 0, day=day) if r and r[3] else None),
        row('promo', T['backtest.promo'], T['backtest.promo.note'].format(deals=p[2], day=day) if p and p[2] else None),
    ]


def around_send(cycles: List[dict], sent: Optional[dict]) -> tuple:
    """(the last cycle started on or before the send's day, the first started
    after it) among `cycles` (scored, newest first). Unsent: (the newest, None)."""
    if not cycles:
        return None, None
    if sent is None:
        return cycles[0], None
    day = str(sent.get('sent_at') or '')[:10]
    before = next((c for c in cycles if str(c.get('start_date'))[:10] <= day), None)
    after = next((c for c in reversed(cycles) if str(c.get('start_date'))[:10] > day), None)
    return before, after


# ─── Impact ───────────────────────────────────────────────────────────────

def locked_block(*, name: str, brand: Optional[str], domain: Optional[str]) -> dict:
    return {'state': 'locked', 'title': T['locked.title'].format(name=name),
            'text': T['locked.text'].format(name=name, name_s=possessive(name), brand=brand or name,
                                            domain=domain or 'the brand site')}
