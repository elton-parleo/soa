"""
2T-8: the Product record of a brand at retail (supply's `mode`
manufacturer), to the console demo's shape (parleohq/truesync console-demo,
data/pg.ts `record`, `products`, issues, and the seed Product record screen).

B1, the markup comparison. A brand page's markup is a ProductGroup with one
Product per variant (`hasVariant`). A feed variant is compared with the page's
variant that is its own: by GTIN (both zero-padded to 14 digits, the 2T-4
digit normalisation, so an 11-digit GTIN finds its 12-digit self), else by
size and pack count, else by size alone when one variant has it. Only fields
both sides carry are compared (GTIN, size, pack count, weight range, the
line's name); a field the markup does not carry is "not in the markup", never
a difference. supply's own-page findings compare a feed row with the group's
first variant (Preemie on every Swaddlers SKU), so on a page with a
ProductGroup these replace them.

B2, the record per feed SKU: `record_list` and `build_product_record`, from
the reads TrueSync's release page already makes (console_release's held
records, master record and readback). B3: the Publishing preview counts SKUs
and the diff's GTIN rows collapse per line. Copy: PRODUCT_RECORD_TEMPLATES.
Shapes: docs/console-read-models.md, "2T-8". Deterministic; no model.
"""
import re
from typing import Dict, Iterable, List, Optional

from soa_shared import attribute_accuracy

PRODUCT_RECORD_TEMPLATES = {
    'markup.not_in': 'not in the markup',
}

T = PRODUCT_RECORD_TEMPLATES

#: B1's fields, each as the record's field label names it.
MARKUP_FIELDS = ('gtin', 'size', 'count', 'weight', 'line')

_GTIN_KEYS = ('gtin13', 'gtin12', 'gtin14', 'gtin8', 'gtin')
_COUNT = re.compile(r'(\d+)\s*(?:ct|count|pack|diapers)\b', re.I)


def _gtin14(value) -> Optional[str]:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits.zfill(14) if digits and len(digits) <= 14 else None


def _variants(json_ld) -> List[dict]:
    """The ProductGroup's own Product variants (hasVariant), in page order; [] when the markup has no group."""
    nodes = json_ld if isinstance(json_ld, list) else [json_ld]
    for node in nodes:
        if isinstance(node, dict) and node.get('hasVariant'):
            return [v for v in node['hasVariant'] if isinstance(v, dict)]
        if isinstance(node, dict) and node.get('@graph'):
            found = _variants(node['@graph'])
            if found:
                return found
    return []


def _group(json_ld) -> Optional[dict]:
    nodes = json_ld if isinstance(json_ld, list) else [json_ld]
    for node in nodes:
        if isinstance(node, dict) and node.get('hasVariant'):
            return node
        if isinstance(node, dict) and node.get('@graph'):
            found = _group(node['@graph'])
            if found:
                return found
    return None


def is_product_group(json_ld) -> bool:
    return bool(_variants(json_ld))


def _size(text) -> Optional[str]:
    text = str(text or '').strip()
    if not text:
        return None
    return attribute_accuracy.size_of(text) or attribute_accuracy.size_of(f"Size {text}")


def node_facts(node: dict) -> dict:
    """What one markup variant states: {gtin, size, count, weight} (None where it states nothing)."""
    gtin = next((node.get(k) for k in _GTIN_KEYS if node.get(k)), None)
    size = _size(node.get('size')) or _size(node.get('name'))
    words = ' '.join(str(node.get(k) or '') for k in ('name', 'size', 'description'))
    m = _COUNT.search(words)
    count = int(m.group(1)) if m else None
    ranges = attribute_accuracy.parse_ranges(str(node.get('description') or ''))
    return {'gtin': str(gtin) if gtin else None, 'size': size, 'count': count,
            'weight': attribute_accuracy.phrase(ranges[0][0]) if ranges else None}


def feed_facts(variant: dict, brand: Optional[str] = None) -> dict:
    """What a feed variant carries: {gtin, size, count, weight, line}."""
    from app.services import console_release as rel
    return {'gtin': variant.get('gtin') or None, 'size': attribute_accuracy.size_of(variant.get('label') or variant.get('title')),
            'count': variant.get('count'), 'weight': variant.get('weight') or None,
            'line': rel.line_key(variant.get('product_name'), brand) if variant.get('product_name') else None}


def match_variant(json_ld, variant: dict) -> tuple:
    """(the page's variant that is the feed variant's, how: gtin | size_count | size) or (None, None)."""
    nodes = _variants(json_ld)
    mine = feed_facts(variant)
    facts = [(n, node_facts(n)) for n in nodes]
    gtin = _gtin14(mine['gtin'])
    if gtin:
        hit = next((n for n, f in facts if _gtin14(f['gtin']) == gtin), None)
        if hit is not None:
            return hit, 'gtin'
    if mine['size']:
        sized = [(n, f) for n, f in facts if f['size'] == mine['size']]
        if mine['count'] is not None:
            hit = next((n for n, f in sized if f['count'] == mine['count']), None)
            if hit is not None:
                return hit, 'size_count'
        if len(sized) == 1:
            return sized[0][0], 'size'
    return None, None


def markup_differences(variant: dict, json_ld, *, brand: Optional[str] = None) -> dict:
    """B1: the feed variant against its own variant on the page. {matched (how, or None), node, differences:
    [{field, record, page}], not_in_markup: [field]}. Unmatched: no difference is claimed."""
    node, how = match_variant(json_ld, variant)
    if node is None:
        return {'matched': None, 'node': None, 'differences': [], 'not_in_markup': []}
    from app.services import console_release as rel
    mine, page = feed_facts(variant, brand), node_facts(node)
    group = _group(json_ld) or {}
    page['line'] = rel.line_key(group.get('name'), brand) if group.get('name') else None
    diffs, absent = [], []
    for field in MARKUP_FIELDS:
        ours, theirs = mine.get(field), page.get(field)
        if ours in (None, ''):
            continue
        if theirs in (None, ''):
            absent.append(field)
            continue
        same = _gtin14(ours) == _gtin14(theirs) if field == 'gtin' else str(ours) == str(theirs)
        if not same:
            shown = rel.page_line(group.get('name')) if field == 'line' else theirs
            diffs.append({'field': field, 'record': variant.get('product_name') if field == 'line' else ours,
                          'page': shown})
    return {'matched': how, 'node': node, 'differences': diffs, 'not_in_markup': absent}


#: B1 -> the record's finding kinds (console_read_models.RECORD_FINDINGS).
FINDING_OF = {'gtin': 'gtin_mismatch', 'count': 'pack_differs', 'line': 'name_differs', 'size': 'size_differs',
              'weight': 'weight_differs'}


def markup_findings(row: dict, variant: dict, *, brand: Optional[str] = None) -> List[dict]:
    """A brand page row's findings for one record variant, in supply's finding shape ({finding, expected,
    observed}), from B1's comparison; supply's own are kept for a page whose markup has no ProductGroup."""
    if not is_product_group(row.get('json_ld')):
        return list(row.get('findings') or [])
    got = markup_differences(variant, row['json_ld'], brand=brand)
    return [{'finding': FINDING_OF[d['field']], 'expected': str(d['record']), 'observed': str(d['page']),
             'detail': {'matched_by': got['matched']}} for d in got['differences']]


# ─── B2: the record per feed SKU ─────────────────────────────────────────

PRODUCT_RECORD_TEMPLATES.update({
    'hero.disagree': 'Agents contradict the record on {n} {products} this cycle.',
    'hero.most.one': ' {name} has the most: {k} {agents}.',
    'hero.most.many': ' {names} each have {k} agents disagreeing.',
    'hero.none': 'Agents match the record on every product they quoted this cycle.',
    'hero.unquoted': 'No agent quoted these products this cycle.',
    'state.agents_disagree': '{n} {agents} disagree',
    'state.match': 'Agents match',
    'state.not_quoted': 'Not quoted',
    'row.name': 'Name on {domain}',
    'row.gtin': 'GTIN',
    'row.gtin.none': 'None in the feed',
    'row.gtin.mapping': '{domain} also maps it to {what}',
    'row.gtin.markup': '{domain} markup gives {gtin} for {size}',
    'row.weight': 'Weight range',
    'row.weight.note': '{domain} size chart, {day}',
    'row.weight.none': 'No chart on {domain}',
    'row.packs': '{size} packs on {domain}',
    'row.claims': 'Claims',
    'row.claims.note': '{domain}, {day}',
    'row.price': 'Price',
    'row.price.v': 'Not set. Retailers price it',
    'row.retailer': '{retailer}, {day}',
    'row.retailer.says': 'Page says {weight}',
    'row.cant': "Couldn't read",
    'row.cant.http': "Couldn't read. HTTP {codes}",
    'row.cant.walled': "Couldn't read. Walled",
    'row.unread': 'Not read yet',
    'row.not_carried': 'Not carried. The feed lists no page there',
    'row.not_carried.club': 'Not carried. The clubs sell {line} instead',
    'row.verified': 'Last verified',
    'issues.none': 'None found on this record.',
    'issue.two_charts.title': 'Two {size} charts',
    'issue.two_charts.text': '{domain} rates {groups}.',
    'issue.two_charts.group': '{lines} {size} at {range}',
    'issue.two_charts.both': ' {agents} gave both ranges for this diaper.',
    'issue.two_charts.other': ' {agents} gave {range} for this diaper.',
    'issue.gtin.two.title': 'One GTIN for two packs',
    'issue.gtin.two.text': '{domain} maps {gtin} to {counts}.',
    'issue.gtin.digits.title': 'A GTIN with {digits} digits',
    'issue.gtin.digits.text': '{where} gives {was} for {line} {size}, which drops its leading zero: {now}.',
    'issue.gtin.digits.where.markup': '{domain} markup',
    'issue.gtin.digits.where.feed': 'The feed',
    'issue.gtin.markup.title': 'Another GTIN in the markup',
    'issue.gtin.markup.text': "Markup names another GTIN for {size}: {page} against the feed's {record}.",
    'issue.ranges.title': 'Retailers that state the wrong range',
    'issue.ranges.text': '{wrong}.{right}',
    'issue.ranges.one': '{retailer} says {range}',
    'issue.ranges.right': ' {retailers} {verb} {domain} at {range}.',
    'issue.borrows.title': 'Markup borrows another line',
    'issue.borrows.text': 'The {line} page markup lists {sizes} with {other} weights, against its own size chart.',
    'surface.held': 'Held in preview',
    'surface.published': 'Published',
    'surface.live': 'Live',
    'surface.blocked': 'Blocked',
    'surface.na': 'Not applicable',
    'surface.drift': '{n} {agents} disagree',
    'surface.match': 'Matches answers',
    'surface.unquoted': 'Not quoted yet',
    'variant.walled': 'Not read · walled',
    'variant.walled.http': 'Not read · walled, HTTP {code}',
    'variant.unread': 'Not read yet',
    'variant.says': 'Page says {weight}',
    'history.verified': 'Verified against {domain} and the retailer pages',
    'history.verified.detail': '{n} {pages} read',
    'history.compiled': 'Record compiled from the feed',
    'history.compiled.detail': 'Feed version {version}. Held on {held}',
    'history.compiled.detail.unversioned': 'Held on {held}',
    'history.first': 'First read',
    'history.page.read': '{who} read',
    'history.page.walled': '{who} walled',
})

_RETAILER_ID = (re.compile(r'/dp/([A-Z0-9]{10})', re.I), re.compile(r'/ip/(?:[^/]+/)?(\d{5,})'),
                re.compile(r'/A-(\d{5,})'), re.compile(r'/(\d{6,})(?:[/?#]|$)'))
_KEEP_MARKS_GENERIC = re.compile(r"\s+\b(?:diapers?|pull[- ]?ons?|pants|wipes|trainers?|nappies|for)\b.*$", re.I)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _and(items: List[str]) -> str:
    from app.services import console_manufacturer as manu
    return manu._and(list(items))


def sku_of(v: dict) -> str:
    """The list's key for a feed SKU: its merchant SKU, else its GTIN-14, else its variant id."""
    return str(v.get('sku') or _gtin14(v.get('gtin')) or v.get('variant_id'))


def is_sku(v: dict, product: str) -> bool:
    keys = {str(k) for k in (v.get('sku'), v.get('variant_id'), v.get('gtin'), _gtin14(v.get('gtin'))) if k}
    return product in keys or (_gtin14(product) is not None and _gtin14(product) == _gtin14(v.get('gtin')))


def _norm(text) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).strip()


def variant_lines(record: dict, v: dict) -> List[dict]:
    """The record's readback lines (console_release.readback) that are about this variant."""
    return [l for l in record.get('drift_all') or [] if _norm(l.get('variant')) == _norm(v.get('label'))]


def sku_state(lines: List[dict]) -> dict:
    """{state: agents_disagree | match | not_quoted, n, which}: the agents with a fact against the record."""
    agent_lines = [l for l in lines if l.get('agent') != 'shelf']
    wrong = sorted({l['agent'] for l in agent_lines if l.get('verdict') in ('wrong', 'partial')})
    if wrong:
        return {'state': 'agents_disagree', 'n': len(wrong), 'which': wrong}
    return {'state': 'match' if agent_lines else 'not_quoted', 'n': 0, 'which': []}


def state_status(st: dict) -> dict:
    if st['state'] == 'agents_disagree':
        return {'label': T['state.agents_disagree'].format(n=st['n'], agents=_plural(st['n'], 'agent', 'agents'))
                .replace('1 agent disagree', '1 agent disagrees'), 'tone': 'warn'}
    if st['state'] == 'match':
        return {'label': T['state.match'], 'tone': 'ok'}
    return {'label': T['state.not_quoted'], 'tone': 'neu'}


def _short_line(name: Optional[str], brand: Optional[str]) -> str:
    from app.services import console_manufacturer as manu
    return manu._line_display(name, brand)


def sku_chart(prices: Optional[List[dict]], v: dict, *, charts: Optional[Dict[str, list]], own_domains: Iterable[str],
              brand: Optional[str]):
    """The SKU's chart: its line's on the brand's page (console_release.feed_line_charts, 2T-4 (5)), else the
    chart its own rows' page carries (console_release.record_chart); None when the line has none."""
    from app.services import console_release as rel
    if charts is not None:
        mine = charts.get(rel.line_key(v.get('product_name'), brand))
        if mine:
            return mine
    return rel.record_chart(prices, [v], own_domains=own_domains, brand=brand)


def record_sub(v: dict, chart) -> str:
    """The subtitle under the record's title (its product name): the variant's words without the name again. 2T-11
    (B2): a feed label that leads with the product name ("Pampers Swaddlers, Newborn, 84 ct") read "Pampers
    Swaddlers, Pampers Swaddlers, Newborn, 84 ct" in the selected record's title."""
    from app.services import console_release as rel
    label, name = str(v.get('label') or ''), str(v.get('product_name') or '').strip()
    if name and label.lower().startswith(name.lower()):
        v = {**v, 'label': label[len(name):].lstrip(' ,-·').strip()}
    return rel._variant_words(v, chart)


def record_list_rows(records: List[dict], *, catalog: Optional[dict], feed_rows: Optional[List[dict]],
                     prices: Optional[List[dict]], own_domains: Iterable[str], brand: Optional[str],
                     charts: Optional[Dict[str, list]] = None) -> List[dict]:
    """B2: one row per feed SKU, in the hold's order: {sku, title, sub, line, record_ref, state, disagree, status,
    retired}. The subtitle is the label, the count and the line's chart range ("Size 4, 150 ct, 15 to 34 lb")."""
    from app.services import console_release as rel
    out = []
    for rec in records:
        for v in rel.record_variants(rec['record_ref'], catalog, feed_rows):
            chart = sku_chart(prices, v, charts=charts, own_domains=own_domains, brand=brand)
            st = sku_state(variant_lines(rec, v))
            succ = v.get('successor') or {}
            out.append({'sku': sku_of(v), 'title': v.get('product_name') or rec.get('name'),
                        'sub': record_sub(v, chart), 'line': _short_line(v.get('product_name'), brand),
                        'record_ref': rec['record_ref'], 'variant_id': v.get('variant_id'), 'state': st['state'],
                        'disagree': {'n': st['n'], 'which': st['which']}, 'status': state_status(st),
                        'retired': {'successor': {'productName': succ.get('product_name'), 'sku': succ.get('sku')}
                                    if succ else None} if v.get('status') == 'retired' else None})
    return out


def build_hero(rows: List[dict], *, revenue: Optional[dict]) -> dict:
    """B2: {disagree: {n, of}, sentence, gainable}: products (feed SKUs) where agents disagree with the record,
    the lines with the most agents disagreeing, and the revenue model's gainable pool (the Overview's own)."""
    bad = [r for r in rows if r['state'] == 'agents_disagree']
    if bad:
        k = max(r['disagree']['n'] for r in bad)
        top = list(dict.fromkeys(r['line'] for r in bad if r['disagree']['n'] == k))
        sentence = T['hero.disagree'].format(n=len(bad), products=_plural(len(bad), 'product', 'products'))
        sentence += T['hero.most.one'].format(name=top[0], k=k, agents=_plural(k, 'agent', 'agents')) if len(top) == 1 \
            else T['hero.most.many'].format(names=_and(top), k=k)
    else:
        quoted = any(r['state'] == 'match' for r in rows)
        sentence = T['hero.none'] if quoted else T['hero.unquoted']
    today = (revenue or {}).get('today') or {}
    return {'disagree': {'n': len(bad), 'of': len(rows)}, 'sentence': sentence,
            'gainable': {'value': today.get('gainable'), 'currency': (revenue or {}).get('currency'),
                         'measured': (revenue or {}).get('measured')} if revenue else None}


def _own(rows: Iterable[dict], own: set) -> List[dict]:
    return [r for r in rows if r.get('role') == 'own' or _dom(r.get('retailer_domain')) in own]


def _dom(d) -> str:
    return str(d or '').lower().removeprefix('www.')


def line_page(prices: Optional[List[dict]], v: dict, own_domains: Iterable[str], brand: Optional[str]) -> Optional[dict]:
    """The brand page that speaks for the variant's line: its own row's page when it carries markup for the line,
    else the newest own-site page whose markup names the line (as the charts are keyed, console_release.line_charts)."""
    from app.services import console_release as rel
    own = {_dom(d) for d in own_domains or () if d}
    key = rel.line_key(v.get('product_name'), brand)
    pages = sorted((r for r in _own(prices or [], own) if r.get('json_ld')),
                   key=lambda r: str(r.get('observed_at') or ''), reverse=True)
    mine = [r for r in pages if rel._row_matches(r, v)]
    for r in mine + pages:
        if rel.line_key(_ld_name(r['json_ld']), brand) == key:
            return r
    return None


def _ld_name(json_ld) -> Optional[str]:
    node = _group(json_ld) or (json_ld if isinstance(json_ld, dict) else {})
    return node.get('name')


def _page_name(json_ld) -> Optional[str]:
    """"Pampers® Swaddlers™": the page's product name up to its product-type word, marks kept."""
    name = _ld_name(json_ld)
    if not name:
        return None
    return _KEEP_MARKS_GENERIC.sub('', str(name).split('|')[0]).strip(' -,:') or None


def _offers(node: dict) -> List[dict]:
    got = node.get('offers')
    got = got if isinstance(got, list) else [got] if isinstance(got, dict) else []
    out = []
    for o in got:
        if not isinstance(o, dict):
            continue
        seller = o.get('seller') or {}
        name = seller.get('name') if isinstance(seller, dict) else seller
        words = ' '.join(str(o.get(k) or '') for k in ('name', 'description', 'url', 'sku'))
        m = _COUNT.search(words) or re.search(r'(\d+)[-_ ]?(?:ct|count)', words, re.I)
        out.append({'seller': name, 'count': int(m.group(1)) if m else None, 'url': o.get('url')})
    return out


def _stated(row: dict) -> Optional[str]:
    w = row.get('weight_range')
    if isinstance(w, dict):
        return attribute_accuracy.phrase(w)
    return str(w) if w else None


def _http(row: dict) -> Optional[str]:
    for k in ('http_status', 'status_code', 'http_code'):
        if row.get(k):
            return str(row[k])
    return None


def _retailer_id(row: dict) -> Optional[str]:
    if row.get('gtin'):
        return str(row['gtin'])
    for pat in _RETAILER_ID:
        m = pat.search(str(row.get('url') or ''))
        if m:
            return m.group(1)
    return None


def _deal_words(deals: Optional[dict], v: dict, domain: str) -> List[str]:
    """The deals live on the variant at a retailer, each its one label without the retailer ("Rollback, $49.77
    from $59.77"): supply's /deals, as Trade promotions reads them."""
    from app.services import console_release as rel
    from soa_shared import promo_pass_through as ppt
    out = []
    for deal in (deals or {}).get('deals') or []:
        if _dom(deal.get('retailer_domain')) != domain:
            continue
        entry = next((e for e in deal.get('variants') or [] if rel._row_matches(e, v)), None)
        if entry is None or ppt.out_of_stock(deal, entry):
            continue
        said = ppt.label(deal, entry)
        out.append(said.split(': ', 1)[1] if ': ' in said else said)
    return out


def _drift_for(drift: List[dict], reference: Optional[dict], v: dict, brand: Optional[str]) -> List[dict]:
    """2M-1's weight rows (rm.build_weight_drift) about this variant, by its /reference attribute."""
    from app.services import console_release as rel
    by_ref = {a.get('variant_ref'): a for a in (reference or {}).get('attributes') or []}
    out = []
    for r in drift or []:
        a = by_ref.get(r.get('variant_ref')) or {}
        line_text = ' '.join(x for x in (a.get('product_name'), a.get('variant_label')) if x)
        if rel.matches_variant([v], variant_id=a.get('variant_id') or a.get('sku'), label=a.get('variant_label'),
                               line_text=line_text, brand=brand):
            out.append(r)
    return out


def _drift_domain(row: dict) -> Optional[str]:
    m = re.search(r'\(([^)]+)\)\s*$', str(row.get('field') or ''))
    return _dom(m.group(1)) if m and m.group(1) != 'markup' else None


def _size_words(label) -> Optional[str]:
    return attribute_accuracy.size_label(label)


def build_issues(v: dict, *, page: Optional[dict], charts: Optional[Dict[str, list]], feed_rows: Optional[List[dict]],
                 brand: Optional[str], domain: str, attribute_answers: List[dict], drift: List[dict],
                 shelf_rows: List[dict], flags: List[dict], chart_weight: Optional[str],
                 markup: Optional[dict] = None) -> List[dict]:
    """B2: the record's issues, each {kind, title, text, fix_kind, tone}: two charts for the size across the
    lines, a GTIN mapping (one GTIN on two counts in the markup, or 11 digits; 2T-11: the markup naming another
    GTIN than the feed's, the GTIN row's own mismatch, so the Issues card never says "None found" beside it),
    retailers stating another range than the chart, and markup sizes that carry another line's chart."""
    from app.services import console_brand_overview as bo
    from app.services import console_release as rel
    from app.services import console_manufacturer as manu
    out = []
    size = _size_words(v.get('label'))
    key = rel.line_key(v.get('product_name'), brand)
    line = _short_line(v.get('product_name'), brand)
    phrase = attribute_accuracy.phrase
    # two charts: the size has two ranges across the feed's lines
    groups = bo.chart_groups(charts or {}, feed_rows, brand).get(size) if charts and size else None
    if groups and len(groups) > 1:
        text = T['issue.two_charts.text'].format(domain=domain, groups=' and '.join(
            T['issue.two_charts.group'].format(lines=_and(ls), size=size, range=rng) for rng, ls in groups))
        ranges = {rng for rng, _ in groups}
        said: Dict[str, set] = {}
        for a in attribute_answers or []:
            if rel.matches_variant([v], variant_id=a.get('variant_id'), line_text=a.get('variant'), brand=brand) is None:
                continue
            got = phrase(a.get('stated'))
            if got in ranges:
                said.setdefault(surfaces_name(a.get('platform')), set()).add(got)
        both = [ag for ag, got in said.items() if len(got) > 1]
        other = sorted({ag for ag, got in said.items() if chart_weight and got - {chart_weight}} - set(both))
        if both:
            text += T['issue.two_charts.both'].format(agents=_and(sorted(both)))
        elif other:
            rest = sorted(ranges - {chart_weight})
            text += T['issue.two_charts.other'].format(agents=_and(other), range=_and(rest))
        out.append({'kind': 'two_charts', 'title': T['issue.two_charts.title'].format(size=size), 'text': text,
                    'fix_kind': 'size_chart', 'tone': 'bad'})
    # gtin mapping: one GTIN on two counts in the markup
    nodes = _variants((page or {}).get('json_ld'))
    gtin = _gtin14(v.get('gtin'))
    if gtin and nodes:
        counts = []
        for n in nodes:
            f = node_facts(n)
            if _gtin14(f['gtin']) == gtin:
                for o in _offers(n) or [{'seller': None, 'count': f['count']}]:
                    if o['count'] and o['count'] not in [c for c, _ in counts]:
                        counts.append((o['count'], o['seller']))
        if len(counts) > 1:
            out.append({'kind': 'gtin_mapping', 'title': T['issue.gtin.two.title'],
                        'text': T['issue.gtin.two.text'].format(domain=domain, gtin=v.get('gtin'), counts=' and '.join(
                            f"{'' if not s else possessive_of(s) + ' '}{c} ct" for c, s in counts)),
                        'fix_kind': 'gtin', 'tone': 'bad'})
    # gtin mapping: a GTIN that is not one as written (11 digits), on the variant's line and size
    for f in flags or []:
        mine = (f.get('where') == 'feed' and _gtin14(f.get('was')) == gtin and gtin) or \
            (f.get('where') == 'markup' and rel.line_key(f.get('line'), brand) == key and size and size.lower() in
             str(f.get('field') or '').replace('_', ' '))
        if mine:
            where = T['issue.gtin.digits.where.markup'].format(domain=domain) if f['where'] == 'markup' \
                else T['issue.gtin.digits.where.feed']
            out.append({'kind': 'gtin_mapping', 'title': T['issue.gtin.digits.title'].format(digits=f.get('digits')),
                        'text': T['issue.gtin.digits.text'].format(where=where, was=f['was'], line=line, size=size or '',
                                                                    now=f['now']),
                        'fix_kind': 'gtin', 'tone': 'bad'})
            break
    # 2T-11 (B2): the markup names another GTIN for the variant (markup_differences, the GTIN row's `was`)
    gtin_diff = next((d for d in (markup or {}).get('differences') or [] if d['field'] == 'gtin'), None)
    if gtin_diff:
        out.append({'kind': 'gtin_mapping', 'title': T['issue.gtin.markup.title'],
                    'text': T['issue.gtin.markup.text'].format(size=size or 'this size', page=gtin_diff['page'],
                                                               record=gtin_diff['record']),
                    'fix_kind': 'gtin', 'tone': 'bad'})
    # retailers stating another range than the chart
    # each retailer's stated range: its shelf row's own when the row states one (the newer read), else 2M-1's row
    stated = {_drift_domain(r): r['was'] for r in drift if r.get('kind') == 'page' and _drift_domain(r)}
    stated.update({_dom(r.get('retailer_domain')): _stated(r) for r in shelf_rows if _stated(r)})
    wrong = [(d, rng) for d, rng in stated.items() if chart_weight and rng != chart_weight]
    if wrong:
        right = sorted(rm_name(d) for d, rng in stated.items() if rng == chart_weight)
        text = T['issue.ranges.text'].format(
            wrong=', '.join(T['issue.ranges.one'].format(retailer=rm_name(d), range=rng) for d, rng in wrong),
            right=T['issue.ranges.right'].format(retailers=_and(right), verb='match' if len(right) > 1 else 'matches',
                                                 domain=domain, range=chart_weight) if right else '')
        out.append({'kind': 'retailers_wrong_range', 'title': T['issue.ranges.title'], 'text': text,
                    'fix_kind': 'size_chart', 'tone': 'warn'})
    # markup sizes carrying another line's chart, against its own
    own = (charts or {}).get(key) if charts else None
    if nodes and own:
        borrowed, other_line = [], None
        for n in nodes:
            f = node_facts(n)
            if not f['size'] or not f['weight']:
                continue
            mine_w = rel.weight_of(own, f"Size {f['size']}")
            if mine_w is None or mine_w == f['weight']:
                continue
            for other_key, chart in (charts or {}).items():
                if other_key != key and rel.weight_of(chart, f"Size {f['size']}") == f['weight']:
                    borrowed.append(f['size'])
                    other_line = other_line or other_key
                    break
        if borrowed:
            other = next((_short_line(r.get('product_name'), brand) for r in feed_rows or []
                          if rel.line_key(r.get('product_name'), brand) == other_line), None) or other_line
            sizes = _sizes_words(borrowed)
            out.append({'kind': 'markup_borrows', 'title': T['issue.borrows.title'],
                        'text': T['issue.borrows.text'].format(line=line, sizes=sizes, other=other),
                        'fix_kind': 'size_chart', 'tone': 'warn'})
    return out


def _sizes_words(sizes: List[str]) -> str:
    nums = [int(s) for s in sizes if str(s).isdigit()]
    if len(nums) == len(sizes) and len(nums) > 2 and nums == list(range(nums[0], nums[0] + len(nums))):
        return f"sizes {nums[0]} to {nums[-1]}"
    words = [f"Size {s}" if str(s).isdigit() else str(s).capitalize() for s in sizes]
    return _and(words)


def rm_name(domain: Optional[str]) -> str:
    from app.services import console_read_models as rm
    return rm._retailer_name(_dom(domain))


def surfaces_name(platform: Optional[str]) -> str:
    """An answer's agent by its display name ("AI Mode"), in rm.AGENT_NAMES."""
    from app.services import console_read_models as rm
    from soa_shared import surfaces
    agent = surfaces.agent_of(platform) or str(platform)
    return rm.AGENT_NAMES.get(agent, agent)


def possessive_of(name: str) -> str:
    from soa_shared.possessive import possessive
    return possessive(name)


def _day(value) -> Optional[str]:
    from app.services import console_manufacturer as manu
    return manu.short_day(value)


def _long_day(value) -> Optional[str]:
    from app.services import console_read_models as rm
    iso = rm._iso(value)
    if not iso:
        return None
    from datetime import datetime
    try:
        d = datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
    except ValueError:
        return None
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def record_rows(v: dict, *, page: Optional[dict], shelf_rows: List[dict], retailers: List[str], own: set,
                domain: str, chart, deals: Optional[dict], drift: List[dict], club_lines: List[dict],
                brand: Optional[str], markup: dict) -> List[dict]:
    """B2: the record card's field rows, each {k, v, prov (brand | retail | parleo), note, mono, diff, struck}."""
    from app.services import console_release as rel
    from app.services import console_release as _rel  # noqa: F401
    from app.services import console_manufacturer as manu
    out = []
    size = _size_words(v.get('label'))
    name = _page_name((page or {}).get('json_ld'))
    if name:
        line_diff = next((d for d in markup.get('differences') or [] if d['field'] == 'line'), None)
        out.append({'k': T['row.name'].format(domain=domain), 'v': name, 'prov': 'brand',
                    'note': None if not line_diff else f"The feed names it {line_diff['record']}"})
    node = markup.get('node')
    gtin_diff = next((d for d in markup.get('differences') or [] if d['field'] == 'gtin'), None)
    note = None
    if node is not None and v.get('count'):
        other = [o for o in _offers(node) if o['count'] and o['count'] != v.get('count')]
        if other:
            note = T['row.gtin.mapping'].format(domain=domain, what=' and '.join(
                f"{'an' if (o['seller'] or '')[:1].lower() in 'aeiou' else 'a'} {o['seller']} {o['count']} ct pack"
                if o['seller'] else f"a {o['count']} ct pack" for o in other))
    row = {'k': T['row.gtin'], 'v': v.get('gtin') or T['row.gtin.none'], 'prov': 'brand', 'mono': bool(v.get('gtin')),
           'note': note}
    if gtin_diff:
        row.update({'diff': True, 'was': str(gtin_diff['page']),
                    'note': T['row.gtin.markup'].format(domain=domain, gtin=gtin_diff['page'], size=size or 'this size')})
    out.append(row)
    weight = rel.weight_of(chart, v.get('label')) if chart else None
    if weight:
        out.append({'k': T['row.weight'], 'v': weight, 'prov': 'brand',
                    'note': T['row.weight.note'].format(domain=domain, day=_day((page or {}).get('observed_at')) or 'not dated')})
    else:
        out.append({'k': T['row.weight'], 'v': size or T['row.unread'], 'prov': 'brand',
                    'note': T['row.weight.none'].format(domain=domain)})
    packs = []
    for n in _variants((page or {}).get('json_ld')):
        f = node_facts(n)
        if size and f['size'] != attribute_accuracy.size_of(v.get('label')):
            continue
        for o in _offers(n) or [{'seller': None, 'count': f['count']}]:
            if o['count']:
                packs.append(f"{o['count']} ct {o['seller']}".strip() if o['seller'] else f"{o['count']} ct")
    if packs:
        out.append({'k': T['row.packs'].format(size=size or 'The', domain=domain), 'v': ', '.join(dict.fromkeys(packs)),
                    'prov': 'brand'})
    if (page or {}).get('bullets'):
        out.append({'k': T['row.claims'], 'v': ', '.join(page['bullets'][:4]), 'prov': 'brand',
                    'note': T['row.claims.note'].format(domain=domain, day=_day(page.get('observed_at')) or 'not dated')})
    out.append({'k': T['row.price'], 'v': T['row.price.v'], 'prov': 'parleo'})
    stated_by = {_drift_domain(r): r['was'] for r in drift if r.get('kind') == 'page' and _drift_domain(r)}
    walled, unread = [], []
    for r in sorted(shelf_rows, key=lambda r: rm_name(r.get('retailer_domain'))):
        d = _dom(r.get('retailer_domain'))
        if not r.get('observed_at'):
            unread.append(r)
            continue
        if r.get('method') in rel.WALLED_METHODS and r.get('price') is None:
            walled.append(r)
            continue
        if r.get('price') is None:
            continue
        bits = [f"{v['count']} ct ${r['price']}" if v.get('count') else f"${r['price']}"]
        bits += _deal_words(deals, v, d)
        if not _deal_words(deals, v, d) and r.get('list_price') and str(r['list_price']) != str(r['price']):
            bits.append(f"from ${r['list_price']}")
        text = ', '.join(bits)
        stated = _stated(r) or stated_by.get(d)
        f = {'k': T['row.retailer'].format(retailer=rm_name(d), day=_day(r['observed_at'])), 'v': text, 'prov': 'retail'}
        if stated:
            f['v'] = f"{text}. {T['row.retailer.says'].format(weight=stated)}"
            if weight and stated != weight:
                f.update({'diff': True, 'struck': weight})
        out.append(f)
    if walled:
        codes = [c for c in (_http(r) for r in walled) if c]
        names = list(dict.fromkeys(rm_name(r.get('retailer_domain')) for r in walled))
        out.append({'k': _and(names), 'prov': 'parleo',
                    'v': T['row.cant.http'].format(codes=' and '.join(dict.fromkeys(codes))) if codes
                    else T['row.cant.walled']})
    if unread:
        out.append({'k': _and(list(dict.fromkeys(rm_name(r.get('retailer_domain')) for r in unread))),
                    'v': T['row.unread'], 'prov': 'parleo'})
    listed = {_dom(x) for x in v.get('retailers') or []} | {_dom(r.get('retailer_domain')) for r in shelf_rows}
    missing = [d for d in retailers or [] if _dom(d) not in listed and _dom(d) not in own]
    if missing:
        clubs = [l for l in club_lines or [] if l.get('line') != v.get('product_name')
                 and {_dom(c) for c in l.get('clubs') or []} >= {_dom(d) for d in missing}]
        out.append({'k': _and([rm_name(d) for d in missing]), 'prov': 'retail',
                    'v': T['row.not_carried.club'].format(line=_short_line(clubs[0]['line'], brand)) if clubs
                    else T['row.not_carried']})
    dated = [str(r['observed_at']) for r in shelf_rows + ([page] if page else []) if r and r.get('observed_at')]
    if dated:
        out.append({'k': T['row.verified'], 'v': _long_day(max(dated)), 'prov': 'parleo'})
    for f in out:
        for k in ('note', 'mono', 'diff', 'was', 'struck'):
            f.setdefault(k, None if k != 'mono' and k != 'diff' else False)
    return out


SURFACE_WORD = {'held': 'surface.held', 'published': 'surface.published', 'live': 'surface.live',
                'blocked': 'surface.blocked', 'na': 'surface.na'}


def record_surfaces(record: dict, st: dict, channels: Dict[str, dict]) -> List[dict]:
    """B2: the record on each surface of the pass, in 2T-1's vocabulary: {channel, name, s, word, drift (drift |
    none | unquoted | None), drift_word, n}."""
    from app.services import console_release as rel
    out = []
    for slug, cell in (record.get('cells') or {}).items():
        s = cell.get('s')
        # 2U-2: the matrix carries every channel; the record lists the pass's (a row for it, or a held/live cell)
        if s in ('next', 'not_for_brand') or (s == 'na' and cell.get('publication_id') is None):
            continue
        na = s in ('na', 'blocked')
        drift = None if na else 'drift' if st['state'] == 'agents_disagree' else 'none' if st['state'] == 'match' \
            else 'unquoted'
        word = None if na else T['surface.drift'].format(n=st['n'], agents=_plural(st['n'], 'agent', 'agents')).replace(
            '1 agent disagree', '1 agent disagrees') if drift == 'drift' else T['surface.match'] if drift == 'none' \
            else T['surface.unquoted']
        out.append({'channel': slug, 'name': rel._channel_short(slug, channels), 's': s,
                    'word': T[SURFACE_WORD.get(s, 'surface.na')], 'drift': drift, 'drift_word': word,
                    'n': st['n'] if drift == 'drift' else None, 'note': cell.get('note')})
    return out


def record_variants_read(v: dict, shelf_rows: List[dict], *, deals: Optional[dict], drift: List[dict],
                         chart_weight: Optional[str]) -> List[dict]:
    """B2: one per retailer read of the SKU: {id (GTIN or the retailer's id), count, retailer, price, note, tone};
    a walled retailer "Not read · walled"."""
    from app.services import console_release as rel
    stated_by = {_drift_domain(r): r['was'] for r in drift if r.get('kind') == 'page' and _drift_domain(r)}
    out = []
    for r in sorted(shelf_rows, key=lambda r: rm_name(r.get('retailer_domain'))):
        d = _dom(r.get('retailer_domain'))
        name = rm_name(d)
        base = {'id': _retailer_id(r) or name, 'count': v.get('count'), 'retailer': name,
                'name': f"{v['count']} ct, {name}" if v.get('count') else name}
        if not r.get('observed_at'):
            out.append({**base, 'price': None, 'note': T['variant.unread'], 'tone': 'neu'})
            continue
        if r.get('price') is None and r.get('method') in rel.WALLED_METHODS:
            code = _http(r)
            out.append({**base, 'id': _retailer_id(r) or name, 'price': None,
                        'note': T['variant.walled.http'].format(code=code) if code else T['variant.walled'],
                        'tone': 'neu'})
            continue
        if r.get('price') is None:
            continue
        notes = _deal_words(deals, v, d)
        stated = _stated(r) or stated_by.get(d)
        if stated:
            notes.append(T['variant.says'].format(weight=stated))
        off = bool(stated and chart_weight and stated != chart_weight)
        out.append({**base, 'price': f"${r['price']}", 'note': '. '.join(notes) or None,
                    'tone': 'bad' if off else 'warn' if _deal_words(deals, v, d) else 'ok'})
    return out


def record_history(v: dict, *, shelf_rows: List[dict], page: Optional[dict], held_rows: Dict[str, dict],
                   channels: Dict[str, dict], domain: str, feed_version: Optional[dict]) -> tuple:
    """B2: (history, history_all). Three kinds, newest first: the cycle's reads ("Verified against <domain> and the
    retailer pages"), the hold ("Record compiled from the feed", its feed version), the first read; every page
    read in history_all."""
    from app.services import console_release as rel
    from app.services import console_manufacturer as manu
    reads = [r for r in shelf_rows + ([page] if page else []) if r and r.get('observed_at')]
    out, every = [], []
    for r in reads:
        d = _dom(r.get('retailer_domain'))
        who = domain if r is page else rm_name(d)
        walled = r is not page and r.get('price') is None and r.get('method') in rel.WALLED_METHODS
        every.append({'kind': 'page', 'at': str(r['observed_at']), 'day': _day(r['observed_at']),
                      'text': T['history.page.walled' if walled else 'history.page.read'].format(who=who),
                      'url': r.get('url')})
    every.sort(key=lambda e: e['at'], reverse=True)
    if reads:
        newest = max(str(r['observed_at']) for r in reads)
        out.append({'kind': 'verified', 'at': newest, 'day': _day(newest),
                    'text': T['history.verified'].format(domain=domain),
                    'detail': T['history.verified.detail'].format(n=len(reads), pages=_plural(len(reads), 'page', 'pages'))})
    compiled = [e for r in held_rows.values() for e in r.get('journal') or [] if e.get('event') == 'compiled']
    if compiled:
        at = max(str(e.get('at') or '') for e in compiled)
        held = _and([rel._channel_short(s, channels) for s, r in held_rows.items() if manu.is_held(r)]) or 'no surface'
        version = (feed_version or {}).get('version') or (feed_version or {}).get('id') if isinstance(feed_version, dict) \
            else feed_version
        out.append({'kind': 'compiled', 'at': at, 'day': _day(at), 'text': T['history.compiled'],
                    'detail': T['history.compiled.detail'].format(version=version, held=held) if version
                    else T['history.compiled.detail.unversioned'].format(held=held)})
    if reads:
        oldest = min(str(r['observed_at']) for r in reads)
        out.append({'kind': 'first_read', 'at': oldest, 'day': _day(oldest), 'text': T['history.first'],
                    'detail': None})
    out.sort(key=lambda e: e['at'], reverse=True)
    return out, every


def build_product_record(v: dict, record: dict, *, prices: Optional[List[dict]], retailers: List[str],
                         own_domains: Iterable[str], feed_rows: Optional[List[dict]], charts: Optional[Dict[str, list]],
                         drift: List[dict], reference: Optional[dict], flags: List[dict],
                         attribute_answers: List[dict], deals: Optional[dict], channels: Dict[str, dict],
                         held_rows: Dict[str, dict], feed_version, club_lines: List[dict], brand: Optional[str],
                         hero: dict) -> dict:
    """B2: GET /record?product=<sku> for a brand at retail, one feed SKU: {mode, kind, sku, title, sub, line,
    status, state, hero, record, differences (B1), issues, issues_none, surfaces, variants, history,
    history_all}."""
    from app.services import console_release as rel
    own = {_dom(d) for d in own_domains or () if d}
    domain = next(iter(sorted(own)), None) or 'the brand site'
    chart = sku_chart(prices, v, charts=charts, own_domains=own_domains, brand=brand)
    weight = rel.weight_of(chart, v.get('label')) if chart else None
    page = line_page(prices, v, own_domains, brand)
    markup = markup_differences(v, page['json_ld'], brand=brand) if page else \
        {'matched': None, 'node': None, 'differences': [], 'not_in_markup': []}
    shelf = [r for r in rel.variant_rows(prices, v) if r.get('role') != 'own' and _dom(r.get('retailer_domain')) not in own]
    mine_drift = _drift_for(drift, reference, v, brand)
    st = sku_state(variant_lines(record, v))
    issues = build_issues(v, page=page, charts=charts, feed_rows=feed_rows, brand=brand, domain=domain,
                          attribute_answers=attribute_answers, drift=mine_drift, shelf_rows=shelf, flags=flags,
                          chart_weight=weight, markup=markup)
    history, every = record_history(v, shelf_rows=shelf, page=page, held_rows=held_rows, channels=channels,
                                    domain=domain, feed_version=feed_version)
    succ = v.get('successor') or {}
    return {
        'mode': 'manufacturer', 'kind': 'product', 'sku': sku_of(v), 'record_ref': record.get('record_ref'),
        'title': v.get('product_name') or record.get('name'), 'line': _short_line(v.get('product_name'), brand),
        'sub': record_sub(v, chart), 'gtin': v.get('gtin'),
        'state': st['state'], 'disagree': {'n': st['n'], 'which': st['which']}, 'status': state_status(st),
        'retired': {'successor': {'productName': succ.get('product_name'), 'sku': succ.get('sku')} if succ else None}
        if v.get('status') == 'retired' else None,
        'hero': hero,
        'record': record_rows(v, page=page, shelf_rows=shelf, retailers=retailers, own=own, domain=domain, chart=chart,
                              deals=deals, drift=mine_drift, club_lines=club_lines, brand=brand, markup=markup),
        'differences': [{**d, 'matched_by': markup['matched']} for d in markup['differences']],
        'not_in_markup': markup['not_in_markup'],
        'issues': issues, 'issues_none': None if issues else T['issues.none'],
        'surfaces': record_surfaces(record, st, channels),
        'variants': record_variants_read(v, shelf, deals=deals, drift=mine_drift, chart_weight=weight),
        'history': history, 'history_all': every,
    }
