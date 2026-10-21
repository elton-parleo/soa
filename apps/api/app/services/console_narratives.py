"""
2L-3: the one-line narratives on the console's read models.

The lines are written by the worker (soa_shared/narratives.py) and read here,
beside the typed fields, as `narrative`: a string while the stored line's facts
digest is the facts' digest now, else null and the console shows its template.

  /answers           each Answer
  /overview          each product of the `all` surface (the facts are every
                     agent's quotes, so a single surface's row keeps its
                     template), and each signal's example answer (answerId)
  /true-value        each row, the caption under the product

With SOA_NARRATIVES_ENABLED off, or soa_narratives missing (migration
c8e2f4a6b1d3), every narrative is null. Never raises: a failed read serves
the templates.
"""
import logging
from typing import Dict, List

from soa_shared import narratives
from soa_shared import surfaces

logger = logging.getLogger(__name__)


def lines_for(conn, cycle_id: int) -> Dict[str, str]:
    try:
        return narratives.served(conn, cycle_id)
    except Exception:  # noqa: BLE001 - a narrative is never worth a 500
        logger.exception("[narratives] read failed for cycle %s", cycle_id)
        return {}


def with_answers(answers: List[dict], lines: Dict[str, str]) -> List[dict]:
    for a in answers:
        a['narrative'] = narratives.answer_line(lines, a.get('id'))
    return answers


def _row_keys(row: dict) -> tuple:
    feed = row.get('feed_sku')
    return (row.get('sku'), row.get('gtin'), row.get('variant_id'), f"sku:{feed}" if feed else None)


def with_overview(body: dict, lines: Dict[str, str]) -> dict:
    by_answer = {}
    for surface, block in (body.get('by_surface') or {}).items():
        for p in block.get('products') or []:
            p['narrative'] = narratives.product_line(lines, *_row_keys(p)) if surface == surfaces.ALL else None
        for s in block.get('signals') or []:
            answer_id = s.get('answerId')
            if answer_id not in by_answer:
                by_answer[answer_id] = narratives.answer_line(lines, answer_id)
            s['narrative'] = by_answer[answer_id]
    return body


def with_true_value(body: dict, lines: Dict[str, str]) -> dict:
    for row in body.get('rows') or []:
        row['narrative'] = narratives.product_line(lines, *_row_keys(row))
    return body
