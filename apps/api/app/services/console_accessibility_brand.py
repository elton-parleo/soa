"""
2T-4 (4): Accessibility for a brand at retail (supply's mode manufacturer).

FL15's Accessibility read "Product markup on product pages 0 of 36" while
pampers.com's pages carry ProductGroup JSON-LD (2O-6 serves the brand page's
`json_ld` on its own retailer-prices rows): the check counts reads whose
method is `json_ld`, a priced Offer, over every page read, the retailers'
included. A brand's own pages set no price (supply reads them `method: none`),
so the brand's markup was never what the check looked at.

Brand mode serves the demo's six checks over the brand's own pages, N the
feed's distinct pages on the brand's site (its product_url_<brand domain>
links, served as each feed row's retailers[].url):

  robots         robots.txt lets the answer-time agents read the brand's
                 pages: the access run's per-token verdicts on the brand's
                 own rows (`allow` of every token read there)
  html           product pages served in plain HTML: the feed's pages read
                 (read_status ok or empty) by an own fetch, not a hosted render
  product_group  a ProductGroup with an Offer per retailer and a gtin13: the
                 page's markup is a ProductGroup, every variant carries a
                 gtin13, and an Offer for each retailer the feed lists.
                 2T-7 (7): the note says what the markup carries, "ProductGroup
                 with gtin13 on 7 of 7. No Offer per retailer in the markup",
                 so a 0 that is absence (no Offer node on any page, what
                 pampers.com serves and the compile-and-hold fixes) reads as
                 absence (`offers_absent`), not as a markup that disagrees
  prices         retailer prices filled in the markup: the variants with an
                 Offer that carries a price ("3 Swaddlers sizes only")
  gtin           GTINs in the markup well formed: none that is a GTIN only
                 zero-padded (2S-1's read). 2T-7 (3): the value names the lines
                 that drop a digit, as the demo words it ("AMORE and Ultra drop
                 the leading zero"), the count of them in the note
  weight         weight in the markup contradicts the size selector (2M-1's
                 markup rows, rm.build_weight_drift). 2T-7 (3): the count is the
                 pages whose markup states a range the brand's chart does not,
                 of the pages whose markup states one, and the value and the
                 note name them ("3 of 4 pages: Baby-Dry, Cruisers 360 and
                 Zzz")

The retailer pages keep their own checks (console_parity.build_access_checks
over the retailer rows only), `retailer_checks`. The hero comes from the data:
when every page is served and every agent may read it, "pampers.com served
every product page on Oct 24. What agents find there is the problem."; and
each block that exists, named by retailer ("Amazon's robots.txt disallows 4 of
6 agents. Walmart challenged 3 page reads."). House rules: no semicolons, no
dashes.

Nothing here changes the score: Catalog & Context still counts the reads
console_score.crawl_counts counts.
"""
from typing import Dict, Iterable, List, Optional

from app.services import console_manufacturer as manu
from app.services import console_parity as parity
from app.services import console_read_models as rm
from app.services import console_release as rel
from soa_shared.retailers import retailer_key

T = {
    'robots': 'robots.txt lets answer-time agents read {domain}',
    'html': 'Product pages served in plain HTML',
    'product_group': 'ProductGroup with an Offer per retailer and gtin13',
    'prices': 'Retailer prices filled in markup',
    'gtin': 'GTINs in markup well formed',
    'weight': 'Weight in markup contradicts the size selector',
    'value': '{n} of {d}',
    'value.weight': '{n} of {d} pages: {lines}',
    'value.weight.none': '0 of {d} pages',
    'value.gtin': '{lines} {verb} the leading zero',
    'basis.robots': "the access run's robots verdicts per answer-time token on {domain}'s product pages",
    'basis.html': "the feed's {d} pages on {domain}, read by our own fetch (read_status ok or empty), no hosted render",
    'basis.product_group': 'ProductGroup with gtin13 on {both} of {d}. An Offer for each retailer the feed lists on {offers}',
    'basis.product_group.no_offer': 'ProductGroup with gtin13 on {both} of {d}. No Offer per retailer in the markup',
    'basis.prices': 'variants in the markup with an Offer that carries a price',
    'basis.prices.some': '{lines} only',
    'basis.prices.none': 'no variant in the markup carries a retailer price',
    'basis.gtin': '{n} of {d} GTINs in the markup drop the leading zero: {lines}',
    'basis.gtin.ok': 'every GTIN in the markup is one as written',
    'basis.weight': "pages whose markup states a weight range {domain}'s size selector does not: {lines}",
    'basis.weight.ok': "every weight range in the markup matches {domain}'s size selector",
    'hero.served': '{domain} served every product page on {day}. What agents find there is the problem.',
    'hero.partly': '{domain} served {n} of {d} product pages on {day}.',
    'hero.none': '{domain} served none of its {d} product pages to our reader.',
    'hero.own_disallow': "{domain}'s robots.txt disallows {n} of {d} agents.",
    'block.disallow': "{name}'s robots.txt disallows {n} of {d} agents",
    'block.challenged': '{name} challenged {n} page reads',
    'block.challenged.one': '{name} challenged 1 page read',
}

READ = ('ok', 'empty')


def _domain(value) -> str:
    return str(value or '').lower().removeprefix('www.')


def feed_pages(feed_rows: Optional[List[dict]], own_domains: Iterable[str]) -> List[str]:
    """The feed's distinct pages on the brand's own sites, in feed order (rel._url_key)."""
    urls = [r.get('url') for row in feed_rows or [] for r in row.get('retailers') or [] if isinstance(r, dict)]
    return rel.own_urls(urls, own_domains)


def _own_reads(prices: Optional[List[dict]], pages: List[str], own_domains: Iterable[str]) -> Dict[str, dict]:
    """Each feed page's newest own read, by page."""
    own = {_domain(d) for d in own_domains or () if d}
    out: Dict[str, dict] = {}
    for r in sorted(prices or [], key=lambda r: str(r.get('observed_at') or ''), reverse=True):
        if not (r.get('role') == 'own' or _domain(r.get('retailer_domain')) in own):
            continue
        key = rel._url_key(r.get('url'))
        if key in pages and key not in out:
            out[key] = r
    return out


def _check(key, name, got, of, *, good_when_zero=False, value=None, basis=None, unit='pages') -> dict:
    out = dict(parity._check(name, got, of, good_when_zero=good_when_zero, unit=unit, key=key))
    if value is not None and of:
        out['value'] = value
    if basis:
        out['basis'] = basis
    return out


def _not_checked(key, name, why) -> dict:
    return {'name': name, 'value': 'not checked', 'status': 'not_checked', 'checked': False, 'key': key, 'basis': why}


def _tokens_by_domain(access: Optional[dict]) -> Dict[str, Dict[str, str]]:
    """{domain: {token: verdict}} from the access grid's rows (their page url's host)."""
    from clients import truesync_client as supply_fields
    out: Dict[str, Dict[str, str]] = {}
    grid = ((access or {}).get('accessibility') or {}).get('grid') or (access or {}).get('grid') or {}
    for row in grid.get('rows') or []:
        url = ((row.get('detail') or {}).get('url')) or ''
        host = _domain(rel._url_key(url).split('/', 1)[0]) if rel._url_key(url) else _domain(row.get('source'))
        for t in supply_fields.token_rules(row) or []:
            if t.get('token'):
                out.setdefault(host, {}).setdefault(t['token'], t.get('verdict'))
    return out


def _offers(node: dict) -> List[dict]:
    offers = node.get('offers')
    if isinstance(offers, dict):
        offers = offers.get('offers') if isinstance(offers.get('offers'), list) else [offers]
    return [o for o in offers or [] if isinstance(o, dict)]


def _offer_retailer(offer: dict) -> Optional[str]:
    seller = offer.get('seller')
    name = seller.get('name') if isinstance(seller, dict) else seller
    return retailer_key(offer.get('url')) or retailer_key(name)


def _is_group(ld) -> bool:
    kind = (ld or {}).get('@type') if isinstance(ld, dict) else None
    return kind == 'ProductGroup' or (isinstance(kind, list) and 'ProductGroup' in kind)


def build(*, prices: Optional[List[dict]], feed_rows: Optional[List[dict]], reference: Optional[dict],
          access: Optional[dict], robots: Optional[list], own_domains: List[str], retailers: Iterable[str],
          brand: Optional[str]) -> dict:
    """{checks, brand_pages, hero}: see the module docstring."""
    domain = next((d for d in own_domains if d), None) or 'the brand site'
    pages = feed_pages(feed_rows, own_domains)
    reads = _own_reads(prices, pages, own_domains)
    n = len(pages)
    read = {k: r for k, r in reads.items() if r.get('read_status') in READ}
    plain = [k for k, r in read.items() if r.get('reference_source') != 'hosted_render']
    read_at = max((str(r['observed_at']) for r in read.values() if r.get('observed_at')), default=None)
    day = rm._short_day(read_at) if read_at else None

    # robots on the brand's own pages
    tokens = _tokens_by_domain(access)
    mine = {t: v for d in own_domains for t, v in tokens.get(_domain(d), {}).items()}
    if mine:
        allowed = sum(1 for v in mine.values() if v == 'allow')
        robots_row = _check('robots', T['robots'].format(domain=domain), allowed, len(mine), unit='agents',
                            basis=T['basis.robots'].format(domain=domain))
    else:
        entry = next((e for e in robots or [] if _domain(e.get('retailer_domain')) in {_domain(d) for d in own_domains}),
                     None)
        why = (f"robots.txt on {domain} was {entry.get('robots_status')}, so no agent's verdict was read" if entry
               else f"the access run read no robots verdict on {domain}'s product pages")
        robots_row = _not_checked('robots', T['robots'].format(domain=domain), why)

    # the markup: ProductGroup, gtin13, an Offer per retailer the feed lists for the page, prices
    owned = {_domain(d) for d in own_domains}
    listed = {_domain(d) for d in retailers or () if d} - owned
    sold_at: Dict[str, set] = {}
    for row in feed_rows or []:
        links = [x for x in row.get('retailers') or [] if isinstance(x, dict)]
        page = next((rel._url_key(x.get('url')) for x in links if _domain(x.get('domain')) in owned and x.get('url')), None)
        if page:
            sold_at.setdefault(page, set()).update(_domain(x.get('domain')) for x in links
                                                   if x.get('domain') and _domain(x.get('domain')) not in owned)
    group = gtin13 = offered = full = both = any_offer = 0
    priced_by_line: Dict[str, int] = {}
    variants = priced = 0
    for key, r in read.items():
        ld = r.get('json_ld') or (manu.row_brand_page(r) or {}).get('json_ld')
        nodes = manu._products(ld)
        is_group = _is_group(ld)
        has_gtin13 = bool(nodes) and all(node.get('gtin13') for node in nodes)
        wanted = sold_at.get(key) or set()
        has_offers = bool(nodes) and all(wanted <= {_offer_retailer(o) for o in _offers(node)} and _offers(node)
                                         for node in nodes)
        group += is_group
        gtin13 += has_gtin13
        both += is_group and has_gtin13
        any_offer += any(_offers(node) for node in nodes)
        offered += has_offers
        full += is_group and has_gtin13 and has_offers
        line = manu._line_display(rel.page_line(ld.get('name') if isinstance(ld, dict) else None) or '', brand)
        for node in nodes:
            variants += 1
            if any(o.get('price') not in (None, '') for o in _offers(node)):
                priced += 1
                priced_by_line[line] = priced_by_line.get(line, 0) + 1
    group_row = _check('product_group', T['product_group'], full, n,
                       basis=T['basis.product_group' if any_offer else 'basis.product_group.no_offer'].format(
                           both=both, d=n, offers=offered))
    group_row.update(group=group, gtin13=gtin13, offered=offered, offers_absent=bool(read) and not any_offer)
    if priced_by_line and priced < variants:
        some = ', '.join(f"{k} {line} size{'s' if k != 1 else ''}" for line, k in priced_by_line.items())
        prices_basis = T['basis.prices.some'].format(lines=some)
    elif not priced:
        prices_basis = T['basis.prices.none']
    else:
        prices_basis = T['basis.prices']
    prices_row = _check('prices', T['prices'], priced, variants, unit='variants in markup', basis=prices_basis)

    # GTINs (2S-1's markup read)
    page_list = [{'url': k, 'observed_at': r.get('observed_at'), 'brand_page': manu.row_brand_page(r) or {}}
                 for k, r in read.items()]
    gtins = manu.markup_gtins(page_list)
    flags = [f for f in manu.gtin_flags(page_list, None, brand=brand) if f.get('where') == 'markup']
    bad_lines = list(dict.fromkeys(f['line'] for f in flags))
    gtin_row = _check('gtin', T['gtin'], len(gtins) - len(flags), len(gtins), unit='GTINs in markup',
                      value=T['value.gtin'].format(lines=manu._and(bad_lines), verb='drops' if len(bad_lines) == 1
                                                   else 'drop') if bad_lines else None,
                      basis=T['basis.gtin'].format(n=len(flags), d=len(gtins), lines=manu._and(bad_lines))
                      if bad_lines else T['basis.gtin.ok'])

    # weight in markup against the chart (2M-1's markup rows)
    attrs = [a for a in (reference or {}).get('attributes') or [] if isinstance(a, dict)]
    with_markup = list(dict.fromkeys(manu._line_display(a.get('product_name') or a.get('variant_label'), brand)
                                     for a in attrs if a.get('markup')))
    drift = rm.build_weight_drift(reference, brand=brand) if reference else []
    by_ref = {a.get('variant_ref'): a for a in attrs}
    wrong = list(dict.fromkeys(manu._line_display((by_ref.get(row.get('variant_ref')) or {}).get('product_name')
                                                  or (by_ref.get(row.get('variant_ref')) or {}).get('variant_label'),
                                                  brand)
                               for row in drift if row.get('kind') == 'markup'))
    weight_row = _check('weight', T['weight'], len(wrong), len(with_markup), good_when_zero=True,
                        unit='weights in markup',
                        value=T['value.weight'].format(n=len(wrong), d=len(with_markup), lines=manu._and(wrong))
                        if wrong else T['value.weight.none'].format(d=len(with_markup)),
                        basis=T['basis.weight'].format(domain=domain, lines=manu._and(wrong)) if wrong
                        else T['basis.weight.ok'].format(domain=domain))

    checks = [robots_row,
              _check('html', T['html'], len(plain), n, basis=T['basis.html'].format(d=n, domain=domain)),
              group_row, prices_row, gtin_row, weight_row]

    # the hero, from the data
    agents_ok = robots_row['status'] in ('ok', 'not_checked')
    if n and len(plain) == n and agents_ok and day:
        lead = T['hero.served'].format(domain=domain, day=day)
    elif plain and day:
        lead = T['hero.partly'].format(domain=domain, n=len(plain), d=n, day=day)
    else:
        lead = T['hero.none'].format(domain=domain, d=n)
    if robots_row.get('checked') and robots_row['status'] != 'ok':
        lead += ' ' + T['hero.own_disallow'].format(domain=domain, n=robots_row['of'] - robots_row['got'],
                                                    d=robots_row['of'])
    blocks = []
    challenged: Dict[str, int] = {}
    for r in prices or []:
        d = _domain(r.get('retailer_domain'))
        if d in listed and r.get('read_status') == 'challenged':
            challenged[d] = challenged.get(d, 0) + 1
    for d in sorted(listed):
        name = rm._retailer_name(d)
        verdicts = tokens.get(d) or {}
        no = sum(1 for v in verdicts.values() if v == 'disallow')
        if no:
            blocks.append({'domain': d, 'kind': 'robots', 'n': no, 'of': len(verdicts),
                           'text': T['block.disallow'].format(name=name, n=no, d=len(verdicts))})
        if challenged.get(d):
            k = challenged[d]
            blocks.append({'domain': d, 'kind': 'challenged', 'n': k,
                           'text': T['block.challenged.one'].format(name=name) if k == 1 else
                           T['block.challenged'].format(name=name, n=k)})
    text = ' '.join([lead] + [b['text'] + '.' for b in blocks])
    return {'checks': checks,
            'brand_pages': {'domain': domain, 'pages': n, 'read': len(read), 'plain_html': len(plain), 'read_at': read_at},
            'hero': {'text': text, 'lead': lead, 'blocks': blocks}}


def retailer_rows(reference: Optional[dict], own_domains: Iterable[str]) -> Optional[dict]:
    """The /reference body with the retailer pages only, for the retailer checks."""
    if reference is None:
        return None
    own = {_domain(d) for d in own_domains or () if d}
    return {**reference, 'rows': [r for r in reference.get('rows') or []
                                  if r.get('role') != 'own' and _domain(r.get('retailer_domain')) not in own]}
