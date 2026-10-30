"""
2V-2: an externally hosted seller (supply's `mode` seller_external, parleo-
supply-app#40, docs/truesync/seller-mode.md there). The read models behind
the console's retail-mode screens (parleohq/truesync console-demo,
apps/console/src/data/petco.ts): Rules, Approvals, Publishing, the TrueSync
release card, the Product record, the Fix queue, True Value's program line,
ladder and receipt, and Prove's Funded offers.

A seller we do not host publishes through its own accounts, which Parleo has
no credential for, so supply compiles its records and HOLDS them, as it does a
brand's (manufacturer mode): status `compiled_not_published`, reason
`held_for_merchant`; the seller's own team sends the file, and "sent" is a
fact the seller states (`sent_by_merchant`). The mcp channel is the one Parleo
publishes itself (get_product_true_cost on its own server, read back).

What is the seller's, not a brand's: its own prices and the price path of its
owned programs (supply 2V-1: list, each first-order step, ongoing, member,
each with its rule, funder and end date), and six rules s1..s6 whose every
word is supply's. soa derives only what it counts on the cycle's answers: the
backtest, the two fixes (first-order prices; a retired program name), whether
answers applied a funded ladder, and the agents that quoted a program price.
Copy: SELLER_TEMPLATES. Pure; no read, no model.
"""
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu

SELLER_EXTERNAL = 'seller_external'
#: The modes whose records supply compiles and holds.
HELD_MODES = (manu.MANUFACTURER, SELLER_EXTERNAL)

#: Publishing's surfaces in the demo's order (petco.ts publishing.surfaces), then the channels 2U-2 added.
SURFACES = (
    ('merchant_center', 'gmc', 'Google Merchant Center', 'The feed Gemini and AI Mode read'),
    ('ucp_uip', 'ucp', 'Google UCP', 'Checkout profile with program prices'),
    ('acp', 'oai', 'OpenAI product feed', 'The feed behind ChatGPT shopping cards'),
    ('schema_org', 'markup', 'Site markup (schema.org Offer)', 'What every crawler reads first'),
    ('mcp', 'mcp', 'MCP endpoint', "Served by get_product_true_cost on Parleo's own server. Nothing is sent"),
    ('deals_api', 'deals', 'Parleo Deals API', "The seller's programs, priced per SKU"),
    ('deal_directory', 'directory', 'Deal directory', 'Each program with its funder and end date'),
    ('manufacturer_center', 'mfc', 'Google Manufacturer Center',
     "A brand's channel. A seller's product data goes to Merchant Center"),
)

SELLER_TEMPLATES = {
    'surface.held': 'Compiled {day}',
    'surface.held.sent': 'Compiled {day}, sent {sent}',
    'surface.live': 'Live since {day}',
    'surface.blocked': 'Blocked {day}',
    'surface.not_compiled': 'Not compiled yet',
    'surface.not_for_seller': 'Not for a seller',
    'surface.records': '{valid} of {total} valid',
    'preview.title': '{skus} {name} SKUs, {surfaces} surfaces',
    'preview.title.none': 'No {name} record compiled yet',
    'preview.note': 'Compiled {day}. Held until {name_s} team sends it. Sending it publishes the same record everywhere.',
    'preview.note.sent': 'Compiled {day}. {name_s} team says it sent {channels} on {sent}.',
    'diff.absent': 'absent',
    'diff.member': '{price} (member-only)',
    'diff.first_order_rule': '{rule}, ends {until}',
    'backtest.cheapest': 'Price questions where {name} is cheapest and named so',
    'backtest.retired': 'Answers quoting a retired program name',
    'backtest.member': 'Member prices visible to public agents',
    'backtest.cheapest.note': 'Answers that quoted a {name} first-order price, {day}',
    'backtest.retired.note': '{names}, {day}',
    'backtest.member.note': 'Rule s2 holds' ,
    'backtest.member.note.off': 'Rule s2 is off: the member price compiles into public channels',
    'fix.first_order.title': 'Publish first-order {program} prices on {n} SKUs',
    'fix.first_order.detail': ('{funded} funded by a brand, {standard} standard first-order, {rx} Rx held by rule. '
                               '{missed} of {asked} price answers left the first-order price out.'),
    # 2V-4 (B5): the demo's copy fix, named for the former name answers say most
    'fix.retired.title': 'Fix "{former}" copy',
    'fix.retired.detail': '{k} of {n} answers this cycle still said {names}. The program is {current}.',
    'fix.release.title': 'Send the held {name} files',
    'fix.release.detail': '{n} SKUs compiled for {surfaces} surfaces and held. {name_s} own team sends them.',
    'state.needs_decision': 'Needs a decision',
    'state.in_flight': 'Approved, in flight',
    'state.held': 'Compiled, held',
    'state.shipped': 'Shipped',
    'tv.program_line': 'First {program} {price} ({rule_name}). Quoted by {k} of {n} agents.',
    'tv.program_line.ongoing': '{program} {price} on every order. Quoted by {k} of {n} agents.',
    'tv.ladder.title': "{funder_s} {program} ladder at {name}",
    'tv.ladder.sub': '{product}. Funded by {funder}{ends}.',
    'tv.ladder.note': 'Agents that quoted a step on the ladder: {k} of {n}.',
    # 2V-5 (V3): a price path no brand funds
    'tv.ladder.title.open': '{program} prices at {name}',
    'tv.ladder.sub.open': '{product}. Funder not stated{ends}.',
    # 2V-5 (V1, V2, V4): a program entry's line (program_text)
    'program.scope.all': 'all SKUs',
    'program.tier': 'tier {tier}',
    'program.points': '{points} points',
    # 2V-6 (X2): supply's points_multiplier is the rate per dollar spent
    'program.multiplier': '{x} points per $1',
    'program.benefit': '{tier} members get {off} on {scope} ({name})',
    'program.former': 'formerly {names}',
    'program.member': '{tier} members {off}',
    'program.rx': 'Rx excluded{orders}',
    'program.funded': 'funded by {funder}',
    'program.funded.none': 'funder not stated',
    'program.stacks': 'combines with {names}',
    'program.stacks.none': 'not combinable with other offers',
    'program.ends': 'ends {day}',
    'program.ends.none': 'no end date',
    # 2V-6 (X3): a line's read-out, from the cycle's value-tier rows
    'program.asked': 'asked this cycle, {k} of {n} right',
    'program.asked.unscored': 'asked this cycle, none scored',
    'program.not_asked': 'not asked this cycle',
    'program.quoted': 'Program price quoted in {k} of {n} answers.',
    # 2V-6 (X4): the record's points line
    'record.points': '{program} points',
    'record.points.rate': '{rate} per $1 ({at_list} on this {item} at list{first})',
    'record.points.first': ', {n} on the first {program} order',
    'record.points.fixed': '{n} on this {item}',
    'tv.receipt.title': 'What a first {program} order costs',
    'tv.program.terms': '{terms}',
    'prove.title': 'Funded offers',
    'prove.sub': 'Brand money that runs through {name}, and whether agents pass it on.',
    'prove.detail': '{steps}. Ends {until}.',
    'prove.detail.open': '{steps}.',
    'prove.agents': 'Applied in {k} of {n} answers.',
    'prove.agents.none': 'No answer this cycle priced these SKUs.',
    'prove.value': '{amount} on the {product}',
    'prove.aside.kick': '{funder} partner seat',
    'prove.aside.label': 'answers that applied the ladder {funder} pays for',
    'prove.note': 'Partner seats see funded offers and the answers behind them, nothing else.',
    'record.sub': '{name} item {sku}',
    'record.status.held': 'Compiled, held in preview',
    'record.status.sent': 'Compiled, sent {sent}',
    'record.status.none': 'Not compiled yet',
}
T = SELLER_TEMPLATES
ORDER_LABELS = {'1': '1st order', '2': '2nd order', '3': '3rd order', 'ongoing': 'Ongoing'}


def is_seller_external(merchant_record: Optional[dict]) -> bool:
    return (merchant_record or {}).get('mode') == SELLER_EXTERNAL


def is_held_mode(merchant_record: Optional[dict]) -> bool:
    """A merchant whose records supply compiles and holds: a brand at retail, or a seller we do not host."""
    return (merchant_record or {}).get('mode') in HELD_MODES


#: 2V-4 (B1): the kinds an external merchant can be; the content branches on them, the gate does not.
EXTERNAL_KINDS = ('brand', 'seller')


def is_external(merchant_record: Optional[dict]) -> bool:
    """
    2V-4 (B1): the one gate every held-mode read model takes. An external
    merchant, hosting `external`, a brand or a seller: supply holds its
    compile for its own team either way (seller_mode.holds). A record from a
    supply before 2R-1 states no mode and holds nothing, so it is not one.
    """
    r = merchant_record or {}
    return r.get('hosting') == 'external' and r.get('kind') in EXTERNAL_KINDS and r.get('mode') is not None


def external_kind(merchant_record: Optional[dict]) -> Optional[str]:
    """'brand' or 'seller' for an external merchant (is_external), else None: where the content differs."""
    return (merchant_record or {}).get('kind') if is_external(merchant_record) else None


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith('s') else f"{name}'s"


def _dec(value) -> Optional[Decimal]:
    try:
        return None if value in (None, '') else Decimal(str(value))
    except InvalidOperation:
        return None


def money(value) -> str:
    """$77.99; $30 for a whole amount."""
    d = _dec(value)
    if d is None:
        return ''
    d = d.quantize(Decimal('0.01'))
    return f"${d:.0f}" if d == d.to_integral() else f"${d}"


def _day(value) -> Optional[str]:
    return manu.short_day(value)


def _program(name: Optional[str], merchant: str) -> str:
    """"Petco Autoship" -> "Autoship": the merchant's name off the front, as supply's rule wording says it."""
    text = name or ''
    return text[len(merchant) + 1:] if merchant and text.casefold().startswith(merchant.casefold() + ' ') else text


def _funder(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value if any(c.isupper() for c in value) else value.replace('_', ' ').replace('-', ' ').title()


def _until(step: Optional[dict]) -> Optional[str]:
    """A program's end date, as a date: supply sends midnight UTC, which a time zone would read as the day before."""
    value = (step or {}).get('valid_until')
    return str(value)[:10] if value else None


def short_rule(rule: Optional[str]) -> str:
    """"40% off, capped at $30" -> "40% ($30 cap)", "5% off" -> "5%": the ladder's step labels, as the demo writes them."""
    text = rule or ''
    m = re.match(r'^(.*?) off, capped at (\$[\d.]+)$', text)
    if m:
        return f"{m.group(1)} ({m.group(2)} cap)"
    return text[:-4] if text.endswith('% off') else text


def paths_by_sku(price_paths: Optional[dict]) -> List[dict]:
    """supply's /price-paths rows, each {variant_id, sku, title, product_name, product_url, price_path}."""
    return [r for r in (price_paths or {}).get('skus') or [] if isinstance(r, dict)]


# ─── Publishing ───────────────────────────────────────────────────────────

def _newest(rows: List[dict], key: str = 'compiled_at') -> Optional[dict]:
    rows = [r for r in rows if r.get(key)]
    return max(rows, key=lambda r: str(r.get(key))) if rows else None


def _fields(slug: str, rows: List[dict]) -> str:
    """What the held files carry, read off their payloads (the demo's `fields` line)."""
    found: List[str] = []

    def add(name):
        if name not in found:
            found.append(name)
    for p in rows:
        payload = p.get('payload') if isinstance(p.get('payload'), dict) else {}
        if slug == 'merchant_center':
            for item in payload.get('productInputs') or []:
                attrs = item.get('productAttributes') or {}
                for key, name in (('price', 'price'), ('salePrice', 'sale_price'), ('loyaltyPrograms', 'loyalty_program'),
                                  ('salePriceEffectiveDate', 'sale_price_effective_date')):
                    if key in attrs:
                        add(name)
        elif slug == 'acp':
            for item in payload.get('items') or []:
                for key in ('price', 'sale_price', 'sale_price_end_date', 'availability'):
                    if key in item:
                        add(key)
        elif slug == 'ucp_uip':
            for v in (payload.get('product') or {}).get('variants') or []:
                add('price')
                if 'list_price' in v:
                    add('list_price')
                if (v.get('metadata') or {}).get('price_path'):
                    add('program steps')
        elif slug == 'schema_org':
            text = repr(payload)
            for key, name in (('priceSpecification', 'priceSpecification'), ('MemberProgram', 'MemberProgram'),
                              ('validThrough', 'validThrough')):
                if key in text:
                    add(name)
        elif slug in ('deals_api', 'deal_directory'):
            add('programs' if slug == 'deal_directory' else 'price paths')
        elif slug == 'mcp':
            add('list price, first-order steps, ongoing, member, funder')
    return ', '.join(found)


def build_surfaces(*, pubs: List[dict], held: Optional[dict], plan: Optional[List[dict]]) -> List[dict]:
    """
    Publishing's surfaces for an external seller, one per supply channel in the
    demo's order: {id, name, status (held | live | blocked | not_compiled |
    not_for_seller), last, fields, note, channel, sent, records, publication_ids}.
    A channel is held when its newest rows are held_for_merchant, live when
    Parleo published it (mcp), blocked when every row is.
    """
    held = held or {}
    sent_on = held.get('sent') or {}
    planned = {p.get('channel'): p for p in plan or []}
    out = []
    for slug, sid, name, note in SURFACES:
        rows = manu.latest_by_record(pubs, slug)
        holding = [p for p in rows if manu.is_held(p)]
        blocked = [p for p in rows if manu.is_blocked(p)]
        live = [p for p in rows if p.get('status') == manu.LIVE_STATUS]
        entry = planned.get(slug) or {}
        sent = sent_on.get(slug)
        if entry.get('reason') == 'not_for_seller':
            status, last = 'not_for_seller', T['surface.not_for_seller']
        elif live:
            status, last = 'live', T['surface.live'].format(day=_day((_newest(live, 'published_at') or live[0]).get(
                'published_at') or live[0].get('compiled_at')))
        elif holding:
            day = _day((_newest(holding) or {}).get('compiled_at'))
            status = 'held'
            last = T['surface.held.sent'].format(day=day, sent=_day(sent)) if sent else T['surface.held'].format(day=day)
        elif blocked:
            status, last = 'blocked', T['surface.blocked'].format(day=_day((_newest(blocked) or {}).get('compiled_at')))
        else:
            status, last = 'not_compiled', T['surface.not_compiled']
        valid = [p for p in holding if manu.is_valid(p)]
        errors = [e for p in holding for e in manu._errors(p)]
        out.append({'id': sid, 'name': name, 'status': status, 'last': last,
                    'fields': _fields(slug, holding or live), 'note': entry.get('note') if status == 'blocked' else note,
                    'channel': slug, 'sent': sent, 'records_total': len(holding or live),
                    'records': T['surface.records'].format(valid=len(valid), total=len(holding)) if holding else None,
                    'errors': errors, 'reason': entry.get('reason'),
                    'publication_ids': [p['id'] for p in holding if p.get('id') is not None]})
    return out


def channel_states(surfaces: List[dict]) -> List[dict]:
    """The eight channels as one list: {channel, state, label}, the release card's and the Overview card's."""
    labels = {'held': 'Compiled, held', 'live': 'Live', 'blocked': 'Blocked', 'not_compiled': 'Not compiled yet',
              'not_for_seller': 'Not for a seller'}
    return [{'channel': s['channel'], 'name': s['name'], 'state': s['status'], 'label': labels.get(s['status'], s['status']),
             'line': s['last'], 'sent': s.get('sent')} for s in surfaces]


def _first_with_steps(rows: List[dict]) -> Optional[dict]:
    funded = [r for r in rows if ((r.get('price_path') or {}).get('steps') or [{}])[0].get('funded_by')]
    stepped = [r for r in rows if (r.get('price_path') or {}).get('steps')]
    return (funded or stepped or [None])[0]


def build_diff(*, paths: List[dict], loyalty: Optional[dict]) -> List[dict]:
    """
    What changes on publish, in the demo's rows (petco.ts publishing.diff):
    the first SKU with a first-order step (a funded one first), its first-order
    price and rule, its ongoing price, the program name (a former name ->
    the current), the member price. `was` is absent: nothing the seller
    publishes through Parleo states these before the held file is sent.
    """
    row = _first_with_steps(paths)
    path = (row or {}).get('price_path') or {}
    out = []
    first = (path.get('steps') or [None])[0]
    if first:
        out.append({'field': 'first_order_price', 'was': T['diff.absent'], 'now': str(first['price']),
                    'prov': 'brand' if first.get('funded_by') else 'retail', 'sku': row.get('sku')})
        rule = first.get('rule') or ''
        out.append({'field': 'first_order_rule', 'was': T['diff.absent'],
                    'now': T['diff.first_order_rule'].format(rule=rule, until=str(_until(first))[:10]) if _until(first) else rule,
                    'prov': 'brand' if first.get('funded_by') else 'retail', 'sku': row.get('sku')})
    if path.get('ongoing'):
        out.append({'field': 'ongoing_price', 'was': T['diff.absent'], 'now': str(path['ongoing']['price']),
                    'prov': 'retail', 'sku': (row or {}).get('sku')})
    former = list((loyalty or {}).get('former_names') or [])
    if loyalty and former:
        out.append({'field': 'program_name', 'was': former[0], 'now': loyalty.get('name'), 'prov': 'retail'})
    member = path.get('member')
    if member:
        out.append({'field': 'member_price', 'was': T['diff.absent'], 'now': T['diff.member'].format(price=member['price']),
                    'prov': 'retail', 'sku': (row or {}).get('sku')})
    return out


def build_preview(*, surfaces: List[dict], name: str, skus: Optional[int], held: Optional[dict]) -> dict:
    holding = [s for s in surfaces if s['status'] in ('held', 'live')]
    if not holding:
        return {'title': T['preview.title.none'].format(name=name), 'note': ''}
    day = _day((held or {}).get('compiled_at'))
    sent = {s['channel']: s['sent'] for s in surfaces if s.get('sent')}
    title = T['preview.title'].format(skus=skus if skus is not None else '', name=name, surfaces=len(holding)).replace('  ', ' ')
    if sent:
        newest = max(sent.values())
        names = manu._and([s['name'] for s in surfaces if s.get('sent')])
        note = T['preview.note.sent'].format(day=day, name_s=_possessive(name), channels=names, sent=_day(newest))
    else:
        note = T['preview.note'].format(day=day, name_s=_possessive(name))
    return {'title': title, 'note': note}


# ─── answers ──────────────────────────────────────────────────────────────

def _prices_in(text: str) -> List[Decimal]:
    out = []
    for m in re.finditer(r'\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)', text or ''):
        try:
            out.append(Decimal(m.group(1).replace(',', '')))
        except InvalidOperation:
            continue
    return out


def quoted_first_order(answer: dict, paths: List[dict]) -> bool:
    """Whether an answer quoted any SKU's first-order price (to the cent)."""
    wanted = {_dec(s.get('price')) for r in paths for s in (r.get('price_path') or {}).get('steps') or []
              if s.get('order_n') == '1'}
    return bool(wanted & set(_prices_in(answer.get('text') or '')))


def quoted_step(answer: dict, path: Optional[dict]) -> bool:
    wanted = {_dec(s.get('price')) for s in (path or {}).get('steps') or []}
    return bool(wanted & set(_prices_in(answer.get('text') or '')))


def says_former(answer: dict, former: Iterable[str]) -> List[str]:
    text = (answer.get('text') or '').casefold()
    return [n for n in former if n and n.casefold() in text]


def subject_keys(source_ref: Optional[dict]) -> List[str]:
    """2V-5 (W4): the product a question is coded to, by its source: the variant id, SKU, variant ref and GTIN its
    source_ref carries, each also as GTIN-14. None for a question coded to no one product (a comparison)."""
    from app.services import console_read_models as rm
    ref = source_ref if isinstance(source_ref, dict) else {}
    raw = [ref.get(k) for k in ('variant_id', 'sku', 'variant_ref', 'gtin')]
    return sorted({str(k) for k in raw + [rm._gtin14(ref.get('gtin'))] if k})


def coded_to(answer: dict, row: dict) -> bool:
    """2V-5 (W4): an answer whose question is coded to this SKU (subject_keys against the row's variant id, SKU and
    GTIN). Text naming the product is not enough: a where-to-buy answer that also prices the 47 lb bag, or a
    comparison naming several products, is not an answer about the 30 lb bag."""
    from app.services import console_read_models as rm
    sku = str(row.get('sku') or '')
    mine = {str(k) for k in (row.get('variant_id'), sku, f"sku:{sku}" if sku else None, f"feed_sku:{sku}" if sku else None,
                             row.get('gtin'), rm._gtin14(row.get('gtin'))) if k}
    return bool(mine & set(answer.get('keys') or []))


def mentions(answer: dict, row: dict) -> bool:
    """An answer about the SKU: its product name's first words, or its sku."""
    text = (answer.get('text') or '').casefold()
    name = ' '.join(str(row.get('product_name') or row.get('title') or '').split()[:3]).casefold()
    return bool(name and name in text) or bool(row.get('sku') and str(row['sku']) in text)


# ─── Rules ────────────────────────────────────────────────────────────────

def _rule(rules: Optional[List[dict]], code: str) -> Optional[dict]:
    return next((r for r in rules or [] if r.get('code') == code or r.get('id') == code), None)


def build_backtest(*, rules: Optional[List[dict]], answers: List[dict], price_answers: List[dict], paths: List[dict],
                   former: List[str], name: str, cycle: Optional[dict]) -> List[dict]:
    """
    The demo's three rows (petco.ts rules.backtest), counted on the newest
    scored cycle: price answers that quoted a first-order price, answers
    saying a retired program name, member prices in public channels (0 while
    s2 is on). `after` is "Next read": a held file changes nothing an agent
    reads until it is sent.
    """
    day = _day((cycle or {}).get('start_date'))
    quoted = sum(1 for a in price_answers if quoted_first_order(a, paths))
    retired = [a for a in answers if says_former(a, former)]
    s2 = _rule(rules, 's2')
    return [
        {'key': 'cheapest', 'label': T['backtest.cheapest'].format(name=name),
         'before': f"{quoted} of {len(price_answers)}", 'after': 'Next read',
         'note': T['backtest.cheapest.note'].format(name=name, day=day)},
        {'key': 'retired', 'label': T['backtest.retired'], 'before': str(len(retired)), 'after': 'Next read',
         'note': T['backtest.retired.note'].format(names=manu._and(former) if former else 'None stated', day=day)},
        {'key': 'member', 'label': T['backtest.member'], 'before': '0', 'after': '0' if (s2 or {}).get('on') else 'Next read',
         'note': T['backtest.member.note'] if (s2 or {}).get('on') else T['backtest.member.note.off']},
    ]


# ─── Fix queue ────────────────────────────────────────────────────────────

def _state(rule: Optional[dict], held_any: bool) -> str:
    if rule is None or rule.get('approval') == 'needs_approval' or not rule.get('on'):
        return 'needs_decision'
    return 'in_flight'


def build_fixes(*, rules: Optional[List[dict]], paths: List[dict], answers: List[dict], price_answers: List[dict],
                loyalty: Optional[dict], pubs: List[dict], name: str, program: Optional[str]) -> dict:
    """
    {fixes, summary}: the fixes the record and the answers ask for.

      first_order   rule s1 is off (or waits) and price answers left the
                    first-order price out: publish it (gate s1)
      retired       answers still say a former program name and rule s4 is
                    not on (gate s4)
      release       records are held: the seller's team sends them

    Numbered in that order. No owner or due date is recorded: None.
    """
    fixes = []
    s1, s4 = _rule(rules, 's1'), _rule(rules, 's4')
    stepped = [r for r in paths if (r.get('price_path') or {}).get('steps')]
    rx = [r for r in paths if (r.get('price_path') or {}).get('rx')]
    funded = [r for r in stepped if r['price_path']['steps'][0].get('funded_by')]
    missed = [a for a in price_answers if not quoted_first_order(a, paths)]
    if stepped and (not (s1 or {}).get('on') or (s1 or {}).get('approval') != 'approved') and (missed or not price_answers):
        fixes.append({'id': 'first_order', 'gate': 's1', 'title': T['fix.first_order.title'].format(
            program=program or 'program', n=len(stepped) + len(rx)),
            'detail': T['fix.first_order.detail'].format(funded=len(funded), standard=len(stepped) - len(funded),
                                                         rx=len(rx), missed=len(missed), asked=len(price_answers)),
            'status': _state(s1, False), 'scope': f"{len(stepped) + len(rx)} SKUs",
            'tags': ['Merchant Center', 'UCP', 'OpenAI feed', 'Site markup'], 'priority': 'High',
            'owner': None, 'due': None})
    former = list((loyalty or {}).get('former_names') or [])
    saying = [a for a in answers if says_former(a, former)]
    if former and saying and not (s4 or {}).get('on'):
        said = Counter(n for a in saying for n in says_former(a, former))
        names = manu._and(sorted(said))
        top = sorted(said.items(), key=lambda kv: (-kv[1], former.index(kv[0])))[0][0]
        fixes.append({'id': 'retired_name', 'gate': 's4', 'title': T['fix.retired.title'].format(former=top),
                      'detail': T['fix.retired.detail'].format(k=len(saying), n=len(answers), names=names,
                                                               current=(loyalty or {}).get('name')),
                      'status': _state(s4, False), 'scope': 'Program record', 'tags': ['UCP', 'Site markup'],
                      'priority': 'Medium', 'owner': None, 'due': None})
    holding = [p for p in pubs if manu.is_held(p)]
    if holding:
        sent = manu.first_sent(pubs)
        surfaces_n = len({p.get('channel_slug') or p.get('channel') for p in holding})
        fixes.append({'id': 'release', 'gate': None, 'title': T['fix.release.title'].format(name=name),
                      'detail': T['fix.release.detail'].format(n=len(paths), surfaces=surfaces_n, name_s=_possessive(name)),
                      'status': 'shipped' if sent else 'held', 'scope': f"{len(paths)} SKUs, {surfaces_n} surfaces",
                      'tags': ['Publishing'], 'priority': 'High', 'owner': None, 'due': None})
    # the console's fix shape (2T-8): text, state (needs_decision | in_flight | queued | shipped), surfaces, pool, severity
    for n, f in enumerate(fixes, 1):
        f['n'] = n
        f['state_label'] = T.get(f"state.{f['status']}", f['status'])
        f['state'] = 'in_flight' if f['status'] == 'held' else f['status']
        f['text'] = f['detail']
        f['surfaces'] = f['tags']
        f['kind'] = f['id']
        f['pool'] = 'both'
        f['severity'] = f['priority']
    waiting = [f for f in fixes if f['state'] == 'needs_decision']
    by_state = {k: sum(1 for f in fixes if f['state'] == k) for k in ('needs_decision', 'in_flight', 'queued', 'shipped')}
    first = waiting[0]['title'] if waiting else None
    hero = (f"{len(waiting)} of {len(fixes)} fixes need a decision." + (f" First up: {first}." if first else '')) if fixes \
        else 'No fix: no rule, answer or held release asks for one this cycle.'
    return {'fixes': fixes, 'summary': {'waiting': len(waiting), 'total': len(fixes), 'by_state': by_state,
                                        'hero': hero, 'first': first, 'order_note': ''}}


# ─── True Value: program line, ladder, receipt ────────────────────────────

def _agents_quoting(answers: List[dict], row: dict) -> tuple:
    about = [a for a in answers if mentions(a, row)]
    agents = {a.get('agent') for a in about if a.get('agent')}
    quoting = {a.get('agent') for a in about if a.get('agent') and quoted_step(a, row.get('price_path'))}
    return len(quoting), len(agents)


def program_lines(*, paths: List[dict], answers: List[dict], merchant: str) -> Dict[str, str]:
    """{variant_id: programLine} for each SKU whose path has a program price, in the demo's words."""
    out = {}
    for row in paths:
        path = row.get('price_path') or {}
        first = (path.get('steps') or [None])[0]
        k, n = _agents_quoting(answers, row)
        if first:
            rule_name = f"{_funder(first.get('funded_by'))} ladder" if first.get('funded_by') else first.get('rule')
            out[str(row.get('variant_id') or row.get('sku'))] = T['tv.program_line'].format(
                program=_program(first.get('program_name'), merchant), price=money(first['price']),
                rule_name=rule_name, k=k, n=n)
        elif path.get('ongoing'):
            out[str(row.get('variant_id') or row.get('sku'))] = T['tv.program_line.ongoing'].format(
                program=_program(path['ongoing'].get('program_name'), merchant), price=money(path['ongoing']['price']),
                k=k, n=n)
    return out


def _stepped(row: dict) -> bool:
    path = row.get('price_path') or {}
    return bool(path.get('steps') or path.get('ongoing') or path.get('member'))


def build_ladder(*, paths: List[dict], answers: List[dict], name: str, sku: Optional[str] = None) -> Optional[dict]:
    """
    The demo's ladder block for one SKU's price path, in 2V-1's shape: list,
    each first-order step in order, ongoing, member, each with its bar's width.
    2V-5 (V3): any SKU with a price below list, funded or not: the block read
    only a funded ladder, so a feed with no `funded_by` said "no price below
    the list price" above a receipt at $46.79. `sku` the selected SKU, else the
    receipt's (_first_with_steps). None only when the path has no step.
    """
    row = next((r for r in paths if str(r.get('sku')) == str(sku) and _stepped(r)), None) if sku else \
        (_first_with_steps(paths) or next((r for r in paths if _stepped(r)), None))
    if row is None:
        return None
    path = row['price_path']
    lst = _dec(path.get('list_price'))
    if not lst:
        return None
    pct = lambda p: int(round(float(_dec(p) / lst * 100)))  # noqa: E731
    steps = [{'label': 'List', 'value': money(lst), 'pct': 100, 'kind': 'ink'}]
    for s in path.get('steps') or []:
        steps.append({'label': f"{ORDER_LABELS[s['order_n']]}, {short_rule(s['rule'])}",
                      'value': money(s['price']), 'pct': pct(s['price']), **({'kind': 'b'} if s['order_n'] == '1' else {})})
    if path.get('ongoing'):
        o = path['ongoing']
        steps.append({'label': f"Ongoing, {short_rule(o['rule'])}", 'value': money(o['price']), 'pct': pct(o['price'])})
    if path.get('member'):
        m = path['member']
        steps.append({'label': f"{m.get('program_name') or 'Member'}, {short_rule(m.get('rule'))}", 'value': money(m['price']),
                      'pct': pct(m['price'])})
    first = (path.get('steps') or [None])[0] or path.get('ongoing') or path.get('member')
    funder = _funder(first.get('funded_by'))
    program = _program(first.get('program_name'), name)
    k = sum(1 for a in answers if mentions(a, row) and quoted_step(a, path))
    n = sum(1 for a in answers if mentions(a, row))
    until = _until(first)
    product = row.get('title') and f"{row.get('product_name')}, {row.get('title')}" or row.get('product_name')
    return {'title': T['tv.ladder.title'].format(funder_s=_possessive(funder), name=name, program=program) if funder
            else T['tv.ladder.title.open'].format(name=name, program=program),
            'sub': T['tv.ladder.sub'].format(product=product, funder=funder, ends=f", ends {_day(until)}" if until else '')
            if funder else T['tv.ladder.sub.open'].format(product=product, ends=f", ends {_day(until)}" if until else ''),
            'steps': steps, 'note': T['tv.ladder.note'].format(k=k, n=n), 'sku': row.get('sku')}


def build_receipt(*, paths: List[dict], merchant: str) -> Optional[dict]:
    """The demo's receipt for the ladder's SKU: list, the first-order discount, the first order, the member line."""
    row = _first_with_steps(paths)
    if row is None:
        return None
    path = row['price_path']
    first = path['steps'][0]
    lst = _dec(path.get('list_price'))
    rows = [{'k': 'List price', 'v': money(lst)}]
    off = lst - _dec(first['price'])
    label = f"{_funder(first.get('funded_by')) + ' ladder' if first.get('funded_by') else _program(first.get('program_name'), merchant)}, first order {first['rule']}"
    rows.append({'k': label, 'v': f"-{money(off)}", 'kind': 'minus',
                 **({'tag': 'Brand funded'} if first.get('funded_by') else {})})
    rows.append({'k': f"First {_program(first.get('program_name'), merchant)} order", 'v': money(first['price']), 'kind': 'big'})
    member = path.get('member')
    if member:
        rows.append({'k': f"{member.get('program_name')}, {member.get('rule')}", 'v': money(member['price']),
                     'tag': 'Member' if member.get('stackable') else 'Member, not combinable'})
    return {'title': T['tv.receipt.title'].format(program=_program(first.get('program_name'), merchant)),
            'sub': f"{row.get('product_name')}{', ' + row['title'] if row.get('title') and row.get('title') != row.get('product_name') else ''}",
            'rows': rows, 'sku': row.get('sku')}


def _scope_words(entry: dict) -> str:
    """An incentive's scope in words: "all SKUs", "6 SKUs", "Dog > Food"."""
    kind = entry.get('applies_to') or 'all'
    if kind == 'skus':
        n = len(entry.get('applies_to_skus') or [])
        return f"{n} {'SKU' if n == 1 else 'SKUs'}"
    if kind == 'gtins':
        n = len(entry.get('applies_to_gtins') or [])
        return f"{n} {'GTIN' if n == 1 else 'GTINs'}"
    if kind == 'category':
        return str(entry.get('applies_to_category') or 'one category')
    return T['program.scope.all']


def _off(entry: dict) -> str:
    pct, amount = entry.get('discount_percent'), entry.get('discount_amount')
    text = f"{_dec(pct).normalize():f}% off" if pct is not None else f"{money(amount)} off" if amount is not None else ''
    if entry.get('cap_amount') is not None:
        text += f", capped at {money(entry['cap_amount'])}"
    return text


def _exclusions(entry: dict) -> List[str]:
    out = []
    for x in entry.get('exclusions') or []:
        if isinstance(x, dict) and x.get('rx'):
            orders = [ORDER_LABELS.get(str(o), str(o)).lower() for o in x.get('orders') or []]
            out.append(T['program.rx'].format(orders=f" on the {manu._and(orders)}" if orders else ''))
    return out


def points_rate(entry: dict) -> Optional[str]:
    """2V-6 (X2): a points entry's rate in words: "10 points per $1" (points_multiplier, per dollar spent) or
    "120 points" (a fixed total); None for an entry with neither."""
    if entry.get('points_multiplier') is not None:
        return T['program.multiplier'].format(x=f"{_dec(entry['points_multiplier']).normalize():f}")
    if entry.get('points') is not None:
        return T['program.points'].format(points=f"{_dec(entry['points']).normalize():f}")
    return None


def _name_words(name: Optional[str]) -> set:
    return set(re.findall(r'[a-z0-9]+', str(name or '').casefold())) - {'points', 'point'}


def same_program(a: Optional[str], b: Optional[str]) -> bool:
    """2V-6: two program names are one program when one's words hold the other's ("Perks", "Petco Perks",
    "Petco Perks points"), as a question names a program by what the record called it."""
    x, y = _name_words(a), _name_words(b)
    return bool(x and y) and (x <= y or y <= x)


def _tier(value) -> Optional[str]:
    from app.services import console_read_models as rm
    return rm._norm_tier(value)


def _points_of(loyalty: dict, owned: List[dict]) -> Optional[dict]:
    """2V-6 (X2): the points entry a loyalty tier earns by: the same program (id or name), for this tier or every
    tier."""
    for e in owned:
        if e.get('mechanic') != 'points':
            continue
        if not (e.get('program_id') and e.get('program_id') == loyalty.get('program_id')
                or same_program(e.get('name'), loyalty.get('name'))):
            continue
        if e.get('tier_name') and _tier(e['tier_name']) != _tier(loyalty.get('tier_name')):
            continue
        return e
    return None


def _benefits(loyalty: dict, owned: List[dict]) -> List[str]:
    """2V-6 (X2): the member prices a loyalty tier gives, linked by tier_name, entries that differ only in scope
    together: "Premier members get 10% off on Dog > Food, Cat > Food (Perks Premier)"."""
    tier = _tier(loyalty.get('tier_name'))
    if not tier:
        return []
    groups: List[List[dict]] = []
    for e in owned:
        if e.get('mechanic') == 'member_price' and _tier(e.get('tier_name')) == tier and _off(e):
            same = next((g for g in groups if _same_terms(g[0]) == _same_terms(e)), None)
            if same is not None:
                same.append(e)
            else:
                groups.append([e])
    return [T['program.benefit'].format(tier=g[0]['tier_name'], off=_off(g[0]), name=g[0].get('name') or 'member price',
                                        scope=', '.join(dict.fromkeys(_scope_words(e) for e in g)))
            for g in groups]


def program_text(entry: dict, *, scopes: List[str], owned: Optional[List[dict]] = None, former: bool = True) -> str:
    """
    2V-5 (V1, V2, V4): one owned incentive entry as one line, from 2V-1's
    shape: its scope in words, its steps in order with `ongoing` (or its
    member discount), each cap, the Rx exclusion, a loyalty program's tier,
    points and former names, its funder ("funder not stated" when none),
    whether it combines (`stacks_with` empty: not combinable with other
    offers), its end date ("no end date").

    2V-6 (X2): a points entry reads its rate first ("10 points per $1, all
    SKUs"); a loyalty tier carries its program's points rate and the member
    prices linked to it by tier_name (`owned`, every entry), and its former
    names only where `former` (the program's first line).
    """
    parts = [', '.join(scopes)]
    mechanic = entry.get('mechanic')
    if mechanic == 'points':
        parts = [f"{points_rate(entry) or 'points'}, {', '.join(scopes)}"]
    elif mechanic == 'loyalty_program':
        if entry.get('tier_name'):
            parts.append(T['program.tier'].format(tier=entry['tier_name']))
        rate = points_rate(entry) or points_rate(_points_of(entry, owned or []) or {})
        if rate:
            parts.append(rate)
        parts += _benefits(entry, owned or [])
        if former and entry.get('former_names'):
            parts.append(T['program.former'].format(names=manu._and(entry['former_names'])))
    elif entry.get('steps'):
        parts.append('; '.join(f"{ORDER_LABELS.get(str(s.get('order_n')), str(s.get('order_n'))).lower()} {_off(s)}".strip()
                               for s in entry['steps']))
    else:
        off = _off(entry)
        if off:
            parts.append(T['program.member'].format(off=off, tier=entry.get('tier_name') or 'member')
                         if mechanic == 'member_price' else off)
    parts += _exclusions(entry)
    parts.append(T['program.funded'].format(funder=_funder(entry['funded_by'])) if entry.get('funded_by')
                 else T['program.funded.none'])
    stacks = [str(x) for x in entry.get('stacks_with') or []]
    parts.append(T['program.stacks'].format(names=manu._and(stacks)) if stacks else T['program.stacks.none'])
    until = _until(entry)
    parts.append(T['program.ends'].format(day=_day(until)) if until else T['program.ends.none'])
    return '. '.join(p[:1].upper() + p[1:] for p in parts if p) + '.'


def _same_terms(entry: dict) -> tuple:
    """What makes two entries one line: all but their scope (Perks Premier on Dog > Food and on Cat > Food)."""
    import json
    return json.dumps({k: v for k, v in entry.items() if not k.startswith('applies_to') and k not in ('id', 'set_at')},
                      sort_keys=True, default=str)


def asked_about(entry: dict, value_outcomes: List[dict]) -> List[dict]:
    """
    2V-6 (X3): the cycle's value-tier rows (soa_expectation_outcomes, tier
    value_incentives) about one program entry, by what the question asked:
    a points question by its rule's program_name, and for a points entry by
    its mechanic too (a per_dollar question is about a points_multiplier,
    a fixed one about a points total); a member-price question by its tier
    name. Before, the line keyed on 2V-1's per-product rows: cycle 3's one
    per-dollar question left every line "not asked this cycle".
    """
    from app.services import console_read_models as rm
    mechanic, out = entry.get('mechanic'), []
    for o in value_outcomes or []:
        expected = rm._json(o.get('expected_answer')) or {}
        kind = expected.get('type')
        if kind == 'points' and mechanic in ('points', 'loyalty_program'):
            rule = expected.get('rule') if isinstance(expected.get('rule'), dict) else {}
            if not same_program(rule.get('program_name') or expected.get('program_name'), entry.get('name')):
                continue
            if mechanic == 'points' and (rule.get('kind') == 'per_dollar') != (entry.get('points_multiplier') is not None):
                continue
            out.append(o)
        elif kind == 'member_price' and mechanic in ('member_price', 'loyalty_program') and entry.get('tier_name') \
                and _tier(expected.get('tier_name')) == _tier(entry['tier_name']):
            out.append(o)
    return out


def _read_out(about: List[dict]) -> dict:
    """2V-6 (X3): {agentsRight, tone, asked, scored, right, by_surface} of a line's value-tier rows, in words."""
    from app.services import console_read_models as rm
    scored = [o for o in about if o.get('outcome') in rm.SUMMARY_SCORED]
    right = sum(1 for o in scored if o.get('outcome') == 'exact')
    text_ = (T['program.asked'].format(k=right, n=len(scored)) if scored else T['program.asked.unscored'])
    tone = 'neu' if not scored else 'ok' if right == len(scored) else 'bad' if not right else 'warn'
    return {'agentsRight': text_, 'tone': tone, 'asked': len(about), 'scored': len(scored), 'right': right,
            'by_surface': rm._program_agents(scored)}


def build_programs(*, owned: Optional[List[dict]], paths: List[dict], answers: List[dict], merchant: str,
                   value_outcomes: Optional[List[dict]] = None) -> List[dict]:
    """
    The demo's program cards (petco.ts trueValue.programs): 2V-5 (V1, V2, V4)
    one per owned incentive entry, entries that differ only in scope on one
    line, in supply's order: {name (2V-3 Q7: with its tier where entries share
    a name), tier, scope, text (program_text, the whole line), terms (its
    steps), valid_until, funded_by, mechanic, agentsRight, tone, program_id}.
    Before, one line per program id hid Autoship's base entry under its
    SKU-scoped ladder, and Perks Premier read the ladder's steps.

    2V-6: `terms` is `text`, the one line, on every card (X1: a loyalty tier's
    terms were its former names alone, or empty). The points entry has its
    line, and a loyalty tier reads its points rate and member prices, its
    former names on the program's first line only (X2). `agentsRight` is
    "asked this cycle, k of n right" over the cycle's value-tier rows about
    the line (asked_about), with `asked`, `scored`, `right`, `by_surface`;
    a line no value-tier row asked about keeps the price-path count, or
    "not asked this cycle" when no answer was about it either (X3).
    """
    from app.services import console_read_models as rm
    owned = list(owned or [])
    entries = [e for e in owned
               if e.get('mechanic') in ('subscription_discount', 'member_price', 'loyalty_program', 'points')]
    groups: List[List[dict]] = []
    for e in entries:
        same = next((g for g in groups if _same_terms(g[0]) == _same_terms(e)), None)
        if same is not None:
            same.append(e)
        else:
            groups.append([e])
    claimed = {str(s) for e in entries if e.get('applies_to') == 'skus' for s in e.get('applies_to_skus') or []}
    formers_said: set = set()
    out = []
    for group in groups:
        entry = group[0]
        pid = entry.get('program_id') or entry.get('name')
        scopes = list(dict.fromkeys(_scope_words(e) for e in group))
        former = list(entry.get('former_names') or [])
        first = not (former and pid in formers_said)
        if former:
            formers_said.add(pid)
        text_ = program_text(entry, scopes=scopes, owned=owned, former=first)
        name = rm.incentive_name(entry, 'Program', [e for e in entries if e not in group] + [entry])
        if entry.get('mechanic') == 'points' and 'point' not in name.casefold():
            name = f"{name} points"
        base = {'name': name, 'tier': entry.get('tier_name'), 'scope': ', '.join(scopes), 'text': text_,
                'terms': text_, 'valid_until': _until(entry), 'funded_by': entry.get('funded_by'),
                'mechanic': entry.get('mechanic'), 'program_id': pid}
        asked = asked_about(entry, value_outcomes or [])
        if entry.get('mechanic') in ('loyalty_program', 'points'):
            saying = [a for a in answers if says_former(a, former)] if former else []
            said = f"{len(saying)} answers still said {manu._and(former)}." if former else ''
            if asked:
                read = _read_out(asked)
                out.append({**base, **read, 'agentsRight': ' '.join(filter(None, [read['agentsRight'],
                                                                                   said if saying else ''])),
                            'tone': 'warn' if saying and read['tone'] == 'ok' else read['tone']})
            else:
                out.append({**base, 'agentsRight': said or T['program.not_asked'], 'tone': 'warn' if saying else
                            'ok' if former else 'neu', 'asked': 0, 'scored': 0, 'right': 0, 'by_surface': {}})
            continue
        skus = {str(s) for e in group for s in e.get('applies_to_skus') or []}

        def in_scope(r: dict) -> bool:
            path = r.get('price_path') or {}
            on_path = any(s.get('program_id') == pid for s in (path.get('steps') or []) + [path.get('ongoing') or {}]) \
                if entry.get('mechanic') != 'member_price' else (path.get('member') or {}).get('program_id') == pid
            if entry.get('applies_to') == 'skus':
                return on_path and str(r.get('sku')) in skus
            return on_path and (entry.get('mechanic') == 'member_price' or str(r.get('sku')) not in claimed)

        if asked:
            out.append({**base, **_read_out(asked)})
            continue
        priced = [r for r in paths if in_scope(r)]
        about = [a for a in answers if any(mentions(a, r) for r in priced)]
        right = [a for a in about if any(quoted_step(a, r.get('price_path')) for r in priced)]
        out.append({**base, 'agentsRight': T['program.quoted'].format(k=len(right), n=len(about)) if about
                    else T['program.not_asked'],
                    'tone': 'bad' if about and not right else 'warn' if about and len(right) < len(about)
                    else 'ok' if about else 'neu', 'asked': 0, 'scored': 0, 'right': 0, 'by_surface': {}})
    return out


# ─── Prove: Funded offers ─────────────────────────────────────────────────

def build_funded_offers(*, paths: List[dict], answers: List[dict], name: str) -> dict:
    """
    The demo's Funded offers (petco.ts prove): one row per funder's program
    with the SKUs it funds, its steps and end date, how many answers about
    those SKUs applied it, and its value on the first SKU.
    """
    groups: Dict[tuple, List[dict]] = {}
    for row in paths:
        first = ((row.get('price_path') or {}).get('steps') or [None])[0]
        if first and first.get('funded_by'):
            groups.setdefault((first['funded_by'], first.get('program_id')), []).append(row)
    rows = []
    best = None
    for (funder, _pid), skus in groups.items():
        path = skus[0]['price_path']
        steps = ', '.join(f"{s['rule']} the {ORDER_LABELS[s['order_n']].lower().replace(' order', '')}"
                          if s['order_n'] != 'ongoing' else s['rule'] for s in path['steps'])
        until = _until(path['steps'][0])
        about = [a for a in answers if any(mentions(a, r) for r in skus)]
        applied = [a for a in about if any(quoted_step(a, r.get('price_path')) for r in skus)]
        off = _dec(path.get('list_price')) - _dec(path['steps'][0]['price'])
        row = {'brand': _funder(funder), 'title': f"{_funder(funder)} {_program(path['steps'][0].get('program_name'), name)} ladder",
               'detail': (T['prove.detail'] if until else T['prove.detail.open']).format(steps=steps[:1].upper() + steps[1:],
                                                                                         until=_day(until)),
               'terms': ', '.join(str(r.get('product_name')) for r in skus),
               'agents': T['prove.agents'].format(k=len(applied), n=len(about)) if about else T['prove.agents.none'],
               'tone': 'bad' if about and not applied else 'warn' if not about else 'ok',
               'value': T['prove.value'].format(amount=money(off), product=skus[0].get('title') or skus[0].get('product_name')),
               'funded_by': funder, 'applied': len(applied), 'answers': len(about), 'skus': [r.get('sku') for r in skus]}
        rows.append(row)
        if best is None:
            best = row
    aside = {'kick': T['prove.aside.kick'].format(funder=best['brand']),
             'value': f"{best['applied']} of {best['answers']}",
             'label': T['prove.aside.label'].format(funder=best['brand'])} if best else {'kick': '', 'value': '', 'label': ''}
    return {'title': T['prove.title'], 'sub': T['prove.sub'].format(name=name), 'rows': rows, 'aside': aside,
            'note': T['prove.note']}


def funded_pass_through(*, paths: List[dict], answers: List[dict]) -> Optional[dict]:
    """
    2V-3 (Q6): Funded offers' pass-through: of the cycle's cheapest-place answers (the catalog-built rows, by their
    source: console_seller.cycle_answers, rm.catalog_intent), `n` those about a SKU a funder pays for and `k` those
    that applied its price path. None when the cycle asked no cheapest-place question, the one case "not measured"
    is true. FL17 asked ten, filed under the brand-direct tier, and the screen said it asked none.
    """
    cheapest = [a for a in answers if a.get('intent') == 'cheapest_place']
    if not cheapest:
        return None
    funded = [r for r in paths if (((r.get('price_path') or {}).get('steps') or [None])[0] or {}).get('funded_by')]
    about = [a for a in cheapest if any(mentions(a, r) for r in funded)]
    applied = [a for a in about if any(quoted_step(a, r.get('price_path')) for r in funded)]
    return {'n': len(about), 'k': len(applied), 'asked': len(cheapest), 'intent': 'cheapest_place',
            'source': 'catalog'}


# ─── Product record ───────────────────────────────────────────────────────

def _covers(entry: dict, row: dict, feed_row: Optional[dict]) -> bool:
    """An owned entry's scope holds this SKU: every SKU, its SKU, its GTIN, or its feed category (or under it)."""
    kind = entry.get('applies_to') or 'all'
    if kind == 'skus':
        return str(row.get('sku')) in {str(s) for s in entry.get('applies_to_skus') or []}
    if kind == 'gtins':
        from app.services import console_read_models as rm
        gtin = rm._gtin14(row.get('gtin') or (feed_row or {}).get('gtin'))
        return bool(gtin) and gtin in {rm._gtin14(g) for g in entry.get('applies_to_gtins') or []}
    if kind == 'category':
        cat, want = str((feed_row or {}).get('category') or ''), str(entry.get('applies_to_category') or '')
        return bool(cat and want) and (cat == want or cat.startswith(want + ' >'))
    return True


def _points_earned(rate, price) -> str:
    """Points a per-dollar rate earns on a price, to the whole point: 10 per $1 on $77.99 is 780."""
    from decimal import ROUND_HALF_UP
    return f"{(_dec(rate) * _dec(price)).quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}"


def points_field(*, row: dict, feed_row: Optional[dict], owned: Optional[List[dict]], merchant: str) -> Optional[dict]:
    """
    2V-6 (X4): the record's points line, from the owned points entry whose
    scope holds the SKU: "Perks points: 10 per $1 (780 on this bag at list,
    468 on the first Autoship order)", the rate on the list price and on the
    first program step; a fixed total as "120 on this item". Read-model only:
    the price path carries no points (supply's offer_path, 2V-6 X5).
    """
    entry = next((e for e in owned or [] if e.get('mechanic') == 'points' and _covers(e, row, feed_row)), None)
    if entry is None:
        return None
    path = row.get('price_path') or {}
    item = 'bag' if re.search(r'\b(lb|oz|kg|g)\b', str(row.get('title') or row.get('product_name') or ''), re.I) \
        else 'item'
    label = T['record.points'].format(program=_program(entry.get('name'), merchant) or 'Program')
    if label.casefold().endswith('points points'):
        label = label[:-len(' points')]
    if entry.get('points_multiplier') is not None and _dec(path.get('list_price')) is not None:
        rate = _dec(entry['points_multiplier'])
        first = (path.get('steps') or [None])[0]
        value = T['record.points.rate'].format(
            rate=f"{rate.normalize():f}", at_list=_points_earned(rate, path['list_price']), item=item,
            first=T['record.points.first'].format(n=_points_earned(rate, first['price']),
                                                  program=_program(first.get('program_name'), merchant))
            if first and _dec(first.get('price')) is not None else '')
    elif entry.get('points') is not None:
        value = T['record.points.fixed'].format(n=f"{_dec(entry['points']).normalize():f}", item=item)
    else:
        return None
    return {'k': label, 'v': value, 'prov': 'retail', 'note': program_text(entry, scopes=[_scope_words(entry)])}


def build_record(*, row: dict, feed_row: Optional[dict], name: str, merchant: str, sent: Optional[dict],
                 held_any: bool, owned: Optional[List[dict]] = None) -> dict:
    """The demo's offer record for one SKU (petco.ts record): the price path as fields, with provenance. 2V-6 (X4):
    with the owned incentives, its points line (points_field) after the member price."""
    path = row.get('price_path') or {}
    fields = [{'k': 'List price', 'v': money(path.get('list_price')), 'prov': 'retail'}]
    steps = path.get('steps') or []
    if steps:
        first = steps[0]
        fields.append({'k': f"First {_program(first.get('program_name'), merchant)} order", 'v': money(first['price']),
                       'prov': 'brand' if first.get('funded_by') else 'retail',
                       'note': f"{_funder(first['funded_by']) + ' ladder ' if first.get('funded_by') else ''}{first['rule']}"})
        later = [s for s in steps[1:]]
        if later:
            fields.append({'k': 'Second and third orders' if len(later) > 1 else 'Second order',
                           'v': ', '.join(money(s['price']) for s in later),
                           'prov': 'brand' if first.get('funded_by') else 'retail',
                           'note': ', '.join(s['rule'].replace(' off', '') for s in later)})
    if path.get('ongoing'):
        o = path['ongoing']
        fields.append({'k': f"Ongoing {_program(o.get('program_name'), merchant)}", 'v': money(o['price']), 'prov': 'retail',
                       'note': f"{o['rule']} every order"})
    if path.get('member'):
        m = path['member']
        fields.append({'k': f"Member price ({m.get('program_name')})", 'v': money(m['price']), 'prov': 'retail',
                       'note': m.get('rule')})
    points = points_field(row=row, feed_row=feed_row, owned=owned, merchant=merchant)
    if points:
        fields.append(points)
    funded = next((s for s in steps if s.get('funded_by')), None)
    if funded:
        fields.append({'k': 'Funded by', 'v': _funder(funded['funded_by']), 'prov': 'brand',
                       'note': f"Ladder ends {_day(_until(funded))}" if _until(funded) else None})
    gtin = (feed_row or {}).get('gtin') or row.get('gtin')
    fields.append({'k': 'GTIN', 'v': gtin or 'Not in the feed', 'prov': 'retail', 'mono': True, 'diff': not gtin})
    fields.append({'k': 'Rx', 'v': 'Yes' if path.get('rx') else 'No', 'prov': 'retail'})
    for n in path.get('not_applied') or []:
        fields.append({'k': f"{n.get('program_name')}{' order ' + n['order_n'] if n.get('order_n') else ''}",
                       'v': 'Not applied', 'prov': 'retail', 'note': n.get('reason')})
    status = ({'label': T['record.status.sent'].format(sent=_day(sent.get('sent_at'))), 'tone': 'ok'} if sent else
              {'label': T['record.status.held'], 'tone': 'warn'} if held_any else
              {'label': T['record.status.none'], 'tone': 'neu'})
    return {'kind': 'offer', 'sku': row.get('sku'), 'title': ' '.join(filter(None, [row.get('product_name'),
                                                                                     row.get('title') if row.get('title') != row.get('product_name') else None])),
            'sub': T['record.sub'].format(name=name, sku=row.get('sku') or row.get('variant_id')),
            'status': status, 'fields': fields, 'issues': [], 'json': '',
            'price_path': path}
