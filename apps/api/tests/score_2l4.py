"""
2L-4: the score body as it was before the brand tiles, for the pins that
prove no score moves. The brand tiles' counts sit beside the five in each
surface's metric_counts, `metric_kind` says which five a merchant reads,
`metrics_by_kind` serves both sets and `metrics` is the merchant's; before
2L-4 `metrics` was always the retailer five.
"""
import copy

from app.services import console_score as score_svc

BRAND_KEYS = tuple(key for key, _name in score_svc.BRAND_METRICS)


def before_2l4(body: dict) -> dict:
    out = copy.deepcopy(body)
    by_kind = out.pop('metrics_by_kind', None)
    out.pop('metric_kind', None)
    if by_kind is not None:
        out['metrics'] = by_kind['retailer']
    for counts in (out.get('metric_counts') or {}).values():
        for key in BRAND_KEYS:
            counts.pop(key, None)
    return out


def retailer_rows(body: dict) -> list:
    """The five retailer rows, whatever the merchant's kind."""
    return (body.get('metrics_by_kind') or {}).get('retailer', body.get('metrics'))
