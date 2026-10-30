"""
2V-4: retail mode, the external seller's reading of what brand mode already
has (the 2T and 2U rounds), over the seller's own shapes: supply's feed
listings, 2V-1's price path per SKU, 2V-2's seller rules s1..s6 and its hold
(`mode: seller_external`). The console's retail screens in the demo's words
(parleohq/truesync console-demo, apps/console/src/data/petco.ts):

  release page   the explainer's workspace in SKUs, the current release, every
                 channel's state, one matrix row per SKU on the eight channels
                 with the seller's states and reasons, the master record (the
                 offer record with the price path), the drift rows, the
                 compiler's lines per channel (2V-1's carried / approximated /
                 dropped table), the releases
  record issues  what the record, the held files, the feed and the page read
                 prove, each with its source
  signals        another store first, wrong price, program price missing or
                 misstated, a retired program name, a funded offer missed,
                 access; the lead from the worst of them
  Fix queue      the derived fixes beside 2V-2's (first-order prices, the
                 retired name's copy, the held files): the edge path, the Rx
                 terms, order data for Impact
  Approvals      every seller rule as a request, the signed rows, the release

Every count is one this module counts on its inputs; every sentence is
RETAIL_TEMPLATES'. Pure: no read, no model.
"""
import re
from collections import Counter
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_release as rel
from app.services import console_seller as cs

#: The eight channels, in the demo's retail order (console_seller.SURFACES): slug -> its short name.
CHANNEL_SHORT = {'merchant_center': 'Merchant Center', 'ucp_uip': 'UCP', 'acp': 'OpenAI feed',
                 'schema_org': 'Site markup', 'mcp': 'MCP endpoint', 'deals_api': 'Deals API',
                 'deal_directory': 'Deal directory', 'manufacturer_center': 'Manufacturer Center'}
CHANNEL_ORDER = tuple(s[0] for s in cs.SURFACES)
#: The channel Parleo publishes itself: a serve check, not a compile (no compiler panel).
PARLEO_PUBLISHED = ('mcp',)
SELLER_RULES = ('s1', 's2', 's3', 's4', 's5', 's6')

#: 2V-1's table (parleo-supply-app truesync/channels/price_path_carry.py CARRIAGE, docs/truesync/sku-feed.md "What
#: each channel carries"): per element of a SKU's price path, how each seller channel carries it. None is carried,
#: natively. supply's compile flags what a channel approximates or drops (`price_path.<element>` expressiveness);
#: what it carries natively it does not flag, so those lines come from this table, and say so.
CARRIAGE: Dict[str, Dict[str, Optional[tuple]]] = {
    'schema_org': {
        'first_order': ('approximated', 'A UnitPriceSpecification beside the list price; the condition (a first '
                                        'subscription order) and the percent are description text.'),
        'later_steps': ('approximated', 'Second and third order prices are description text.'),
        'ongoing': ('approximated', 'The recurring price is description text.'),
        'member': None, 'funded_by': ('dropped', 'schema.org has no funder field.'),
        'valid_until': None, 'not_stackable': ('approximated', 'Not combinable is description text.')},
    'ucp_uip': {
        'first_order': ('approximated', 'The selling price stays list; the step rides in variant.metadata.price_path.'),
        'later_steps': ('approximated', 'In variant.metadata.price_path.'),
        'ongoing': ('approximated', 'In variant.metadata.price_path.'),
        'member': ('dropped', 'UCP loyalty has no member-price field.'),
        'funded_by': ('approximated', 'In variant.metadata.price_path.'),
        'valid_until': ('approximated', 'In variant.metadata.price_path.'),
        'not_stackable': ('approximated', 'In variant.metadata.price_path.')},
    'acp': {
        'first_order': ('approximated', 'sale_price is the first-order price; the feed has no field for its '
                                        'condition, so it reads as a price anyone gets.'),
        'later_steps': ('dropped', 'No field for a later order.'), 'ongoing': ('dropped', 'No field for a recurring price.'),
        'member': ('dropped', 'No member-price field.'), 'funded_by': ('dropped', 'No funder field.'),
        'valid_until': None, 'not_stackable': ('dropped', 'No field for it.')},
    'merchant_center': {
        'first_order': ('approximated', 'salePrice is the first-order price, which Google reads as a price any '
                                        'buyer gets.'),
        'later_steps': ('dropped', 'No field for a later order.'), 'ongoing': ('dropped', 'No field for a recurring price.'),
        'member': None, 'funded_by': ('dropped', 'No funder field.'),
        'valid_until': None, 'not_stackable': ('dropped', 'No field for it.')},
}
ELEMENT_NAMES = {'first_order': 'first-order price', 'later_steps': '2nd and 3rd order', 'ongoing': 'ongoing price',
                 'member': 'member price', 'funded_by': 'funder', 'valid_until': 'end date',
                 'not_stackable': 'not combinable'}

RETAIL_TEMPLATES = {
    # the release page
    'workspace.mode_note': ("Offer records compiled from {name_s} feed and its own programs. Nothing an agent reads "
                            "changes until {name_s} team sends the files. Parleo serves get_product_true_cost itself."),
    'release.name': '{n} {name} SKUs, {surfaces} surfaces',
    # 2V-5 (W3): what the tiles count. compiled: one file per SKU per surface in the pass (held and live)
    'workspace.compiled': 'SKU files compiled ({skus} SKUs × {surfaces} surfaces)',
    'workspace.fields.carried': 'compiler lines carried, across the held channels',
    'workspace.fields.approximated': 'approximated',
    'workspace.fields.dropped': 'dropped by spec',
    # 2V-5 (W5): who approved the release: the signer of every seller rule, or how many are signed
    'release.signed': '{k} of {n} signed',
    'release.status.held': 'Compiled, held',
    'release.status.sent': 'Compiled, sent by {who}',
    'release.surface.held': 'Compiled, held · {day}',
    'release.surface.sent': 'Compiled, sent · {day}',
    'release.surface.live': 'Live · {line}',
    'release.surface.blocked': 'Blocked · {day}',
    'release.surface.not_for_seller': "Not for a seller · a brand's channel",
    'release.surface.out': 'Not compiled yet',
    'release.note.account': "Parleo never writes into {name_s} accounts. {name_s} own team sends each file.",
    'release.note.verify': 'The MCP endpoint is Parleo\'s own server, read back {verified}.',
    'release.note.verify.none': "The MCP endpoint is Parleo's own server. It is read back once it is published.",
    'channel.held': 'Held', 'channel.sent': 'Sent', 'channel.live': 'Live', 'channel.blocked': 'Blocked',
    'channel.not_for_seller': 'Not for a seller', 'channel.not_compiled': 'Not compiled yet',
    'channel.line.held': '{n} of {of} SKUs held · {day}',
    'channel.line.sent': '{n} of {of} SKUs · sent {sent}',
    'channel.line.live': '{n} SKUs served · verified {verified}',
    'channel.line.live.unverified': '{n} SKUs served · not verified yet',
    'channel.line.blocked': 'its spec refuses the record',
    'channel.line.not_for_seller': "a brand's channel",
    'cell.held': 'Held for {name_s} team',
    'cell.sent': '{who} says it sent this file, {day}',
    'cell.live': 'Served by get_product_true_cost',
    'cell.rx': 'Rx: list price only (rule s3)',
    'cell.not_for_seller': "A brand's channel. A seller's product data goes to Merchant Center",
    'releases.approvals': '{k} of {n} rules signed',
    'releases.verify.mcp': 'MCP endpoint {verdict} {verified}',
    'releases.verify.none': 'Waits for the send',
    'timeline.compiled': 'Compiled and held on {held} for {name_s} team{live}',
    'timeline.compiled.live': '. Live on the MCP endpoint, which Parleo serves',
    'timeline.readback.mcp': 'MCP endpoint read back: {verdict} {verified}',
    'timeline.sent': '{who} says it sent the {channel} file',
    'timeline.readback': 'Read back: prices right {k} of {n}',
    'drift.no_price': 'No price',
    'drift.truth.first': '{first} first {program}, {lst} list',
    'drift.truth.list': '{lst} list',
    'compiler.carried': 'Validated against {spec}',
    'compiler.table': "2V-1's table: {note}",
    'compiler.rule.merchant_center': ("Merchant Center reads salePrice as a price any buyer gets. The first order rides "
                                      "there, with its end date."),
    'compiler.rule.schema_org': 'An Offer at list price with the first-order price beside it; the program terms in the description.',
    'compiler.rule.acp': 'sale_price is the first-order price and sale_price_end_date its end. No field for the condition.',
    'compiler.rule.ucp_uip': 'The selling price stays list. The price path rides in variant.metadata.',
    'compiler.rule.deals_api': 'Every step of the path as the rules allow: what get_product_true_cost answers from.',
    'compiler.rule.deal_directory': 'Each program with its funder, end date and SKUs.',
    'compiler.rules': '{rules} apply, {on}',
    # the record's issues
    'issue.first_order.page': 'First-order price not in markup',
    'issue.first_order.page.detail': "{domain} publishes list price only in its Offer markup. The {price} lives in page text.",
    'issue.first_order.held.detail': 'The held site markup carries list price only: rule s1 is {state}. The {price} is in no file.',
    'issue.program.title': 'Program price not in markup',
    'issue.program.detail': '{program} {price} on every order is description text in the held markup, not an Offer price.',
    'issue.ladder.title': 'Ladder has no end date in markup',
    'issue.ladder.detail': 'The {day} end date is on the {funder} ladder, not on the offer.',
    'issue.gtin.title': 'GTIN missing',
    'issue.gtin.detail': 'No GTIN in {name_s} feed for this SKU. Agents match on name and retailer ID.',
    'issue.page.title': 'Page differs: {what}',
    'issue.page.detail': "{domain} says {said}. The feed says {feed}.",
    'issue.retired.title': 'Retired program name on the page',
    'issue.retired.detail': "The page still says {former}. The program is {current}.",
    'issue.rx.title': 'Rx with no program exclusion',
    'issue.rx.detail': ('{product} is Rx and its first {program} step applies: no program states an Rx exclusion. '
                        'Pricing picks one term.'),
    'issue.source.page': '{domain} page, read {day}',
    'issue.source.held': 'The held {channel} file, compiled {day}',
    'issue.source.feed': '{name_s} feed{version}',
    'issue.source.programs': "{name_s} programs (supply's owned incentives)",
    # signals
    'signal.store.title': 'Agents name {name}, then recommend {rival} first.',
    'signal.store.detail': '{name} first in {k} of {n} unprompted answers, {rival} in {r}. {name} named in {named}.',
    'signal.store.tag': 'Another store first',
    'signal.missing.title': 'Agents leave out the first {program} price that makes {name} cheaper.',
    'signal.missing.detail': '{missed} of {asked} price answers left the first-order price out. It is in no file agents read yet.',
    'signal.missing.tag': 'Program price missing',
    'signal.misstated.title': 'Agents quote {program} prices {name} does not charge.',
    'signal.misstated.detail': '{k} answers named {program} on a {name} SKU with a price that is on no step of its path.',
    'signal.misstated.tag': 'Program price misstated',
    'signal.retired.title': '{agents} still {say} {former}.',
    'signal.retired.detail': '{k} of {n} answers said {former}. The program is {current}.',
    'signal.retired.tag': 'Retired name',
    'signal.funded.title': "{funder_s} ladder{ends} and agents don't apply it.",
    'signal.funded.detail': 'Applied in {k} of {n} answers about {products}.',
    'signal.funded.tag': 'Funded offer missed',
    'signal.access.title': "{who} can't read {domain}.",
    'signal.access.detail': '{n} agent {identities} turned away at the edge. Signed agents should get the catalog.',
    'signal.access.tag': 'Access',
    'signal.wrong.tag': 'Wrong price',
    # the lead
    'lead.facts.cap': 'first recommendations',
    'lead.facts.missing': 'price answers without the first-order price',
    'lead.facts.quoted.who': 'First order quoted',
    'lead.facts.quoted': 'price answers that applied it',
    'lead.do.fix': '{title}.',
    'lead.do.none': 'No fix asks for a decision this cycle.',
    'lead.cta.fix': 'Open the fix',
    'lead.cta.answers': 'See the {n} answers',
    'lead.kicker': 'From {n} unprompted answers',
    # the fix queue (beside console_seller's)
    'fix.access.title': 'Open a verified-agent path at the edge',
    'fix.access.detail': '{who} {verb} turned away at {domain}. Signed agents should get the catalog.',
    'fix.rx.title': 'Attach the Rx first-order terms to {product}',
    'fix.rx.detail': '{n} Rx {skus} {verb} at list price only (rule s3) until Pricing picks one first-order term.',
    'fix.rx.conflict': '{product} is Rx and no program excludes it. Pick one term and publish it.',
    'fix.orders.title': 'Connect order data for Impact',
    'fix.orders.detail': 'Until then the dollars on Impact are modeled from public inputs and labeled that way.',
    'state.queued': 'Queued',
    # the Overview's actions
    'action.fix': '{title}',
    'action.approval': 'Sign rule {code}: {title}',
    'action.send': 'Send the held files, {n} SKUs on {surfaces} surfaces',
    'action.who.team': '{name_s} team',
    'action.who.approver': 'Approver',
    'activity.compiled': '{n} SKUs compiled for {surfaces}, held for {name_s} team',
    'activity.sent': '{who} says it sent the {channel} file',
    'activity.signed': '{by} signed rule {code}, {title}',
    'activity.mcp': 'MCP endpoint read back: {verdict} {verified}',
    'week.store': '{name} was named in {named} of {n} unprompted answers and recommended first in {k}, against {rival_s} {r}.',
    'week.missing': '{missed} of {asked} price answers left the first-order price out.',
    'week.funded': "{funder_s} ladder was applied in {k} of {n} answers about the SKUs it funds.",
    'week.retired': '{k} answers still said {former}.',
    'week.access': '{n} agent {identities} turned away at the edge.',
    'week.release': '{n} SKUs compiled for {surfaces} surfaces and held for {name_s} team.',
    'revenue.mode_note': ("Retail mode: {name} sets its own prices and programs. Revenue is modeled from these answers, "
                          "not measured from {name} orders."),
}
T = RETAIL_TEMPLATES

VERDICT_WORD = {'approved': 'verified', 'disapproved': 'disagrees', 'unavailable': 'not reachable'}
CHECK = {'approved': 'verified', 'disapproved': 'disagrees', 'unavailable': 'not_reachable'}


def _p(name: str) -> str:
    return cs._possessive(name)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _dec(v):
    return cs._dec(v)


# ─── the hold, per SKU ────────────────────────────────────────────────────

def hold(pubs: List[dict]) -> Dict[str, Dict[str, dict]]:
    """{record_ref: {channel: its newest row}} on every seller channel. A seller's held rows are per SKU
    (`feed:<slug>:<variant_id>`), so a record is a SKU."""
    out: Dict[str, Dict[str, dict]] = {}
    for slug in CHANNEL_ORDER:
        for row in manu.latest_by_record(pubs, slug):
            ref = row.get('record_ref')
            if ref:
                out.setdefault(ref, {})[slug] = row
    return out


def ref_of(row: dict, slug: str) -> str:
    return f"feed:{slug}:{row.get('variant_id') or ('sku:' + str(row.get('sku')))}"


def _sent_by_channel(pubs: List[dict]) -> Dict[str, dict]:
    out = {}
    for e in manu.journal(pubs):
        if e.get('event') == manu.SENT and e.get('channel') and e.get('channel') not in out:
            out[e['channel']] = e
    return out


def _mcp(held: Optional[dict]) -> dict:
    return (((held or {}).get('published') or {}).get('mcp')) or {}


def _verified(held: Optional[dict]) -> Optional[str]:
    m = _mcp(held)
    return m.get('verified_skus') if m.get('acceptance') else None


def channel_states(*, surfaces: List[dict], per_sku: Dict[str, Dict[str, dict]], refs: List[str],
                   channels: List[dict], held: Optional[dict], pubs: List[dict]) -> List[dict]:
    """
    Every channel, in the demo's retail order, as the matrix's columns, the
    workspace's and the release card's surfaces read it: {id, channel, name,
    spec, state (held | live | blocked | not_for_seller | not_compiled),
    label, line, reason, rule, note, in_pass, check, check_reason, compiled,
    of, blocked, sent}. Counts are SKUs.
    """
    specs = {c.get('slug'): c for c in channels or []}
    sent = _sent_by_channel(pubs)
    mcp = _mcp(held)
    out = []
    for sf in surfaces:
        slug = sf['channel']
        rows = [per_sku.get(r, {}).get(slug) for r in refs]
        compiled = sum(1 for r in rows if r and (manu.is_held(r) or r.get('status') == manu.LIVE_STATUS))
        blocked = sum(1 for r in rows if r and manu.is_blocked(r))
        state = sf['status']
        day = manu.short_day(max((str(r.get('compiled_at')) for r in rows if r and r.get('compiled_at')), default=None))
        check, check_reason = None, None
        if state == 'held' and slug in sent:
            line = T['channel.line.sent'].format(n=compiled, of=len(refs), sent=manu.short_day(
                sent[slug].get('sent_at') or sent[slug].get('at')))
            label = T['channel.sent']
        elif state == 'held':
            line, label = T['channel.line.held'].format(n=compiled, of=len(refs), day=day), T['channel.held']
        elif state == 'live':
            verified = mcp.get('verified_skus')
            check = CHECK.get(mcp.get('acceptance')) or 'unverified'
            check_reason = mcp.get('reason')
            line = T['channel.line.live'].format(n=compiled, verified=verified) if verified else \
                T['channel.line.live.unverified'].format(n=compiled)
            label = T['channel.live']
        elif state == 'blocked':
            line, label = sf.get('note') or T['channel.line.blocked'], T['channel.blocked']
        elif state == 'not_for_seller':
            line, label = T['channel.line.not_for_seller'], T['channel.not_for_seller']
        else:
            line, label = '', T['channel.not_compiled']
        out.append({'id': slug, 'channel': slug, 'name': CHANNEL_SHORT.get(slug, sf['name']), 'full_name': sf['name'],
                    'spec': (specs.get(slug) or {}).get('spec_version') or '', 'state': state, 'label': label,
                    'line': line, 'reason': sf.get('reason'), 'rule': None, 'note': sf.get('note'),
                    'in_pass': state in ('held', 'live', 'blocked'), 'check': check, 'check_reason': check_reason,
                    'compiled': compiled, 'of': len(refs), 'blocked': blocked, 'sent': (sent.get(slug) or {}).get('sent_at')})
    return out


# ─── the path's elements and 2V-1's table ─────────────────────────────────

def elements(path: Optional[dict]) -> List[str]:
    """The elements of a SKU's price path (price_path_carry.ELEMENTS), in order."""
    path = path or {}
    steps = path.get('steps') or []
    found = set()
    if any(s.get('order_n') == '1' for s in steps):
        found.add('first_order')
    if any(s.get('order_n') in ('2', '3') for s in steps):
        found.add('later_steps')
    if path.get('ongoing'):
        found.add('ongoing')
    if path.get('member'):
        found.add('member')
        if path['member'].get('stackable') is False:
            found.add('not_stackable')
    priced = steps + ([path['ongoing']] if path.get('ongoing') else [])
    if any(s.get('funded_by') for s in priced):
        found.add('funded_by')
    if any(s.get('valid_until') for s in priced):
        found.add('valid_until')
    return [e for e in ELEMENT_NAMES if e in found]


def carriage(slug: str, element: str) -> str:
    """carried | approximated | dropped for one channel and element; carried when 2V-1's table has no row for it."""
    cell = (CARRIAGE.get(slug) or {}).get(element)
    return cell[0] if cell else 'carried'


# ─── the matrix ───────────────────────────────────────────────────────────

def _prices(text: str) -> List[Decimal]:
    return cs._prices_in(text)


def path_prices(path: Optional[dict]) -> set:
    path = path or {}
    found = {_dec(path.get('list_price'))}
    for s in (path.get('steps') or []) + [path.get('ongoing'), path.get('member')]:
        if s and s.get('price') is not None:
            found.add(_dec(s['price']))
    return {p for p in found if p is not None}


def drift_lines(row: dict, price_answers: List[dict], program: str) -> List[dict]:
    """
    The price answers about one SKU, each against its path: {agent, fact, run,
    said, truth, surface, variant, verdict}. 2V-5 (W4): an answer is about the
    SKU when its question is coded to it (console_seller.coded_to), not when
    its text names the product's first words: "Purina Pro Plan" joined every
    Pro Plan bag's and every comparison's prices to the 30 lb row. right:
    quoted the first-order price (or, with no step, the list price); partial:
    the list price, the first order left out; wrong: a price on no step; missed:
    no price.
    """
    path = row.get('price_path') or {}
    first = next((s for s in path.get('steps') or [] if s.get('order_n') == '1'), None)
    lst = _dec(path.get('list_price'))
    truth = T['drift.truth.first'].format(first=cs.money(first['price']), program=program, lst=cs.money(lst)) if first \
        else T['drift.truth.list'].format(lst=cs.money(lst))
    out = []
    for a in price_answers:
        if not cs.coded_to(a, row):
            continue
        quoted = _prices(a.get('text') or '')
        if first and _dec(first['price']) in quoted or not first and lst in quoted:
            verdict = 'right'
        elif first and lst in quoted:
            verdict = 'partial'
        elif quoted:
            verdict = 'wrong'
        else:
            verdict = 'missed'
        out.append({'agent': a.get('agent'), 'fact': 'price', 'run': f"run-{a['run_id']}" if a.get('run_id') else None,
                    'said': ', '.join(cs.money(p) for p in quoted[:3]) or T['drift.no_price'], 'truth': truth,
                    'surface': None, 'variant': row.get('variant_id'), 'verdict': verdict})
    order = {'wrong': 0, 'partial': 1, 'missed': 2, 'right': 3}
    return sorted(out, key=lambda l: order[l['verdict']])


def cell_of(slug: str, row: Optional[dict], channel: dict, *, path: dict, name: str, sent: Optional[dict],
            rx_held: bool) -> dict:
    """One SKU's cell on one channel: {s, disagree, at, publication_id, note} in the seller's states and reasons."""
    if channel['state'] == 'not_for_seller':
        return {'s': 'not_for_seller', 'disagree': None, 'at': None, 'publication_id': None,
                'note': T['cell.not_for_seller']}
    state = rel.cell_state(row)
    if state == 'published':
        state = 'live'
    note = None
    if state == 'held':
        note = T['cell.sent'].format(who=sent.get('stated_by') or name, day=manu.short_day(sent.get('sent_at'))) if sent \
            else T['cell.rx'] if rx_held else T['cell.held'].format(name_s=_p(name))
    elif state == 'live':
        note = T['cell.live']
    elif state == 'blocked':
        note = (row or {}).get('spec_clause') or next(iter(((row or {}).get('validation') or {}).get('errors') or []), None)
    return {'s': state, 'disagree': None, 'at': (row or {}).get('compiled_at'), 'publication_id': (row or {}).get('id'),
            'note': note}


def compiler_lines(slug: str, row: dict, *, path: dict, spec: str, rules: Optional[List[dict]]) -> dict:
    """One channel's compiler panel for one SKU: its spec, its one-line rule, the seller rules, and the lines:
    carried (validated), the validator's errors, supply's flags, and the path's elements by 2V-1's table."""
    lines, off = [], []
    if manu.is_valid(row):
        carried = cs._fields(slug, [row])
        if carried:
            lines.append({'mark': 'carried', 'field': carried, 'note': T['compiler.carried'].format(spec=spec)})
    for err in (row.get('validation') or {}).get('errors') or ([row['error']] if row.get('error') else []):
        lines.append({'mark': 'conflict', 'field': 'validation', 'note': str(err)})
    flagged = set()
    for e in row.get('expressiveness') or []:
        field = str(e.get('field') or '')
        m = re.match(r'^rule_(s\d+)$', field)
        if m:
            off.append(m.group(1))
            continue
        if field.startswith('price_path.'):
            flagged.add(field[len('price_path.'):])
        lines.append({'mark': rel.MARKS.get(e.get('severity'), 'info'), 'field': field, 'note': e.get('note')})
    if slug in CARRIAGE:
        for element in elements(path):
            if element in flagged:
                continue
            cell = CARRIAGE[slug].get(element)
            if cell is None:
                lines.append({'mark': 'carried', 'field': f"price_path.{element}",
                              'note': T['compiler.table'].format(note=f"{ELEMENT_NAMES[element]}, carried natively.")})
            else:
                lines.append({'mark': cell[0], 'field': f"price_path.{element}",
                              'note': T['compiler.table'].format(note=cell[1])})
    on = [r.get('code') for r in rules or [] if r.get('on') and r.get('code') not in off]
    relevant = [c for c in SELLER_RULES if any(r.get('code') == c for r in rules or [])]
    applied = [c for c in relevant if c in on]
    return {'channel': slug, 'name': CHANNEL_SHORT.get(slug, slug), 'spec_version': spec,
            'rule': T.get(f'compiler.rule.{slug}'), 'rules_relevant': relevant, 'rules_applied': applied,
            'rules_line': rel.rules_line(relevant, applied), 'state': rel.cell_state(row),
            'spec_clause': row.get('spec_clause'), 'lines': lines}


def sku_timeline(rows: Dict[str, dict], *, name: str, held: Optional[dict], lines: List[dict],
                 cycle: Optional[dict], pubs: List[dict]) -> List[dict]:
    """The SKU's history, oldest first: the readback of the cycle's answers, the compile and its hold, the MCP
    readback, any send the seller stated."""
    out = []
    if cycle is not None and lines:
        k = sum(1 for l in lines if l['verdict'] == 'right')
        out.append({'at': str(cycle.get('start_date') or ''), 'what': T['timeline.readback'].format(k=k, n=len(lines)),
                    'tone': 'ok' if k == len(lines) else 'bad', 'cycle': cycle.get('cycle_code')})
    compiled = [e for r in rows.values() for e in r.get('journal') or [] if e.get('event') == 'compiled']
    if compiled:
        held_on = [CHANNEL_SHORT.get(s, s) for s, r in rows.items() if manu.is_held(r)]
        live = any(r.get('status') == manu.LIVE_STATUS for r in rows.values())
        out.append({'at': max(str(e.get('at') or '') for e in compiled), 'tone': 'blue',
                    'what': T['timeline.compiled'].format(held=manu._and(held_on) or 'no surface', name_s=_p(name),
                                                          live=T['timeline.compiled.live'] if live else '')})
    mcp = _mcp(held)
    if mcp.get('acceptance') and 'mcp' in rows:
        out.append({'at': mcp.get('verified_at') or mcp.get('published_at'), 'tone': 'ok' if mcp['acceptance'] == 'approved'
                    else 'bad', 'what': T['timeline.readback.mcp'].format(
                        verdict=VERDICT_WORD.get(mcp['acceptance'], mcp['acceptance']), verified=mcp.get('verified_skus') or '')
                    .strip()})
    for e in manu.journal(rows.values()):
        if e.get('event') == manu.SENT:
            out.append({'at': e.get('sent_at') or e.get('at'), 'tone': 'ok', 'what': T['timeline.sent'].format(
                who=e.get('stated_by') or name, channel=CHANNEL_SHORT.get(e.get('channel'), e.get('channel')))})
    out = [e for e in out if e.get('at')]
    out.sort(key=lambda e: str(e['at']))
    for e in out:
        e['day'] = manu.short_day(e['at'])
    return out


def build_records(*, paths: List[dict], held_paths: List[dict], pubs: List[dict], states: List[dict],
                  channels: List[dict], rules: Optional[List[dict]], name: str, slug: str, held: Optional[dict],
                  cycle: Optional[dict], price_answers: List[dict], agents: Iterable[str], merchant: str,
                  feed_rows: Optional[List[dict]] = None, owned: Optional[List[dict]] = None) -> List[dict]:
    """The matrix, one row per SKU (the price path's), on the eight channels:
    {record_ref, sku, name, brand, sub, variants, retired, successor, disagree,
    cells, record (the offer record with the price path), drift, drift_all,
    timeline, compiler}, in the brand page's shape (console_release.build_records)."""
    per_sku = hold(pubs)
    specs = {c.get('slug'): c.get('spec_version') for c in channels or []}
    by_channel = {c['channel']: c for c in states}
    held_by_sku = {str(h.get('sku')): h for h in held_paths or []}
    sent = _sent_by_channel(pubs)
    s3 = cs._rule(rules, 's3')
    agents = list(agents)
    out = []
    for row in paths:
        ref = ref_of(row, slug)
        rows = per_sku.get(ref, {})
        path = row.get('price_path') or {}
        held_path = (held_by_sku.get(str(row.get('sku'))) or {}).get('price_path') or path
        program = cs._program(next((s.get('program_name') for s in (path.get('steps') or []) +
                                    [path.get('ongoing') or {}] if s.get('program_name')), None), merchant) or 'program'
        lines = drift_lines(row, price_answers, program)
        dis = rel.disagree(lines, agents)
        rx_held = bool(path.get('rx')) and bool((s3 or {}).get('on'))
        cells = {}
        for slug_ in CHANNEL_ORDER:
            ch = by_channel.get(slug_)
            if ch is None:
                continue
            cells[slug_] = cell_of(slug_, rows.get(slug_), ch, path=path, name=name, sent=sent.get(slug_),
                                   rx_held=rx_held)
            if cells[slug_]['s'] not in ('na', 'not_for_seller'):
                cells[slug_]['disagree'] = dis['agents']
        feed_row = next((f for f in feed_rows or [] if str(f.get('sku')) == str(row.get('sku'))), None)
        record = cs.build_record(row=row, feed_row=feed_row, name=name, merchant=merchant, sent=manu.first_sent(pubs),
                                 held_any=any(manu.is_held(p) for p in pubs), owned=owned)
        out.append({
            'record_ref': ref, 'sku': str(row.get('sku') or ref), 'name': record['title'],
            'brand': (feed_row or {}).get('brand_name') or (feed_row or {}).get('brand'), 'sub': record['sub'],
            'variants': [{'variant_id': row.get('variant_id'), 'sku': row.get('sku'), 'label': row.get('title') or '',
                          'count': None, 'gtin': row.get('gtin') or (feed_row or {}).get('gtin'), 'weight': None,
                          'status': 'active'}],
            'retired': False, 'successor': None, 'disagree': dis, 'cells': cells,
            'record': [{'k': f['k'], 'v': f['v'], 'prov': f.get('prov') or 'retail', 'note': f.get('note')}
                       for f in record['fields']],
            'drift': rel.drift_rows(lines), 'drift_all': lines,
            'timeline': sku_timeline(rows, name=name, held=held, lines=lines, cycle=cycle, pubs=pubs),
            'compiler': [compiler_lines(s, r, path=held_path, spec=specs.get(s) or r.get('spec_version') or '',
                                        rules=rules)
                         for s, r in sorted(rows.items(), key=lambda kv: CHANNEL_ORDER.index(kv[0]))
                         if s not in PARLEO_PUBLISHED],
        })
    return out


def fields_count(records: List[dict], states: List[dict]) -> dict:
    """{carried, approximated, dropped}: 2V-5 (W3) the compiler block's own lines, counted on every SKU's panel of
    every channel held for the seller's team (build_records' `compiler`, the lines the screen renders), so a line
    marked dropped is a dropped count. Before, each SKU's path elements were counted by the best any held channel
    did, which read "0 dropped by spec" above GMC's `price_path.later_steps · dropped`."""
    held_on = {c['channel'] for c in states if c['state'] == 'held'}
    counts = {'carried': 0, 'approximated': 0, 'dropped': 0}
    for r in records:
        for panel in r.get('compiler') or []:
            if panel['channel'] in held_on:
                for line in panel['lines']:
                    if line['mark'] in counts:
                        counts[line['mark']] += 1
    return counts


def build_workspace(*, records: List[dict], states: List[dict], held: Optional[dict], name: str) -> dict:
    """The demo's "This workspace today" in SKUs: compiled of SKUs x channels compiled, published (served by
    Parleo), blocked, the path's fields carried / approximated / dropped, SKUs where agents disagree, last
    verified (the MCP readback), next check (no schedule exists: None)."""
    in_pass = [c for c in states if c['in_pass']]
    mcp = _mcp(held)
    verified = mcp.get('verified_at') if mcp.get('acceptance') else None
    return {
        'records': len(records), 'lines': len(records),
        'compiled': {'n': sum(c['compiled'] for c in in_pass), 'of': len(records) * len(in_pass)},
        'published': sum(c['compiled'] for c in states if c['state'] == 'live'),
        'live': sum(c['compiled'] for c in states if c['state'] == 'live'),
        'blocked': sum(c['blocked'] for c in states),
        'channels': {s: sum(1 for c in states if c['state'] == s)
                     for s in ('held', 'live', 'blocked', 'not_for_seller', 'not_compiled')},
        'fields': fields_count(records, states),
        'fields_label': {k: T[f'workspace.fields.{k}'] for k in ('carried', 'approximated', 'dropped')},
        'compiled_label': T['workspace.compiled'].format(skus=len(records), surfaces=len(in_pass)),
        'disagree': sum(1 for r in records if r['disagree']['agents']),
        'walled': {'n': 0, 'domains': []},
        'last_verified': verified, 'last_verified_day': manu.short_day(verified),
        'next_check': None,
        'surfaces': [dict(c) for c in states],
        'mode_note': T['workspace.mode_note'].format(name_s=_p(name)),
    }


def release_status(c: dict, day: Optional[str]) -> str:
    if c['state'] == 'held' and c.get('sent'):
        return T['release.surface.sent'].format(day=manu.short_day(c['sent']))
    if c['state'] == 'held':
        return T['release.surface.held'].format(day=day)
    if c['state'] == 'live':
        return T['release.surface.live'].format(line=c['line'])
    if c['state'] == 'blocked':
        return T['release.surface.blocked'].format(day=day)
    if c['state'] == 'not_for_seller':
        return T['release.surface.not_for_seller']
    return T['release.surface.out']


def build_release(*, pubs: List[dict], states: List[dict], rules: Optional[List[dict]], name: str, skus: int,
                  held: Optional[dict]) -> Optional[dict]:
    """The newest compile and hold as the current release, in the brand page's shape (console_release.build_release):
    {name, compiled_at, day, rules_on, products, surfaces_held, approved_by (2V-5: approved_by()),
    requested, status, surfaces[] with spec versions, notes, channels}."""
    compiles = rel._compiles(pubs)
    if not compiles:
        return None
    newest = compiles[-1]
    day = manu.short_day(newest['compiled_at'])
    sent = manu.first_sent(pubs)
    # the card's count (console_seller.release_card): the surfaces held for the seller's team
    holding = [c for c in states if c['state'] == 'held']
    mcp = _mcp(held)
    return {
        'name': T['release.name'].format(n=skus, name=name, surfaces=len(holding)), 'named': False,
        'compiled_at': newest['compiled_at'], 'day': day,
        'rules_on': {'on': sum(1 for r in rules or [] if r.get('on')), 'of': len(rules or [])} if rules is not None else None,
        'products': skus, 'surfaces_held': sum(1 for c in states if c['state'] == 'held'),
        'approved_by': approved_by(rules), 'requested': newest['by'],
        'status': T['release.status.sent'].format(who=sent.get('stated_by')) if sent else T['release.status.held'],
        'surfaces': [{'channel': c['channel'], 'name': c['name'], 'spec_version': c['spec'],
                      'status': release_status(c, day), 'state': c['state'], 'in_pass': c['in_pass']} for c in states],
        'notes': [T['release.note.account'].format(name_s=_p(name)),
                  T['release.note.verify'].format(verified=mcp.get('verified_skus')) if mcp.get('acceptance') == 'approved'
                  else T['release.note.verify.none']],
        'channels': {c['channel']: c['spec'] for c in states if c['in_pass']},
    }


def approved_by(rules: Optional[List[dict]]) -> Optional[str]:
    """2V-5 (W5): the release's approver. A seller's release is gated by its rules s1..s6, each signed on supply's
    record (`approved_by`): the signer when every rule is signed by one person, else "{k} of {n} signed"; None
    (the screen's dash) only when nothing is signed."""
    gating = [r for r in rules or [] if r.get('code') in SELLER_RULES]
    signed = [r for r in gating if r.get('approval') == 'approved']
    if not signed:
        return None
    signers = {r.get('approved_by') for r in signed}
    if len(signed) == len(gating) and len(signers) == 1 and None not in signers:
        return signers.pop()
    return T['release.signed'].format(k=len(signed), n=len(gating))


def build_releases(*, pubs: List[dict], feed_version: Optional[dict], rules: Optional[List[dict]],
                   held: Optional[dict]) -> List[dict]:
    """console_release.build_releases, with a seller's approvals (its signed rules) and verification (the MCP
    readback) on the current one."""
    out = rel.build_releases(pubs=pubs, feed_version=feed_version, rules=rules)
    mcp = _mcp(held)
    signed = sum(1 for r in rules or [] if r.get('approval') == 'approved')
    for r in out:
        r['approvals'] = T['releases.approvals'].format(k=signed, n=len(rules or [])) if r['current'] else r['approvals']
        if r['current']:
            r['verification'] = T['releases.verify.mcp'].format(
                verdict=VERDICT_WORD.get(mcp['acceptance'], mcp['acceptance']), verified=mcp.get('verified_skus') or '') \
                .strip() if mcp.get('acceptance') else T['releases.verify.none']
    return out


# ─── the record's issues ──────────────────────────────────────────────────

def _offer_prices(payload: Optional[dict]) -> tuple:
    """(prices, has validThrough) of a schema.org payload's Offer and its priceSpecification."""
    offers = (payload or {}).get('offers') or {}
    offers = offers if isinstance(offers, list) else [offers]
    found, through = set(), False
    for o in offers:
        if not isinstance(o, dict):
            continue
        found.add(_dec(o.get('price')))
        through = through or bool(o.get('priceValidUntil') or o.get('validThrough'))
        specs = o.get('priceSpecification') or []
        for s in specs if isinstance(specs, list) else [specs]:
            if isinstance(s, dict):
                found.add(_dec(s.get('price')))
                through = through or bool(s.get('validThrough'))
    return {p for p in found if p is not None}, through


def _page_offer(row: dict) -> tuple:
    """A page read's JSON-LD Offer prices and validThrough, as _offer_prices reads a payload."""
    found, through = set(), False
    blocks = row.get('json_ld')
    for b in blocks if isinstance(blocks, list) else [blocks] if blocks else []:
        if isinstance(b, dict):
            p, t = _offer_prices(b)
            found |= p
            through = through or t
    return found, through


def own_page_rows(reference: Optional[dict], row: dict, domain: Optional[str]) -> List[dict]:
    """supply's /reference reads of the SKU's own page (the seller's domain), newest first."""
    out = []
    for r in (reference or {}).get('rows') or []:
        on_domain = domain and str(r.get('retailer_domain') or '').lower().removeprefix('www.') == domain
        keyed = str(r.get('sku') or '') == str(row.get('sku')) or r.get('variant_id') == row.get('variant_id') or \
            (row.get('product_url') and r.get('url') == row.get('product_url'))
        if (r.get('role') == 'own' or on_domain) and keyed:
            out.append(r)
    return sorted(out, key=lambda r: str(r.get('observed_at') or ''), reverse=True)


def build_issues(*, row: dict, held_rows: Dict[str, dict], feed_row: Optional[dict], feed_version: Optional[dict],
                 page_rows: List[dict], loyalty: Optional[dict], owned: List[dict], rules: Optional[List[dict]],
                 name: str, merchant: str, domain: Optional[str]) -> List[dict]:
    """
    The offer record's issues, each {code, title, detail, tone, source: {kind,
    label, url, at}} with the demo's wording and the source that proves it:

      first_order   the first-order price is in no markup: the page read's Offer
                    has list price only, or the held markup has none (s1 off)
      program       the ongoing program price is description text in the held markup
      ladder        a funded step's end date is on no Offer (held markup or page)
      gtin          no GTIN in the feed
      page          the page read differs from the feed: name, price, size
      retired       the page read still carries a former program name
      rx            an Rx SKU whose first program step applies (no exclusion)
    """
    path = row.get('price_path') or {}
    steps = path.get('steps') or []
    first = next((s for s in steps if s.get('order_n') == '1'), None)
    program = cs._program((first or path.get('ongoing') or {}).get('program_name'), merchant) or 'program'
    page = page_rows[0] if page_rows else None
    page_src = {'kind': 'page', 'label': T['issue.source.page'].format(domain=domain or 'the page', day=manu.short_day(
        page.get('observed_at'))), 'url': page.get('url'), 'at': page.get('observed_at')} if page else None
    markup = held_rows.get('schema_org')
    held_src = {'kind': 'held', 'label': T['issue.source.held'].format(channel='site markup', day=manu.short_day(
        markup.get('compiled_at'))), 'url': None, 'at': markup.get('compiled_at')} if markup else None
    held_prices, held_through = _offer_prices((markup or {}).get('payload'))
    out = []
    if first:
        price = cs.money(first['price'])
        if page is not None:
            prices, _t = _page_offer(page)
            if prices and _dec(first['price']) not in prices:
                out.append({'code': 'first_order', 'title': T['issue.first_order.page'], 'tone': 'bad', 'source': page_src,
                            'detail': T['issue.first_order.page.detail'].format(domain=domain or 'The page', price=price)})
        if not any(i['code'] == 'first_order' for i in out) and markup and _dec(first['price']) not in held_prices:
            s1 = cs._rule(rules, 's1') or {}
            out.append({'code': 'first_order', 'title': T['issue.first_order.page'], 'tone': 'bad', 'source': held_src,
                        'detail': T['issue.first_order.held.detail'].format(
                            state='on' if s1.get('on') else 'off', price=price)})
    ongoing = path.get('ongoing')
    if ongoing and markup and _dec(ongoing.get('price')) not in held_prices:
        out.append({'code': 'program', 'title': T['issue.program.title'], 'tone': 'warn', 'source': held_src,
                    'detail': T['issue.program.detail'].format(program=cs._program(ongoing.get('program_name'), merchant),
                                                              price=cs.money(ongoing['price']))})
    funded = next((s for s in steps if s.get('funded_by') and s.get('valid_until')), None)
    if funded:
        through = _page_offer(page)[1] if page is not None else held_through
        if (page is not None or markup) and not through:
            out.append({'code': 'ladder', 'title': T['issue.ladder.title'], 'tone': 'warn',
                        'source': page_src if page is not None else held_src,
                        'detail': T['issue.ladder.detail'].format(day=manu.short_day(cs._until(funded)),
                                                                 funder=cs._funder(funded['funded_by']))})
    if not ((feed_row or {}).get('gtin') or row.get('gtin')):
        version = (feed_version or {}).get('version_number')
        out.append({'code': 'gtin', 'title': T['issue.gtin.title'], 'tone': 'warn',
                    'detail': T['issue.gtin.detail'].format(name_s=_p(name)),
                    'source': {'kind': 'feed', 'label': T['issue.source.feed'].format(
                        name_s=_p(name), version=f", version {version}" if version is not None else ''),
                        'url': None, 'at': (feed_version or {}).get('committed_at')}})
    if page is not None:
        diffs = []
        for f in page.get('findings') or []:
            kind = f.get('finding')
            if kind in ('name_differs', 'size_differs', 'pack_differs'):
                diffs.append((kind.split('_')[0], f.get('observed'), f.get('expected')))
        lst = _dec(path.get('list_price'))
        seen = _dec(page.get('price'))
        if lst is not None and seen is not None and seen != lst:
            diffs.append(('price', cs.money(seen), cs.money(lst)))
        if diffs:
            out.append({'code': 'page', 'title': T['issue.page.title'].format(what=manu._and([d[0] for d in diffs])),
                        'tone': 'warn', 'source': page_src,
                        'detail': ' '.join(T['issue.page.detail'].format(domain=domain or 'The page',
                                                                         said=f'"{d[1]}"' if d[1] else 'nothing',
                                                                         feed=f'"{d[2]}"' if d[2] else 'nothing')
                                           for d in diffs)})
        former = [n for n in (loyalty or {}).get('former_names') or [] if n and n.casefold() in repr(
            {k: page.get(k) for k in ('json_ld', 'title', 'text', 'bullets', 'name')}).casefold()]
        if former:
            out.append({'code': 'retired', 'title': T['issue.retired.title'], 'tone': 'warn', 'source': page_src,
                        'detail': T['issue.retired.detail'].format(former=manu._and([f'"{n}"' for n in former]),
                                                                  current=(loyalty or {}).get('name'))})
    excluded = any('rx' in str(n.get('reason') or '').lower() for n in path.get('not_applied') or [])
    if path.get('rx') and first and not excluded:
        out.append({'code': 'rx', 'title': T['issue.rx.title'], 'tone': 'bad',
                    'detail': T['issue.rx.detail'].format(product=row.get('product_name') or row.get('sku'), program=program),
                    'source': {'kind': 'programs', 'label': T['issue.source.programs'].format(name_s=_p(name)),
                               'url': None, 'at': None}})
    return out


# ─── signals ──────────────────────────────────────────────────────────────

def unprompted_counts(vis: Optional[dict]) -> Optional[dict]:
    """Visibility's unprompted read: {n, named, first (us), rivals: [(name, first)], ours}, every agent together."""
    rows = [r for r in (vis or {}).get('byQuestion') or [] if r.get('unprompted') and r.get('answered')]
    ours = next((r['name'] for r in ((vis or {}).get('ranking') or {}).get('rows') or [] if r.get('you')), None)
    if not rows or not ours:
        return None
    # each row's named [{name, you}] and first {name, you} (console_read_models._visibility_run)
    first = Counter((r.get('first') or {}).get('name') for r in rows if (r.get('first') or {}).get('name'))
    named = sum(1 for r in rows if any(n.get('you') for n in r.get('named') or []))
    rivals = [(n, c) for n, c in first.most_common() if n != ours]
    return {'n': len(rows), 'named': named, 'first': first.get(ours, 0), 'rivals': rivals, 'ours': ours}


def store_signal(counts: Optional[dict], name: str) -> Optional[dict]:
    """Agents name the seller, then recommend another store first: its unprompted first picks below a rival's."""
    if not counts or not counts['rivals'] or counts['rivals'][0][1] <= counts['first']:
        return None
    rival, r = counts['rivals'][0]
    # the entity Visibility counted as ours (the study's primary), which for a seller's own study is the seller
    name = counts.get('ours') or name
    return {'id': 'another_store_first', 'rule': 'another_store_first', 'kind': 'store', 'pool': 'lost',
            'title': T['signal.store.title'].format(name=name, rival=rival),
            'detail': T['signal.store.detail'].format(name=name, rival=rival, k=counts['first'], n=counts['n'], r=r,
                                                     named=counts['named']),
            'tag': T['signal.store.tag'], 'tone': 'bad', 'count': r - counts['first'], 'route': 'visibility',
            'facts': {'name': name, 'rival': rival, 'k': counts['first'], 'r': r, 'n': counts['n']}, 'narrative': None}


def missing_signal(*, paths: List[dict], price_answers: List[dict], name: str, program: str) -> Optional[dict]:
    stepped = [r for r in paths if (r.get('price_path') or {}).get('steps')]
    if not stepped or not price_answers:
        return None
    missed = [a for a in price_answers if not cs.quoted_first_order(a, paths)]
    if not missed:
        return None
    return {'id': 'program_price_missing', 'rule': 'program_price_missing', 'kind': 'price', 'pool': 'missed',
            'title': T['signal.missing.title'].format(program=program, name=name),
            'detail': T['signal.missing.detail'].format(missed=len(missed), asked=len(price_answers)),
            'tag': T['signal.missing.tag'], 'tone': 'bad', 'count': len(missed), 'route': 'true-value',
            'facts': {'missed': len(missed), 'asked': len(price_answers)}, 'narrative': None}


def misstated_signal(*, paths: List[dict], answers: List[dict], name: str, program: str) -> Optional[dict]:
    """Answers that name the program on a SKU and quote a price on no step of its path."""
    if not program:
        return None
    word = program.casefold()
    bad = [a for a in answers for r in paths if r.get('price_path', {}).get('steps') and cs.mentions(a, r)
           and word in (a.get('text') or '').casefold() and _prices(a.get('text') or '')
           and not set(_prices(a.get('text') or '')) & path_prices(r.get('price_path'))]
    k = len({a.get('run_id') for a in bad})
    if not k:
        return None
    return {'id': 'program_price_misstated', 'rule': 'program_price_misstated', 'kind': 'price', 'pool': 'missed',
            'title': T['signal.misstated.title'].format(program=program, name=name),
            'detail': T['signal.misstated.detail'].format(k=k, program=program, name=name),
            'tag': T['signal.misstated.tag'], 'tone': 'bad', 'count': k, 'route': 'answers', 'narrative': None}


def retired_signal(*, answers: List[dict], loyalty: Optional[dict]) -> Optional[dict]:
    former = list((loyalty or {}).get('former_names') or [])
    saying = [a for a in answers if cs.says_former(a, former)]
    if not saying:
        return None
    names = manu._and(sorted({n for a in saying for n in cs.says_former(a, former)}))
    agents = sorted({rm_agent(a.get('agent')) for a in saying if a.get('agent')})
    return {'id': 'retired_program', 'rule': 'retired_program', 'kind': 'retired', 'pool': 'missed',
            'title': T['signal.retired.title'].format(agents=manu._and(agents) or 'Agents',
                                                      say='says' if len(agents) == 1 else 'say', former=names),
            'detail': T['signal.retired.detail'].format(k=len(saying), n=len(answers), former=names,
                                                       current=(loyalty or {}).get('name')),
            'tag': T['signal.retired.tag'], 'tone': 'warn', 'count': len(saying), 'route': 'answers', 'narrative': None}


def funded_signal(*, paths: List[dict], answers: List[dict]) -> Optional[dict]:
    """A brand-funded ladder agents do not apply: of the answers about the SKUs it funds, those that quoted no step."""
    funded = [r for r in paths if ((r.get('price_path') or {}).get('steps') or [{}])[0].get('funded_by')]
    if not funded:
        return None
    about = [a for a in answers if any(cs.mentions(a, r) for r in funded)]
    applied = [a for a in about if any(cs.quoted_step(a, r.get('price_path')) for r in funded)]
    if not about or len(applied) == len(about):
        return None
    first = funded[0]['price_path']['steps'][0]
    funder = cs._funder(first['funded_by'])
    until = cs._until(first)
    return {'id': 'funded_missed', 'rule': 'funded_missed', 'kind': 'funded', 'pool': 'missed',
            'title': T['signal.funded.title'].format(funder_s=_p(funder), ends=f" ends {manu.short_day(until)}" if until else ''),
            'detail': T['signal.funded.detail'].format(k=len(applied), n=len(about), products=manu._and(
                [str(r.get('product_name')) for r in funded][:2])),
            'tag': T['signal.funded.tag'], 'tone': 'warn', 'count': len(about) - len(applied), 'route': 'prove',
            'narrative': None}


def access_signal(access: Optional[dict], domain: Optional[str]) -> Optional[dict]:
    who = [g.get('label') for g in (access or {}).get('problem_identities') or [] if g.get('label')]
    if not who:
        return None
    return {'id': 'access', 'rule': 'access', 'kind': 'access', 'pool': 'root',
            'title': T['signal.access.title'].format(who=manu._and(who[:2]) + (f" and {len(who) - 2} more" if len(who) > 2
                                                                                else ''), domain=domain or 'the site'),
            'detail': T['signal.access.detail'].format(n=len(who), identities=_plural(len(who), 'identity was',
                                                                                     'identities were')),
            'tag': T['signal.access.tag'], 'tone': 'warn', 'count': len(who), 'route': 'accessibility', 'narrative': None}


def rm_agent(agent: Optional[str]) -> str:
    from app.services import console_read_models as rm
    return rm.AGENT_NAMES.get(agent, agent or '')


#: The seller's signal order: another store first, then the price signals, the program name, access; the
#: parity signals after (another brand's price is "Wrong price" in a seller's words).
SIGNAL_ORDER = ('another_store_first', 'program_price_missing', 'program_price_misstated', 'funded_missed',
                'retired_program', 'access')


def rank_signals(existing: List[dict], new: List[Optional[dict]]) -> List[dict]:
    """The seller's signals first, in SIGNAL_ORDER, then the existing ones (console_parity.build_signals), each
    with `rank` and its `tag`; another brand's price reads "Wrong price"."""
    made = sorted([s for s in new if s], key=lambda s: SIGNAL_ORDER.index(s['id']))
    rest = [{**s, 'tag': T['signal.wrong.tag'] if s.get('rule') == 'other_brand' else s.get('tag')} for s in existing]
    return [{**s, 'rank': i + 1} for i, s in enumerate(made + rest)]


def build_lead(signals: List[dict], *, name: str, counts: Optional[dict], fixes: List[dict]) -> Optional[dict]:
    """The demo's hero from the worst signal: the store signal's two tiles (us, the rival, first picks of the
    unprompted answers), else the signal's count; `do` the first fix that waits; no owner is recorded."""
    if not signals:
        return None
    top = signals[0]
    if top['id'] == 'another_store_first':
        f = top['facts']
        facts = [{'who': name, 'value': str(f['k']), 'of': f"of {f['n']}", 'cap': T['lead.facts.cap']},
                 {'who': f['rival'], 'value': str(f['r']), 'of': f"of {f['n']}", 'cap': T['lead.facts.cap']}]
    elif top['id'] == 'program_price_missing':
        f = top['facts']
        facts = [{'who': name, 'value': str(f['missed']), 'of': f"of {f['asked']}", 'cap': T['lead.facts.missing']},
                 {'who': T['lead.facts.quoted.who'], 'value': str(f['asked'] - f['missed']), 'of': f"of {f['asked']}",
                  'cap': T['lead.facts.quoted']}]
    else:
        facts = [{'who': top.get('tag') or name, 'value': str(top.get('count') or 0), 'of': None, 'cap': top['detail']}]
    waiting = next((f for f in fixes if f['state'] == 'needs_decision'), None) or (fixes[0] if fixes else None)
    n = (counts or {}).get('n')
    return {'headline': top['title'], 'kind': top['kind'], 'signal': top['id'], 'pool': top.get('pool'),
            'kicker': T['lead.kicker'].format(n=n) if n else None, 'why': top['detail'],
            'facts': facts, 'do': T['lead.do.fix'].format(title=waiting['title']) if waiting else T['lead.do.none'],
            'owner': None,
            'ctas': [{'label': T['lead.cta.fix'], 'route': 'fixes'},
                     {'label': T['lead.cta.answers'].format(n=n) if n else 'See the answers', 'route': 'answers'}]}


# ─── the Fix queue, beside console_seller.build_fixes ────────────────────

def more_fixes(*, paths: List[dict], rules: Optional[List[dict]], access: Optional[dict], domain: Optional[str],
               issues: Dict[str, List[dict]]) -> List[dict]:
    """
    The fixes the demo's queue has that console_seller does not derive:

      access   agent identities turned away at the edge: open a verified-agent path
      rx       an Rx SKU held at list price by s3, or one no program excludes:
               attach the Rx first-order terms
      orders   no order data reaches Impact (soa holds none): connect it
    """
    out = []
    who = [g.get('label') for g in (access or {}).get('problem_identities') or [] if g.get('label')]
    if who:
        out.append({'id': 'edge_path', 'gate': None, 'title': T['fix.access.title'],
                    'detail': T['fix.access.detail'].format(who=manu._and(who[:3]) + (f" and {len(who) - 3} more"
                                                                                       if len(who) > 3 else ''),
                                                            verb='is' if len(who) == 1 else 'are',
                                                            domain=domain or 'the edge'),
                    'status': 'needs_decision', 'scope': f"{domain or 'the site'} edge", 'tags': ['Edge', 'Web Bot Auth'],
                    'priority': 'High', 'owner': None, 'due': None})
    rx = [r for r in paths if (r.get('price_path') or {}).get('rx')]
    s3 = cs._rule(rules, 's3') or {}
    conflict = [r for r in rx if any(i['code'] == 'rx' for i in issues.get(str(r.get('sku'))) or [])]
    if conflict or (rx and s3.get('on')):
        product = (conflict or rx)[0].get('product_name') or (conflict or rx)[0].get('sku')
        detail = T['fix.rx.conflict'].format(product=product) if conflict else \
            T['fix.rx.detail'].format(n=len(rx), skus=_plural(len(rx), 'SKU', 'SKUs'),
                                      verb='compiles' if len(rx) == 1 else 'compile')
        out.append({'id': 'rx_terms', 'gate': 's3' if not conflict else None, 'title': T['fix.rx.title'].format(product=product),
                    'detail': detail, 'status': 'queued', 'scope': f"{len(rx)} Rx {_plural(len(rx), 'SKU', 'SKUs')}",
                    'tags': ['Offer record'], 'priority': 'Medium', 'owner': None, 'due': None})
    out.append({'id': 'order_data', 'gate': None, 'title': T['fix.orders.title'], 'detail': T['fix.orders.detail'],
                'status': 'queued', 'scope': 'Integration', 'tags': ['Impact'], 'priority': 'Medium', 'owner': None,
                'due': None})
    return out


def finish_fixes(fixes: List[dict]) -> dict:
    """console_seller.build_fixes' numbering, console shape and summary, over the whole queue."""
    for n, f in enumerate(fixes, 1):
        f['n'] = n
        f['state_label'] = T.get(f"state.{f['status']}") or cs.T.get(f"state.{f['status']}", f['status'])
        f['state'] = 'in_flight' if f['status'] == 'held' else f['status']
        f['text'] = f['detail']
        f['surfaces'] = f['tags']
        f['kind'] = f['id']
        f['pool'] = f.get('pool') or ('root' if f['id'] == 'edge_path' else 'both')
        f['severity'] = f['priority']
    waiting = [f for f in fixes if f['state'] == 'needs_decision']
    by_state = {k: sum(1 for f in fixes if f['state'] == k) for k in ('needs_decision', 'in_flight', 'queued', 'shipped')}
    first = waiting[0]['title'] if waiting else None
    hero = (f"{len(waiting)} of {len(fixes)} fixes need a decision." + (f" First up: {first}." if first else '')) if fixes \
        else 'No fix: no rule, answer or held release asks for one this cycle.'
    return {'fixes': fixes, 'summary': {'waiting': len(waiting), 'total': len(fixes), 'by_state': by_state,
                                        'by_pool': dict(Counter(f['pool'] for f in fixes)),
                                        'by_surface': dict(Counter(s for f in fixes for s in f['surfaces'])),
                                        'hero': hero, 'first': first, 'order_note': ''}}


# ─── Approvals ────────────────────────────────────────────────────────────

def rule_fixes(rules: Optional[List[dict]], fixes: List[dict]) -> List[dict]:
    """Every seller rule as fx.build_approvals' input, in s1..s6 order: the fix it gates when one does, else a
    stand-in with no fix (its request carries no fix title)."""
    gated = {f.get('gate'): f for f in fixes if f.get('gate')}
    out = []
    for code in SELLER_RULES:
        rule = cs._rule(rules, code)
        if rule is None:
            continue
        f = gated.get(code)
        out.append({**f, 'pool': 'both'} if f else {'id': None, 'gate': code, 'title': rule.get('name') or code,
                                                    'pool': 'both'})
    return out


# ─── the Overview ─────────────────────────────────────────────────────────

def build_actions(*, fixes: List[dict], rules: Optional[List[dict]], release: Optional[dict], name: str) -> List[dict]:
    """The demo's "Actions this week", derived as brand mode derives its queue: each rule that waits (the
    approver signs it), each fix that needs a decision, the held files ({name}'s team sends them). No owner or due
    date is recorded: `who` is the role, `due` None. {who, initials, what, due, status, route}."""
    out = []
    for r in rules or []:
        if r.get('approval') == 'needs_approval':
            out.append({'who': T['action.who.approver'], 'initials': 'AP', 'what': T['action.approval'].format(
                code=r.get('code'), title=r.get('name')), 'due': None, 'status': 'open', 'route': 'approvals',
                'key': f"rule:{r.get('code')}"})
    for f in fixes:
        if f['state'] == 'needs_decision' and f['id'] != 'release' and not f.get('gate'):
            out.append({'who': T['action.who.approver'], 'initials': 'AP', 'what': T['action.fix'].format(title=f['title']),
                        'due': None, 'status': 'open', 'route': 'fixes', 'key': f"fix:{f['id']}"})
    if release and release.get('state') in ('held', 'sent'):
        out.append({'who': T['action.who.team'].format(name_s=_p(name)), 'initials': name[:2].upper(),
                    'what': T['action.send'].format(n=release.get('products'), surfaces=release.get('held')),
                    'due': None, 'status': 'done' if release['state'] == 'sent' else 'open', 'route': 'publishing',
                    'key': 'release'})
    for r in rules or []:
        if r.get('approval') == 'approved':
            out.append({'who': r.get('approved_by') or 'TrueSync', 'initials': (r.get('approved_by') or 'TS')[:2].upper(),
                        'what': T['action.approval'].format(code=r.get('code'), title=r.get('name')),
                        'due': None, 'status': 'done', 'route': 'approvals', 'key': f"rule:{r.get('code')}",
                        'at': r.get('approved_at')})
    return out


def build_activity(*, cycle: dict, first_at, last_at, answers: int, usable: int, agents: int, questions: int,
                   pubs: List[dict], rules: Optional[List[dict]], held: Optional[dict], states: List[dict],
                   skus: int, name: str) -> List[dict]:
    """The loop's stages and the people's acts, newest first: the study started and complete (brand mode's
    words), the compile and hold, the MCP readback, each rule signed (who, when), each send stated."""
    from app.services import console_brand_overview as bo
    from app.services import console_read_models as rm
    out = [e for e in bo.build_activity(cycle=cycle, first_at=first_at, last_at=last_at, answers=answers, usable=usable,
                                        agents=agents, questions=questions, prices=None, own_domains=(), pubs=[],
                                        workspace=None) if e['stage'] in ('started', 'complete')]
    compiled = [e for p in pubs or [] for e in p.get('journal') or [] if e.get('event') == 'compiled']
    held_on = [c['name'] for c in states if c['state'] == 'held']
    if compiled:
        out.append({'at': max(str(e.get('at') or '') for e in compiled), 'icon': 'publish', 'stage': 'compiled',
                    'text': T['activity.compiled'].format(n=skus, surfaces=manu._and(held_on) or 'no surface',
                                                          name_s=_p(name))})
    mcp = _mcp(held)
    if mcp.get('acceptance'):
        out.append({'at': mcp.get('verified_at') or mcp.get('published_at'), 'icon': 'verify', 'stage': 'readback',
                    'text': T['activity.mcp'].format(verdict=VERDICT_WORD.get(mcp['acceptance'], mcp['acceptance']),
                                                     verified=mcp.get('verified_skus') or '').strip()})
    for r in rules or []:
        if r.get('approval') == 'approved' and r.get('approved_at'):
            out.append({'at': r['approved_at'], 'icon': 'check', 'stage': 'signed',
                        'text': T['activity.signed'].format(by=r.get('approved_by') or 'TrueSync', code=r.get('code'),
                                                            title=r.get('name'))})
    for e in manu.journal(pubs):
        if e.get('event') == manu.SENT:
            out.append({'at': e.get('sent_at') or e.get('at'), 'icon': 'publish', 'stage': 'sent',
                        'text': T['activity.sent'].format(who=e.get('stated_by') or name,
                                                          channel=CHANNEL_SHORT.get(e.get('channel'), e.get('channel')))})
    out = [e for e in out if e.get('at')]
    stages = ('started', 'complete', 'compiled', 'readback', 'signed', 'sent')
    out.sort(key=lambda e: (rm._ts(e['at']), stages.index(e['stage'])), reverse=True)
    seen = set()
    unique = []
    for e in out:
        key = (e['stage'], e['text'])
        if key in seen:
            continue
        seen.add(key)
        e['day'] = manu.short_day(e['at'])
        unique.append(e)
    return unique


def week_in_short(*, counts: Optional[dict], missing: Optional[dict], funded: Optional[dict], funded_counts: tuple,
                  retired: Optional[dict], access: Optional[dict], release: Optional[dict], name: str,
                  former: List[str]) -> List[dict]:
    """The week in lines, in the demo's order: first picks, the first-order price, the ladder, the retired name,
    access, the held release. A line with nothing to count is left out."""
    out = []
    if counts and counts['rivals']:
        rival, r = counts['rivals'][0]
        out.append({'key': 'first', 'route': 'visibility', 'text': T['week.store'].format(
            name=counts.get('ours') or name, named=counts['named'], n=counts['n'], k=counts['first'], rival_s=_p(rival), r=r)})
    if missing:
        out.append({'key': 'first_order', 'route': 'true-value', 'text': T['week.missing'].format(**missing['facts'])})
    k, n, funder = funded_counts
    if n:
        out.append({'key': 'funded', 'route': 'prove', 'text': T['week.funded'].format(funder_s=_p(funder), k=k, n=n)})
    if retired:
        out.append({'key': 'retired', 'route': 'answers', 'text': T['week.retired'].format(
            k=retired['count'], former=manu._and(former))})
    who = (access or {}).get('problem_identities') or []
    if who:
        out.append({'key': 'access', 'route': 'accessibility', 'text': T['week.access'].format(
            n=len(who), identities=_plural(len(who), 'identity was', 'identities were'))})
    if release and release.get('held'):
        out.append({'key': 'release', 'route': 'truesync', 'text': T['week.release'].format(
            n=release.get('products'), surfaces=release.get('held'), name_s=_p(name))})
    return out


def funded_counts(*, paths: List[dict], answers: List[dict]) -> tuple:
    """(applied, answers about, funder) for the first funder's SKUs (console_seller.build_funded_offers' count)."""
    funded = [r for r in paths if ((r.get('price_path') or {}).get('steps') or [{}])[0].get('funded_by')]
    if not funded:
        return 0, 0, ''
    about = [a for a in answers if any(cs.mentions(a, r) for r in funded)]
    applied = [a for a in about if any(cs.quoted_step(a, r.get('price_path')) for r in funded)]
    return len(applied), len(about), cs._funder(funded[0]['price_path']['steps'][0]['funded_by'])
