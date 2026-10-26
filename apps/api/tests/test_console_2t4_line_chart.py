"""
2T-4 (5): a line's chart is matched by its page, not its name.

After 2T-3 FL15's Swaddlers Ultra Size 3 row read "No chart on pampers.com"
and its master record "Size 3 · No chart", while Answers' attribute truth said
"pampers.com states as 13 to 26 lb". The Ultra page (/products/pampers-
swaddlers-ultra-diapers, the feed's own link) has a nine-size chart; the page
names the line "Pampers Swaddlers Ultra", the feed "Pampers Swaddlers Ultra
Day + Night", and 2T-3's name match failed.

The rule (console_release.chart_for): a record's chart is the chart of the
page its feed row links to on the brand's site (the row's product_url_<brand
domain>, served as its retailers[].url): the brand's own read whose `url` is
that link. A read that landed elsewhere (`final_url`) counts only when the
landed page names the row's line, so 2T-3's case, a link that lands on another
line's page, still gets nothing. Name match only for a row with no page there.
One chart for the matrix row, the master record, the readback and the lead
signal (feed_line_charts keys the charts by the feed's lines for it).

  * the feed row's line name differs from its page's: the page's chart;
  * the 2T-3 case (the link lands on the Swaddlers page): nothing;
  * a row with no page on the brand's site: the name match, as before;
  * the lead signal's facts read the same chart.

The Ultra page's chart is 2T-3's Swaddlers chart shape with nine sizes, built
here and said so: no recorded Ultra page is in the repository.
"""
from app.services import console_brand_overview as bo
from app.services import console_release as rel
from tests.test_console_2t3_overview_truesync import OWN, SWADDLERS_CHART, SWADDLERS_PAGE, ULTRA, _own

ULTRA_URL = 'https://www.pampers.com/en-us/products/pampers-swaddlers-ultra-diapers'
SWADDLERS_URL = 'https://www.pampers.com/en-us/products/pampers-swaddlers-diapers'
ULTRA_PAGE = 'Pampers® Swaddlers Ultra™ Diapers'
#: nine sizes, the shape the Oct 26 walk read on the Ultra page (values the fixture's, Size 3 13 to 26 lb)
ULTRA_CHART = [{'size': s, 'min': lo, 'max': hi} for s, lo, hi in (
    ('newborn', None, 10.0), ('1', 8.0, 14.0), ('2', 12.0, 18.0), ('3', 13.0, 26.0), ('4', 15.0, 34.0),
    ('5', 22.0, 38.0), ('6', 30.0, 42.0), ('7', 41.0, None), ('8', 46.0, None))]
#: the Ultra record variant with its feed row's own pampers.com link
ULTRA_LINKED = {**ULTRA, 'retailers': ['pampers.com'], 'retailer_urls': {'pampers.com': ULTRA_URL}}


def _page(sku, name, chart, url, final_url=None):
    return {**_own(sku, name, chart), 'url': url, 'final_url': final_url}


def test_a_feed_row_whose_line_name_differs_from_its_pages_gets_the_pages_chart():
    prices = [_page('sku_pg_swultra_s3', ULTRA_PAGE, ULTRA_CHART, ULTRA_URL),
              _page('sku_pg_swd_s1_96', SWADDLERS_PAGE, SWADDLERS_CHART, SWADDLERS_URL)]
    assert rel.line_key(ULTRA['product_name'], 'Pampers') != rel.line_key(ULTRA_PAGE, 'Pampers')   # the names differ
    assert rel.line_charts(prices, OWN, 'Pampers').get(rel.line_key(ULTRA['product_name'], 'Pampers')) is None
    chart = rel.record_chart(prices, [ULTRA_LINKED], own_domains=OWN, brand='Pampers')
    assert chart == ULTRA_CHART and len(chart) == 9
    assert rel.weight_of(chart, ULTRA['label']) == '13 to 26 lb'
    record = {f['k']: f for f in rel.master_record([ULTRA_LINKED], prices=prices, retailers=[], own_domains=OWN,
                                                   chart=chart)}
    assert record['Size and weight']['note'] == 'pampers.com size chart'
    assert '13 to 26 lb' in record['Size and weight']['v']


def test_a_link_that_lands_on_another_lines_page_still_gets_nothing():
    """2T-3's case: the Ultra link lands on the Swaddlers page (supply serves where it landed)."""
    prices = [_page('sku_pg_swultra_s3', SWADDLERS_PAGE, SWADDLERS_CHART, ULTRA_URL, final_url=SWADDLERS_URL)]
    assert rel.record_chart(prices, [ULTRA_LINKED], own_domains=OWN, brand='Pampers') is None
    # landing on the line's own page (a moved address) is the line's
    moved = [_page('sku_pg_swultra_s3', 'Pampers Swaddlers Ultra Day + Night', ULTRA_CHART, ULTRA_URL,
                   final_url=ULTRA_URL + '-v2')]
    assert rel.record_chart(moved, [ULTRA_LINKED], own_domains=OWN, brand='Pampers') == ULTRA_CHART


def test_a_row_with_no_page_on_the_brands_site_is_matched_by_name():
    prices = [_page('sku_pg_swd_s1_96', SWADDLERS_PAGE, SWADDLERS_CHART, SWADDLERS_URL)]
    swd = {**ULTRA, 'sku': 'x', 'variant_id': 'x', 'label': 'Size 1, 96 ct', 'product_name': 'Pampers Swaddlers'}
    assert rel.weight_of(rel.record_chart(prices, [swd], own_domains=OWN, brand='Pampers'), swd['label']) == '8 to 14 lb'
    # a page on the brand's site that was never read is no chart, and no name match stands in for it
    linked = {**swd, 'retailer_urls': {'pampers.com': 'https://www.pampers.com/en-us/products/unread'}}
    assert rel.record_chart(prices, [linked], own_domains=OWN, brand='Pampers') is None


def test_the_lead_signal_reads_the_same_chart():
    prices = [_page('sku_pg_swultra_s3', ULTRA_PAGE, ULTRA_CHART, ULTRA_URL),
              _page('sku_pg_swd_s1_96', SWADDLERS_PAGE, SWADDLERS_CHART, SWADDLERS_URL)]
    feed = [{'product_name': 'Pampers Swaddlers Ultra Day + Night', 'variant_label': 'Size 3, 180 ct',
             'retailers': [{'domain': 'pampers.com', 'url': ULTRA_URL}]},
            {'product_name': 'Pampers Swaddlers', 'variant_label': 'Size 1, 96 ct',
             'retailers': [{'domain': 'pampers.com', 'url': SWADDLERS_URL}]}]
    charts = rel.feed_line_charts(prices, feed, OWN, 'Pampers')
    assert charts[rel.line_key('Pampers Swaddlers Ultra Day + Night', 'Pampers')] == ULTRA_CHART
    reference = {'attributes': [{'variant_ref': 'feed_sku:9', 'variant_label': 'Size 3, 180 ct',
                                 'product_name': 'Pampers Swaddlers Ultra Day + Night', 'truth': {'min': 13, 'max': 26}}]}
    drift = [{'variant_ref': 'feed_sku:9', 'kind': 'page', 'field': 'swaddlers_ultra.size_3.weight (walmart.com)',
              'was': '12 to 22 lb', 'now': '13 to 26 lb'}]
    signal = bo.size_chart_signal(drift, reference, None, domain='pampers.com', brand='Pampers', charts=charts,
                                  feed_rows=feed)
    assert signal is not None   # 2T-3 dropped Ultra from the facts: its name found no chart
    # without the feed, the charts are line_charts' (by the page's own name), as before
    assert rel.feed_line_charts(prices, None, OWN, 'Pampers') == rel.line_charts(prices, OWN, 'Pampers')
