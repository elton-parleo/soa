"""
2T-3: eleven items from the Oct 26 walk of the brand Overview and TrueSync
(org 12, Pampers, cycle FL15-pampers-20261024, the compile-and-hold of Oct
26). Each test quotes what the live console showed.

Two kinds of input, each named where it is used:
  - the 2T-1 harness (2P-1's pair with supply #33's answers RECORDED,
    tests/fixtures/console/supply_2r1/PROVENANCE.md), served end to end;
  - FL15-shaped rows: FL15's retailer-prices and deals are production reads
    this pass never makes, so the rows that state FL15's shape (Amazon read by
    our own fetch, Target by the hosted render, Walmart walled on some SKUs;
    the Amazon list price cut and the Walmart Rollback) are built here in
    supply's served shape (truesync/fullloop/prices.py _row, deals.py) and say
    so. No model call, no production read.
"""
from app.services import console_brand_overview as bo
from app.services import console_release as rel

OWN = ['pampers.com']
SKUS = ['sku_pg_swd_nb_84', 'sku_pg_swd_s1_96', 'sku_pg_amore_s1_132', 'sku_pg_zzz_s4_104', 'sku_pg_cr360_s3_168',
        'sku_pg_swultra_s3']


def _shelf(domain, sku, method, price, at='2026-10-24T14:00:00'):
    """One FL15-shaped retailer-prices row (supply's served row, the fields these readers use)."""
    return {'retailer_domain': domain, 'role': 'retailer', 'sku': sku, 'gtin': None, 'variant_ref': f"feed_sku:{sku}",
            'observed_at': at, 'method': method, 'price': price,
            'read_status': 'ok' if method not in rel.WALLED_METHODS else 'blocked'}


def fl15_shelf_rows():
    """FL15's shelf as the walk found it: Amazon read by our own fetch on every SKU but one, Target by the hosted
    render (regex_rendered) on four, Walmart walled on three SKUs and read on three."""
    rows = []
    for i, sku in enumerate(SKUS):
        rows.append(_shelf('amazon.com', sku, 'none' if i == 5 else 'json_ld' if i % 2 else 'regex',
                           None if i == 5 else '27.97'))
        rows.append(_shelf('target.com', sku, 'none' if i in (3, 5) else 'regex_rendered',
                           None if i in (3, 5) else '27.99'))
        rows.append(_shelf('walmart.com', sku, 'none' if i in (0, 2, 4) else 'regex', None if i in (0, 2, 4) else '27.97'))
    return rows


def _old_activity_line(prices):
    """The activity's shelf line as 2T-1 counted it (any SKU walled walls its retailer), for the before."""
    shelf = [r for r in prices if r.get('observed_at')]
    domains = {r['retailer_domain'] for r in shelf}
    walled = sorted({bo._name(r['retailer_domain']) for r in shelf if r.get('price') is None
                     and r.get('method') in ('none', 'wall')})
    return bo.T['activity.shelf'].format(n=len(domains), read=len(domains) - len(walled), walled=bo.T[
        'activity.shelf.walled'].format(names=bo.manu._and(walled)) if walled else '')


# ── 1: the activity and the timeline read the shelf one way ─────────────

def test_the_activity_counts_shelf_reads_the_way_the_timeline_does():
    prices = fl15_shelf_rows()
    before = _old_activity_line(prices)
    assert before == 'Shelf reads at 3 retailers: 0 read, Amazon, Target and Walmart walled'   # what the walk saw
    activity = bo.build_activity(cycle={'status': 'complete'}, first_at=None, last_at=None, answers=0, usable=0,
                                 agents=6, questions=0, prices=prices, own_domains=OWN, pubs=[], workspace=None)
    shelf = next(e for e in activity if e['stage'] == 'shelf')
    assert shelf['text'] == 'Shelf reads at 3 retailers: 3 read'
    assert (shelf['read'], shelf['walled'], shelf['walled_skus']) == (
        ['Amazon', 'Target', 'Walmart'], [], {'Amazon': 1, 'Target': 2, 'Walmart': 3})
    # the same helper on one record's rows (the Zzz Size 4 SKU): Target walled on it, Amazon and Walmart read
    zzz = [r for r in prices if r['sku'] == 'sku_pg_zzz_s4_104']
    assert rel.shelf_reads(zzz, OWN)['read'] == ['Amazon', 'Walmart']
    assert rel.shelf_reads(zzz, OWN)['walled'] == ['Target']
    line = rel.timeline([{'sku': 'sku_pg_zzz_s4_104'}], {}, prices=prices, own_domains=OWN, lines=[], cycle=None,
                        channels={})
    assert [e['what'] for e in line] == ['Shelf read: Amazon and Walmart read. Target walled']
    # a retailer walled on every SKU is named
    walled = [r for r in prices if r['retailer_domain'] != 'walmart.com'] + \
        [_shelf('walmart.com', s, 'none', None) for s in SKUS]
    activity = bo.build_activity(cycle={'status': 'complete'}, first_at=None, last_at=None, answers=0, usable=0,
                                 agents=6, questions=0, prices=walled, own_domains=OWN, pubs=[], workspace=None)
    assert next(e for e in activity if e['stage'] == 'shelf')['text'] == \
        'Shelf reads at 3 retailers: 2 read, Walmart walled'


# ── 2: a record's weight is its own line's chart on pampers.com, else absent ─

SWADDLERS_PAGE = 'Pampers® Swaddlers™ Diapers for Babies and Newborns'
SWADDLERS_CHART = [{'size': 'newborn', 'min': None, 'max': 10.0}, {'size': '1', 'min': 8.0, 'max': 14.0},
                   {'size': '3', 'min': 13.0, 'max': 26.0}, {'size': '4', 'min': 15.0, 'max': 34.0}]
ULTRA = {'variant_id': 'sku_pg_swultra_s3', 'sku': 'sku_pg_swultra_s3', 'label': 'Size 3, 180 ct', 'count': 180,
         'product_name': 'Pampers Swaddlers Ultra Day + Night', 'gtin': None, 'retailers': [], 'status': 'active'}


def _own(sku, name, chart, at='2026-10-24T02:00:00'):
    """A pampers.com row in supply's served shape (2O-6: json_ld, size_chart, bullets beside observed_at)."""
    return {'retailer_domain': 'pampers.com', 'role': 'own', 'sku': sku, 'gtin': None, 'observed_at': at,
            'method': 'none_by_design', 'price': None, 'json_ld': {'name': name}, 'size_chart': chart, 'bullets': []}


def _old_record_chart(prices, variants):
    """2T-1's record_chart (any chart on the record's own rows), for the before."""
    rows = [r for v in variants for r in rel.variant_rows(prices, v) if r.get('size_chart')]
    return rows[0]['size_chart'] if rows else None


def test_a_line_with_no_chart_gets_no_weight_never_another_line_s():
    """Derived, FL15's Ultra row: the feed's pampers.com URL for Swaddlers Ultra Day + Night lands on the Swaddlers page
    (supply's test_a_redirected_brand_page_serves_where_it_landed is this case), so supply serves the Ultra SKU's own
    row with the Swaddlers page's markup and chart. 2T-1 took that chart for the Ultra record: Size 3, 13 to 26 lb."""
    prices = [_own('sku_pg_swultra_s3', SWADDLERS_PAGE, SWADDLERS_CHART),
              _own('sku_pg_swd_s1_96', SWADDLERS_PAGE, SWADDLERS_CHART)]
    assert rel.weight_of(_old_record_chart(prices, [ULTRA]), ULTRA['label']) == '13 to 26 lb'   # what the walk saw
    chart = rel.record_chart(prices, [ULTRA], own_domains=OWN, brand='Pampers')
    assert chart is None
    assert rel.subtitle([ULTRA], chart) == 'Size 3, 180 ct'
    record = {f['k']: f for f in rel.master_record([ULTRA], prices=prices, retailers=[], own_domains=OWN, chart=chart)}
    assert (record['Size and weight']['v'], record['Size and weight']['note']) == ('Size 3', 'No chart on pampers.com')
    # Swaddlers itself keeps its own chart
    swd = {**ULTRA, 'sku': 'sku_pg_swd_s1_96', 'variant_id': 'sku_pg_swd_s1_96', 'label': 'Size 1, 96 ct',
           'product_name': 'Pampers Swaddlers'}
    assert rel.weight_of(rel.record_chart(prices, [swd], own_domains=OWN, brand='Pampers'), swd['label']) == '8 to 14 lb'
    # no weight to read back against: the record's weight answers are not judged on it
    answer = {'platform': 'chatgpt', 'variant_id': 'sku_pg_swultra_s3', 'verdict': 'match', 'run_id': 1,
              'stated': {'min': 13, 'max': 26}, 'truth': {'min': 13, 'max': 26}}
    assert rel.readback([ULTRA], attribute_answers=[answer], true_value_rows=[], promo=None, deals=None,
                        brand='Pampers', charted=False) == []
    # the lead signal's facts: /reference's truth for Ultra (supply's, from the same page) is not Ultra's
    reference = {'attributes': [{'variant_ref': 'feed_sku:9', 'variant_label': 'Size 3, 180 ct',
                                 'product_name': 'Pampers Swaddlers Ultra Day + Night', 'truth': {'min': 13, 'max': 26}}]}
    drift = [{'variant_ref': 'feed_sku:9', 'kind': 'page', 'field': 'swaddlers_ultra.size_3.weight (walmart.com)',
              'was': '12 to 22 lb', 'now': '13 to 26 lb'}]
    charts = rel.line_charts(prices, OWN, 'Pampers')
    assert bo.size_chart_signal(drift, reference, None, domain='pampers.com', brand='Pampers', charts=charts,
                                feed_rows=[]) is None
    assert bo.size_chart_signal(drift, reference, None, domain='pampers.com', brand='Pampers')['facts']['sources'][0] == \
        {'who': 'pampers.com', 'range': '13 to 26 lb', 'prov': 'brand'}   # 2T-1's reading, for the before


# ── 4: the size-chart signal names both ranges and the lines on each ─────

def _chart(*ranges):
    return [{'size': s, 'min': lo, 'max': hi} for s, lo, hi in ranges]


def test_the_size_chart_detail_names_both_ranges_and_their_lines():
    """FL15-shaped: five lines' own pages on pampers.com, each with its own chart (the facts r5 reads)."""
    small = _chart(('3', 13.0, 26.0), ('4', 15.0, 34.0))
    big = _chart(('3', 16.0, 28.0), ('4', 22.0, 37.0))
    prices = [_own('a', SWADDLERS_PAGE, small), _own('b', 'Pampers® Baby-Dry™ Diapers', small),
              _own('c', 'Pampers® AMORE Diapers', small), _own('d', 'Pampers® Cruisers 360° Pull-on Diapers | Pampers', big),
              _own('e', 'Pampers® Zzz | Pampers', big)]
    feed = [{'product_name': n, 'variant_label': 'Size 4'} for n in (
        'Pampers Swaddlers', 'Pampers Baby-Dry', 'Pampers AMORE', 'Pampers Cruisers 360', 'Pampers Zzz')] + \
        [{'product_name': 'Pampers Pure Protection', 'variant_label': 'Size 1', 'lifecycle': 'retired'}]
    reference = {'attributes': [
        {'variant_ref': 'r1', 'variant_label': 'Size 4', 'product_name': 'Pampers Swaddlers', 'truth': {'min': 15, 'max': 34}},
        {'variant_ref': 'r2', 'variant_label': 'Size 4, 104 ct', 'product_name': 'Pampers Zzz',
         'truth': {'min': 22, 'max': 37}}]}
    drift = [{'variant_ref': 'r1', 'kind': 'page', 'field': 'swaddlers.size_4.weight (amazon.com)', 'was': '22 to 37 lb',
              'now': '15 to 34 lb'},
             {'variant_ref': 'r2', 'kind': 'markup', 'field': 'zzz.size_4.weight (markup)', 'was': '15 to 34 lb',
              'now': '22 to 37 lb'}]
    signal = bo.size_chart_signal(drift, reference, None, domain='pampers.com', brand='Pampers',
                                  charts=rel.line_charts(prices, OWN, 'Pampers'), feed_rows=feed)
    assert signal['title'] == 'pampers.com runs two Size 4 charts, and agents repeat both.'
    assert signal['detail'].startswith('Swaddlers, Baby-Dry and AMORE Size 4 are 15 to 34 lb, Cruisers 360 and Zzz '
                                       'Size 4 are 22 to 37 lb. Zzz Size 4 markup says 15 to 34 lb, the chart 22 to 37 lb.')
    assert signal['facts']['two'][0]['groups'] == [
        {'range': '15 to 34 lb', 'lines': ['Swaddlers', 'Baby-Dry', 'AMORE']},
        {'range': '22 to 37 lb', 'lines': ['Cruisers 360', 'Zzz']}]


# ── 3: one deal label, never supply's shelf text ────────────────────────

from soa_shared import promo_pass_through as ppt  # noqa: E402


def fl15_deals():
    """FL15-shaped /deals (supply's deals.py shape): the Amazon list price cut on AMORE Size 1 and the Walmart Rollback,
    each with the shelf's own words in `text` / `evidence`, as the walk showed them."""
    return {'read_date': '2026-10-24', 'deals': [
        {'retailer_domain': 'amazon.com', 'kind': 'rollback_or_was', 'value': None, 'value_unit': None, 'terms': None,
         'text': '$36.18 with 25 percent savings -25%', 'variants': [
             {'sku': 'sku_pg_amore_s1_132', 'variant_label': 'Size 1, 132 ct', 'product_name': 'Pampers AMORE',
              'shelf_price': '36.18', 'price': '36.18', 'was_price': '47.99',
              'evidence': '$36.18 with 25 percent savings -25% $ 36 . 18 $0.27 per count List Price: $47.99'}]},
        {'retailer_domain': 'walmart.com', 'kind': 'rollback_or_was', 'value': None, 'value_unit': None, 'terms': None,
         'text': 'Rollback $24.97 $27.97', 'variants': [
             {'sku': 'sku_pg_swd_nb_84', 'variant_label': 'Newborn, 84 ct', 'product_name': 'Pampers Swaddlers',
              'shelf_price': '24.97', 'price': '24.97', 'was_price': '27.97', 'evidence': 'Rollback $24.97 was $27.97'}]}]}


def test_one_deal_label_feeds_the_signal_its_detail_the_live_cell_and_the_shelf_row():
    deals = fl15_deals()
    amazon, walmart = deals['deals']
    assert (ppt.label(amazon), ppt.label(walmart)) == ('Amazon: 25% off, $36.18 from $47.99',
                                                       'Walmart: Rollback, 11% off, $24.97 from $27.97')
    answers = [{'run_id': i, 'surface': 'consumer_ui', 'intent': 'cheapest_place',
                'source_ref': {'variant_id': 'sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132'},
                'text': 'Amazon has it for about $36.'} for i in range(3)]
    promo = ppt.count(answers, deals)
    signal = bo.deal_signal(promo, 'Oct 24')
    # before: "Amazon: 25% off list price on AMORE Size 1, $36.18 from $47.99 ran on 1 SKU …
    #          $36.18 with 25 percent savings -25% was live"
    assert signal['title'] == 'Amazon: 25% off, $36.18 from $47.99 ran on 1 SKU. No answer named it.'
    assert signal['detail'] == ('Amazon: 25% off, $36.18 from $47.99 was live on 1 SKU on Oct 24. 0 of 3 cheapest-place '
                                'answers on those SKUs mentioned it.')
    # before: "Amazon $36.18 with $36.18 with 25 percent savings -25%"
    product = {'sku': 'sku_pg_amore_s1_132'}
    assert bo.live_deals(product, deals) == ['Amazon: 25% off, $36.18 from $47.99']
    assert bo.live_deals({'sku': 'sku_pg_swd_nb_84'}, deals) == ['Walmart: Rollback, 11% off, $24.97 from $27.97']
    variant = {'variant_id': 'sku_pg_amore_s1_132', 'sku': 'sku_pg_amore_s1_132', 'label': 'Size 1, 132 ct'}
    shelf = [l for l in rel.readback([variant], attribute_answers=[], true_value_rows=[], promo=promo, deals=deals,
                                     brand='Pampers') if l['agent'] == 'shelf']
    assert [l['said'] for l in shelf] == ['Amazon: 25% off, $36.18 from $47.99']
    for text in (signal['title'], signal['detail'], shelf[0]['said']):
        assert 'percent savings' not in text and '-25%' not in text


# ── 5: the shelf row's verdict is the promo rule's ──────────────────────

def test_the_shelf_row_is_right_only_when_every_answer_named_the_deal():
    """FL15's Walmart Rollback row read "Named in 3 of 6 answers · Right"."""
    deals = fl15_deals()
    variant = {'variant_id': 'sku_pg_swd_nb_84', 'sku': 'sku_pg_swd_nb_84', 'label': 'Newborn, 84 ct'}

    def verdict(named, asked):
        texts = ['Walmart has a Rollback at $24.97.'] * named + ['Try Target.'] * (asked - named)
        answers = [{'run_id': i, 'surface': 'consumer_ui', 'intent': 'cheapest_place', 'text': t,
                    'source_ref': {'variant_id': 'sku_pg_swd_nb_84', 'sku': 'sku_pg_swd_nb_84'}}
                   for i, t in enumerate(texts)]
        promo = ppt.count(answers, deals)
        row = next(l for l in rel.readback([variant], attribute_answers=[], true_value_rows=[], promo=promo,
                                           deals=deals, brand='Pampers') if l['agent'] == 'shelf')
        return row['truth'], row['verdict']
    assert verdict(3, 6) == ('Named in 3 of 6 answers', 'partial')
    assert verdict(6, 6) == ('Named in 6 of 6 answers', 'right')
    assert verdict(0, 6) == ('Named in 0 of 6 answers', 'missed')


# ── 6: the compiler names the rules that apply and the ones that are on ─

def test_the_compiler_serves_the_rules_that_apply_apart_from_the_rules_on():
    """FL15's footer read "rules r1, r2, r5" beside "Compliance rules: 0 of 6 on". The recorded schema_org row of
    #33 (every rule off); then derived: the same row as a compile with r1 and r5 on writes it (their off flags gone)."""
    import copy
    from tests import console_fixture_2r2 as f2r2
    row = next(r for r in f2r2.mine(f2r2.body('publications-held')) if r['channel_slug'] == 'schema_org'
               and r['record_ref'].endswith('00037000833970'))
    rules = [{'code': f"r{i}", 'on': False} for i in range(1, 7)]
    c = rel.compiler({'schema_org': row}, {}, rules)[0]
    assert (c['rules_relevant'], c['rules_applied'], c['rules_line']) == (['r1', 'r2', 'r5'], [],
                                                                          'r1, r2, r5 apply, none on')
    on = copy.deepcopy(row)
    on['expressiveness'] = [e for e in on['expressiveness'] if e['field'] not in ('rule_r1', 'rule_r5')]
    rules_on = [{**r, 'on': r['code'] in ('r1', 'r5')} for r in rules]
    c = rel.compiler({'schema_org': on}, {}, rules_on)[0]
    assert (c['rules_relevant'], c['rules_applied'], c['rules_line']) == (['r1', 'r2', 'r5'], ['r1', 'r5'],
                                                                          'r1, r2, r5 apply, r1 and r5 on')
    # r6 applies only to a record with a retired variant
    assert 'r6' not in rel.compiler({'schema_org': on}, {}, [{'code': 'r6', 'on': True}])[0]['rules_relevant']
    assert rel.compiler({'schema_org': on}, {}, [{'code': 'r6', 'on': True}], retired=True)[0]['rules_applied'] == ['r6']


# ── 7: the workspace counts fields per record, on one scale ─────────────

def _old_fields(rows):
    """2T-1's count: every expressiveness line of every held row (an info line counted as carried)."""
    counts = {'carried': 0, 'approximated': 0, 'dropped': 0}
    for row in rows:
        for e in row.get('expressiveness') or []:
            if rel.RULE_FLAG.match(str(e.get('field') or '')):
                continue
            sev = e.get('severity')
            counts['carried' if sev == 'info' else 'approximated' if sev == 'approximated' else 'dropped'] += 1
    return counts


def test_the_workspace_counts_distinct_fields_per_record():
    """On #33's recorded hold (4 records, held on Site markup and Manufacturer Center, blocked on ACP)."""
    from tests import console_fixture_2r2 as f2r2
    rows = f2r2.mine(f2r2.body('publications-held'))
    held = [r for per in rel.hold(rows).values() for r in per.values()]
    before, after = _old_fields(held), rel._fields(rel.hold(rows).values())
    print(f"\n7 before {before} after {after}")
    assert before == {'carried': 5, 'approximated': 0, 'dropped': 95}
    per = []
    for ref, chans in rel.hold(rows).items():
        mine = [r for r in chans.values() if r['reason'] == 'held_for_merchant']
        carried = {f for r in mine for f in rel.manu.carried_fields(r['payload'])}
        dropped = {e['field'] for r in mine for e in r['expressiveness'] if e['severity'] == 'dropped'} - carried
        per.append((len(carried), len(dropped)))
    assert (after['carried'], after['dropped']) == (sum(c for c, _ in per), sum(d for _, d in per))
    # one scale: no record's dropped count exceeds the fields it was asked to carry and drop
    assert after['dropped'] < before['dropped'] and after['carried'] > before['carried']
