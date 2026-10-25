"""
2R-2: manufacturer mode, a brand at retail. The read models behind the
console's TrueSync, Rules, Publishing and Impact screens when supply says the
merchant's `mode` is `manufacturer` (supply 2R-1).

A manufacturer never sets a price and Parleo never writes into its accounts:
supply compiles the brand's record for each surface and HOLDS it
(`compiled_not_published`, `held_for_merchant`); the brand's own team sends
the file. So nothing here is a publish state Parleo caused, and "sent" is a
fact the brand states (`sent_by_merchant` in supply's journal), never one the
system observed.

Every state is derived from supply's rows and the cycles' answers; no state is
a hardcoded string. The copy is MANUFACTURER_TEMPLATES. The router
(app/routers/console_manufacturer.py) does the reads; these are the pure
builders. Shapes and every rule: docs/console-read-models.md, "2R-2".
Deterministic; no model.
"""
import re
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

from app.services import console_read_models as rm
from soa_shared import attribute_accuracy, retailers as retailer_names

MANUFACTURER = 'manufacturer'

#: supply's publication statuses: held (compiled, not sent by Parleo), live, refused.
HELD = ('compiled_not_published', 'held_for_merchant')
LIVE = ('published',)
BLOCKED = ('failed',)

#: supply 2R-1's publication journal, the events soa reads. `sent_by_merchant`
#: is the brand saying its team sent the held file (POST /publishing/sent).
JOURNAL_EVENTS = ('compiled', 'held_for_merchant', 'sent_by_merchant')
SENT = 'sent_by_merchant'

#: The demo's five surfaces, in its order: (id, supply channel slug).
SURFACES = (('mfc', 'manufacturer_center'), ('oai', 'acp'), ('markup', None), ('ucp', 'ucp_uip'), ('coupons', None))

#: The rule whose approval the brand-funded deals surface waits on.
DEALS_RULE = 'r4'
#: The rules' approval states supply 2R-1 serves.
APPROVAL_STATES = ('approved', 'pending', 'needs_legal', 'returned')

#: The backtest's attribute row: the size rule r5's outcome names.
BACKTEST_SIZE = 'Size 4'

MANUFACTURER_TEMPLATES = {
    'mfc.name': 'Google Manufacturer Center',
    'mfc.last': 'File compiled {day}',
    'mfc.last.sent': 'File compiled {day}, sent {sent}',
    'mfc.note': "The brand's own team sends it. Parleo never writes into its account",
    'oai.name': 'OpenAI product feed (brand)',
    'oai.last': 'Compiled {day}',
    'oai.note': 'Brand feed, retailer-neutral',
    'markup.name': 'Site markup ({domain})',
    'markup.last': 'Read {day}',
    'markup.drift': '{lines} markup {verb} the wrong {sizes} {weights}',
    'markup.drift.sizes': '{lines} markup {verb} the wrong {weights}',
    'markup.gtin': '{lines} {gtins} {verb} {digits} digits',
    'markup.none': 'The markup states the record\'s weight ranges and GTINs',
    'ucp.name': 'UCP profile ({domain})',
    'ucp.last': 'Live, version {version}',
    'ucp.none': 'Not in this pass',
    'coupons.name': 'Brand-funded deals',
    'coupons.last': 'Next release',
    'coupons.fields': 'terms, retailers, end dates',
    'coupons.note.pending': 'Publishes after Legal approves rule 4',
    'coupons.note.approved': 'Legal approved rule 4{on}. Publishes in the next release',
    'coupons.note.unread': "Publishes after Legal approves rule 4. Rule 4's approval could not be read",
    'not_compiled': 'Not compiled yet',
    'blocked.last': 'Refused {day}',
    'diff.lifecycle.was': 'sold, per {named} of {of} agents',
    'diff.lifecycle.now': 'retired, successor {successor}',
    'diff.lifecycle.now_none': 'retired',
    'preview.title': '{count} {brand} records, Manufacturer Center first',
    'preview.title.none': 'No {brand} record compiled yet',
    'preview.note': "Compiled {day} from {domain} and same-day shelf reads. Held until {name}'s team sends it.",
    'preview.note.sent': "Compiled {day} from {domain} and same-day shelf reads. {name}'s team says it sent it on {sent}.",
    'rules.title': 'Compliance rules',
    'rules.sub': 'A manufacturer shows retailers neutrally and never sets a price. These rules hold on every surface.',
    'rules.note': 'Compliance rules compile into every product record. Legal signs off before Publishing switches a rule on.',
    'backtest.attribute': "{size} weight answers giving only the chart's range",
    'backtest.retired': 'Category answers naming {line}',
    'backtest.promo': 'Cheapest-place answers naming a live deal',
    'backtest.attribute.note': '{lines}, {day}',
    'backtest.retired.note': '{successor} named in {k}, {day}',
    'backtest.promo.note': '{deals}, {day}',
    'backtest.not_measured': 'Not measured',
    'backtest.next': 'Next read',
    'backtest.after.unsent': ("After is the first cycle scored after {name}'s team sends the file. A held file changes "
                              "nothing an agent reads, so holding it starts no clock."),
    'backtest.after.waiting': 'After is the first cycle scored after the send on {sent}. None has run yet.',
    'backtest.after.read': 'After is {code} ({day}), the first cycle scored after the send on {sent}.',
    'locked.title': 'Cause shows once {name} publishes the record',
    'locked.text': ("TrueSync can tie a change in these answers to a fix only after {name}'s team publishes the {brand} "
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
    """"Oct 4" from a date or a stamp, None when there is none."""
    if value in (None, ''):
        return None
    if isinstance(value, datetime):
        d = value.date()
    elif isinstance(value, date):
        d = value
    else:
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return f"{d.strftime('%b')} {d.day}"


def _and(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


# ─── supply's publications ────────────────────────────────────────────────

def merchant_publications(publications: Iterable[dict], listing_ids: Iterable) -> List[dict]:
    """The merchant's publications (its catalog's listings) of every channel."""
    ids = set(listing_ids)
    return [p for p in publications or [] if p.get('listing_id') in ids]


def latest_by_listing(publications: Iterable[dict], channel: str) -> List[dict]:
    """The newest publication per listing on `channel`, as build_truesync picks it."""
    best: Dict[object, dict] = {}
    for p in publications or []:
        if p.get('channel_slug') != channel:
            continue
        key = p.get('listing_id')
        have = best.get(key)
        if have is None or (rm._ts(p.get('compiled_at')), p.get('id') or 0) > \
                (rm._ts(have.get('compiled_at')), have.get('id') or 0):
            best[key] = p
    return list(best.values())


def journal(publications: Iterable[dict]) -> List[dict]:
    """Every journal entry on the publications, each with its publication's
    id and channel, oldest first."""
    out = []
    for p in publications or []:
        for e in p.get('journal') or []:
            if isinstance(e, dict) and e.get('event') in JOURNAL_EVENTS:
                out.append({**e, 'publication_id': e.get('publication_id') or p.get('id'),
                            'channel': e.get('channel') or p.get('channel_slug')})
    return sorted(out, key=lambda e: (str(e.get('sent_at') or e.get('at') or ''), e.get('publication_id') or 0))


def sent_facts(publications: Iterable[dict]) -> List[dict]:
    """The brand's statements that it sent a held file, one per (channel,
    sent_at), oldest first: {channel, sent_at, by, note, at, publication_ids}."""
    out: Dict[tuple, dict] = {}
    for e in journal(publications):
        if e.get('event') != SENT:
            continue
        key = (e.get('channel'), str(e.get('sent_at') or e.get('at')))
        fact = out.setdefault(key, {'channel': e.get('channel'), 'sent_at': e.get('sent_at') or e.get('at'),
                                    'by': e.get('by'), 'note': e.get('note'), 'at': e.get('at'),
                                    'publication_ids': []})
        fact['publication_ids'].append(e.get('publication_id'))
    return sorted(out.values(), key=lambda f: str(f['sent_at']))


def first_sent(publications: Iterable[dict]) -> Optional[dict]:
    """The first send the brand stated, on any channel: the clock starts there."""
    facts = sent_facts(publications)
    return facts[0] if facts else None


def carried_fields(payload) -> List[str]:
    """The field names a compiled payload actually carries: Manufacturer
    Center's products[].attributes, a feed's items[] keys, else the payload's
    own keys. In first-seen order."""
    names: List[str] = []

    def add(keys):
        for k in keys:
            if k not in names:
                names.append(k)
    if isinstance(payload, dict):
        products = payload.get('products')
        items = payload.get('items')
        if isinstance(products, list) and products:
            for p in products:
                add(((p or {}).get('attributes') or {}).keys() if isinstance(p, dict) else ())
        elif isinstance(items, list) and items:
            for i in items:
                add(i.keys() if isinstance(i, dict) else ())
        else:
            add(payload.keys())
    return names


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


def _brand_word(variants: List[dict]) -> Optional[str]:
    firsts = {(v.get('product_name') or '').split(' ')[0] for v in variants if v.get('product_name')}
    return next(iter(firsts)) if len(firsts) == 1 else None


def _line_display(product_name: Optional[str], brand: Optional[str]) -> str:
    """"Pampers Cruisers 360" -> "Cruisers 360": the line as the copy names it."""
    head = re.split(r',|\bsize\b', product_name or '', maxsplit=1, flags=re.I)[0]
    words = [w for w in head.split() if w.lower() not in {(brand or '').lower(), 'diapers', 'diaper'}]
    return ' '.join(words) or (product_name or '')


def _field_base(product_name: Optional[str], label: Optional[str], brand: Optional[str]) -> str:
    size = attribute_accuracy.size_label(label)
    return f"{rm.line_of(product_name or label, brand)}.{rm._slug(size or label)}"


def gtin_flags(reference: Optional[dict], feed_rows: Optional[List[dict]] = None) -> List[dict]:
    """GTINs that are not GTINs as written: the brand page markup's
    (/reference attributes[].markup_gtin, supply 2R-1) and the feed's as
    given. [{field, was, now, prov, kind, line, where}]; one per (field, was)."""
    variants = (reference or {}).get('attributes') or []
    brand = _brand_word(variants)
    out, seen = [], set()
    for v in variants:
        was = v.get('markup_gtin')
        now = gtin_correction(was)
        if now:
            field = f"{_field_base(v.get('product_name'), v.get('variant_label'), brand)}.gtin"
            if (field, str(was)) not in seen:
                seen.add((field, str(was)))
                out.append({'field': field, 'was': str(was), 'now': now, 'prov': 'parleo', 'kind': 'gtin',
                            'where': 'markup', 'line': _line_display(v.get('product_name'), brand),
                            'digits': len(''.join(ch for ch in str(was) if ch.isdigit())),
                            'variant_ref': v.get('variant_ref')})
    feed_brand = _brand_word(feed_rows or [])
    for row in feed_rows or []:
        was = row.get('gtin')
        now = gtin_correction(was)
        if now:
            field = f"{_field_base(row.get('product_name'), row.get('variant_label'), feed_brand)}.gtin"
            if (field, str(was)) not in seen:
                seen.add((field, str(was)))
                out.append({'field': field, 'was': str(was), 'now': now, 'prov': 'parleo', 'kind': 'gtin',
                            'where': 'feed', 'line': _line_display(row.get('product_name'), feed_brand),
                            'digits': len(''.join(ch for ch in str(was) if ch.isdigit())),
                            'variant_ref': row.get('sku')})
    return out


# ─── the surfaces ─────────────────────────────────────────────────────────

def markup_reason(drift: List[dict], reference: Optional[dict], flags: List[dict]) -> Optional[str]:
    """The site markup surface's reason, from the weight rows whose markup
    disagrees with the chart and the markup's GTIN flags: "Zzz and Cruisers
    360 markup carry the wrong Size 4 and Size 3 weights. AMORE and Ultra
    GTINs have 11 digits". None when neither."""
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


def brand_page_read(reference: Optional[dict], own_domains: Iterable[str]) -> Optional[str]:
    """When supply last read the brand's own page: its newest own-domain row,
    else the read's own date."""
    own = {str(d).lower().removeprefix('www.') for d in own_domains or () if d}
    stamps = [r.get('observed_at') for r in (reference or {}).get('rows') or []
              if str(r.get('retailer_domain') or '').lower().removeprefix('www.') in own and r.get('observed_at')]
    if stamps:
        return max(str(s) for s in stamps)
    run = (reference or {}).get('reference_run') or {}
    return (reference or {}).get('as_of') or run.get('finished_at') or run.get('created_at')


def _status_of(latest: List[dict]) -> str:
    statuses = {p.get('status') for p in latest}
    if statuses & set(LIVE):
        return 'live'
    if statuses & set(HELD):
        return 'held'
    if statuses & set(BLOCKED):
        return 'blocked'
    return 'not_compiled'


def _newest(rows: List[dict], key: str = 'compiled_at') -> Optional[dict]:
    rows = [r for r in rows if r.get(key)]
    return max(rows, key=lambda r: (rm._ts(r.get(key)), r.get('id') or 0)) if rows else None


def build_surfaces(*, pubs: List[dict], channels: List[dict], drift: List[dict], reference: Optional[dict],
                   flags: List[dict], own_domain: Optional[str], rules: Optional[List[dict]]) -> List[dict]:
    """The Publishing screen's five surfaces, in the demo's order (SURFACES),
    each {id, name, status, last, fields, note} with the facts it was derived
    from beside. `pubs` are the merchant's publications; `rules` supply's
    rules (None when unread)."""
    by_slug = {c.get('slug'): c for c in channels or []}
    domain = own_domain or 'the brand site'
    sent = {f['channel']: f for f in sent_facts(pubs)}
    out = []

    mc = latest_by_listing(pubs, 'manufacturer_center')
    status = _status_of(mc)
    held = [p for p in mc if p.get('status') in HELD]
    newest = _newest(held or mc)
    fields = []
    for p in held or mc:
        for f in carried_fields(p.get('payload')):
            if f not in fields:
                fields.append(f)
    day = short_day((newest or {}).get('compiled_at'))
    fact = sent.get('manufacturer_center')
    if status == 'not_compiled':
        last = T['not_compiled']
    elif status == 'blocked':
        last = T['blocked.last'].format(day=day)
    elif fact:
        last = T['mfc.last.sent'].format(day=day, sent=short_day(fact['sent_at']))
    else:
        last = T['mfc.last'].format(day=day)
    out.append({'id': 'mfc', 'name': T['mfc.name'], 'status': status, 'last': last, 'fields': ', '.join(fields),
                'note': T['mfc.note'],
                # beside the typed fields
                'channel': 'manufacturer_center', 'connected': (by_slug.get('manufacturer_center') or {}).get('connected'),
                'compiled_at': (newest or {}).get('compiled_at'), 'records': len(held),
                'field_list': fields, 'sent': fact,
                'publication_ids': sorted(p.get('id') for p in held if p.get('id') is not None)})

    acp = latest_by_listing(pubs, 'acp')
    status = _status_of(acp)
    newest = _newest(acp)
    day = short_day((newest or {}).get('compiled_at'))
    fields = []
    for p in [p for p in acp if p.get('status') in HELD + LIVE] or acp:
        for f in carried_fields(p.get('payload')):
            if f not in fields:
                fields.append(f)
    refused = next((p for p in sorted(acp, key=lambda p: rm._ts(p.get('compiled_at')), reverse=True)
                    if p.get('status') in BLOCKED), None)
    clause = (refused or {}).get('spec_clause') or (refused or {}).get('error')
    out.append({'id': 'oai', 'name': T['oai.name'], 'status': status,
                'last': T['not_compiled'] if status == 'not_compiled' else
                (T['blocked.last'] if status == 'blocked' else T['oai.last']).format(day=day),
                'fields': ', '.join(fields),
                'note': clause if status == 'blocked' and clause else T['oai.note'],
                'channel': 'acp', 'compiled_at': (newest or {}).get('compiled_at'), 'field_list': fields,
                'spec_clause': clause, 'sent': sent.get('acp')})

    reason = markup_reason(drift, reference, flags)
    read_at = brand_page_read(reference, [own_domain] if own_domain else [])
    out.append({'id': 'markup', 'name': T['markup.name'].format(domain=domain), 'status': 'drift' if reason else 'none',
                'last': T['markup.last'].format(day=short_day(read_at)) if read_at else T['not_compiled'],
                'fields': ', '.join(['weight range'] + (['gtin'] if any(v.get('markup_gtin') for v in
                                                                       (reference or {}).get('attributes') or []) else [])),
                'note': reason or T['markup.none'],
                'read_at': read_at, 'markup_rows': sum(1 for r in drift or [] if r.get('kind') == 'markup'),
                'gtin_flags': sum(1 for f in flags if f.get('where') == 'markup')})

    ucp = [p for p in latest_by_listing(pubs, 'ucp_uip') if p.get('status') in LIVE]
    live = _newest(ucp, 'published_at') or _newest(ucp)
    version = (live or {}).get('spec_version') or short_day((live or {}).get('published_at'))
    out.append({'id': 'ucp', 'name': T['ucp.name'].format(domain=domain), 'status': 'live' if live else 'none',
                'last': T['ucp.last'].format(version=version) if live else T['ucp.none'],
                'fields': ', '.join(carried_fields((live or {}).get('payload'))) if live else '',
                'note': T['ucp.none'] if not live else '',
                'channel': 'ucp_uip', 'published_at': (live or {}).get('published_at')})

    rule = next((r for r in rules or [] if (r.get('code') or r.get('id')) == DEALS_RULE), None)
    approval = (rule or {}).get('approval') or {}
    if rules is None:
        note = T['coupons.note.unread']
    elif approval.get('state') == 'approved':
        on = short_day(approval.get('at'))
        note = T['coupons.note.approved'].format(on=f" on {on}" if on else '')
    else:
        note = T['coupons.note.pending']
    out.append({'id': 'coupons', 'name': T['coupons.name'], 'status': 'next', 'last': T['coupons.last'],
                'fields': T['coupons.fields'], 'note': note,
                'rule': DEALS_RULE, 'approval': approval.get('state') if rule else None})
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


def _store_name(domain: Optional[str]) -> Optional[str]:
    d = str(domain or '').lower().removeprefix('www.')
    return retailer_names.retailer_name(d) or d or None


def seller_rows(named: Dict[str, List[str]], feed_rows: Optional[List[dict]], cycle: Optional[dict],
                own_domains: Iterable[str] = ()) -> List[dict]:
    """A SKU whose stores the agents named (the cycle's where-to-buy and
    cheapest-place answers about it, `named_stores`, most named first) are
    not the feed's retailer list for it: was the agents', now the feed's.
    Only SKUs both sides list; the brand's own site is neither."""
    own = {str(d).lower().removeprefix('www.') for d in own_domains or () if d}
    own_names = {_store_name(d) for d in own}
    brand = _brand_word(feed_rows or [])
    out = []
    for row in feed_rows or []:
        keys = [k for k in (row.get('sku'), row.get('variant_key'), rm._gtin14(row.get('gtin14') or row.get('gtin'))) if k]
        agents = next((named[k] for k in keys if named.get(k)), None)
        listed = [_store_name(r.get('domain')) for r in row.get('retailers') or []
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
    out = [{**{k: v for k, v in r.items()}, 'source': _source(cycle, read_at, 'supply read')} for r in drift or []]
    out += [{**{k: v for k, v in f.items() if k not in ('line', 'digits', 'where')}, 'where': f['where'],
             'source': _source(cycle, read_at, 'supply read' if f['where'] == 'markup' else 'feed')} for f in flags]
    return out + list(lifecycle) + list(sellers)


def build_preview(*, surfaces: List[dict], brand: Optional[str], name: Optional[str],
                  domain: Optional[str]) -> dict:
    """{title, note, records, compiled_at, held}: Manufacturer Center's held file."""
    mfc = next(s for s in surfaces if s['id'] == 'mfc')
    n, day = mfc['records'], short_day(mfc.get('compiled_at'))
    brand = brand or name or 'the brand'
    if not n:
        return {'title': T['preview.title.none'].format(brand=brand), 'note': T['not_compiled'], 'records': 0,
                'compiled_at': None, 'held': False}
    fact = mfc.get('sent')
    note = (T['preview.note.sent'] if fact else T['preview.note']).format(
        day=day, domain=domain or 'the brand site', name=name or brand, sent=short_day((fact or {}).get('sent_at')))
    return {'title': T['preview.title'].format(count=_NUMBER_WORDS.get(n, str(n)), brand=brand), 'note': note,
            'records': n, 'compiled_at': mfc.get('compiled_at'), 'held': not fact, 'sent': fact}


def build_artifacts(merchant: str, pubs: List[dict], channels: List[dict]) -> List[dict]:
    """One entry per channel with a held or live file, its soa URL (B4): the
    file comes through soa with the org's token, never supply's URL."""
    names = {c.get('slug'): c.get('name') or c.get('slug') for c in channels or []}
    out = []
    for slug in dict.fromkeys(p.get('channel_slug') for p in pubs or [] if p.get('channel_slug')):
        rows = [p for p in latest_by_listing(pubs, slug) if p.get('status') in HELD + LIVE]
        newest = _newest(rows)
        if newest is None:
            continue
        out.append({'channel': slug, 'name': names.get(slug, slug), 'records': len(rows),
                    'compiled_at': newest.get('compiled_at'), 'held': newest.get('status') in HELD,
                    'url': f"/api/console/truesync/artifact?merchant={merchant}&channel={slug}"})
    return out


# ─── Rules and their backtest ─────────────────────────────────────────────

def build_rules(supply_rules: Optional[List[dict]]) -> List[dict]:
    """supply's rules as the console's Rule, `id` the rule's code, its
    approval beside."""
    out = []
    for r in supply_rules or []:
        approval = r.get('approval') or {}
        out.append({'id': r.get('code') or r.get('id'), 'name': r.get('name') or '', 'detail': r.get('detail') or '',
                    'on': bool(r.get('on')), 'scope': r.get('scope') or '',
                    'audience': [a if isinstance(a, dict) else {'name': str(a)} for a in r.get('audience') or []],
                    'outcome': r.get('outcome') or '',
                    # beside the typed fields
                    'code': r.get('code') or r.get('id'),
                    'approval': {k: approval.get(k) for k in ('state', 'by', 'at', 'note')} if approval else None})
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
        rule = T['backtest.after.unsent'].format(name=name)
    elif after_cycle is None:
        rule = T['backtest.after.waiting'].format(sent=short_day(sent['sent_at']))
    else:
        rule = T['backtest.after.read'].format(code=after_cycle['cycle_code'], day=short_day(after_cycle.get('start_date')),
                                               sent=short_day(sent['sent_at']))

    def value(counts, key):
        c = (counts or {}).get(key)
        return f"{c[0]} of {c[1]}" if c else T['backtest.not_measured']

    def after_value(key):
        if after is None:
            return T['backtest.next']
        return value(after, key)

    out = []
    a = before.get('attribute')
    out.append({'key': 'attribute', 'label': T['backtest.attribute'].format(size=BACKTEST_SIZE),
                'before': value(before, 'attribute'), 'after': after_value('attribute'),
                'note': ((T['backtest.attribute.note'].format(lines=_and(a[2]) or 'None', day=day) + '. ') if a else '') + rule,
                'cycle': before_cycle['cycle_code'], 'after_cycle': (after_cycle or {}).get('cycle_code') if after else None})
    r = before.get('retired')
    out.append({'key': 'retired', 'label': T['backtest.retired'].format(line=r[2] if r else 'the retired line'),
                'before': value(before, 'retired'), 'after': after_value('retired'),
                'note': ((T['backtest.retired.note'].format(successor=r[3], k=r[4] or 0, day=day) + '. ')
                         if r and r[3] else '') + rule,
                'cycle': before_cycle['cycle_code'], 'after_cycle': (after_cycle or {}).get('cycle_code') if after else None})
    p = before.get('promo')
    out.append({'key': 'promo', 'label': T['backtest.promo'], 'before': value(before, 'promo'),
                'after': after_value('promo'),
                'note': ((T['backtest.promo.note'].format(deals=p[2], day=day) + '. ') if p and p[2] else '') + rule,
                'cycle': before_cycle['cycle_code'], 'after_cycle': (after_cycle or {}).get('cycle_code') if after else None})
    return out


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
            'text': T['locked.text'].format(name=name, brand=brand or name, domain=domain or 'the brand site')}
