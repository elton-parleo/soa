"""
2T-7 (2): a served body as it read before the cycle label, for the pins that
prove nothing else moved. Copy named a cycle by its code ("in
FL3-wiggle-and-snug-20261014", "in cycle FL4-…"); it now names it by its day
("in the Oct 14 cycle", rm.cycle_label), and each `previous` block carries
{day, name, since, vs} beside `cycle` (the Overview its `previous_label`). This
puts the codes back and drops those keys.
"""
import copy
import re

from sqlalchemy import text

from app.services import console_read_models as rm

LABEL_KEYS = ('day', 'name', 'since', 'vs')


def cycle_names(db) -> dict:
    """{"the Oct 14 cycle": code} for every cycle in the harness, in its study's zone."""
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(text(
            "SELECT id, cycle_code, created_at, start_date, study_type FROM soa_cycles")).mappings()]
        return {rm.cycle_label_of(conn, r)['name']: r['cycle_code'] for r in rows}


def before_2t7(body, names: dict):
    def back(s: str) -> str:
        for name, code in names.items():
            # the lede and the revenue basis read "in cycle <code>" for this cycle
            s = re.sub(rf"in {re.escape(name)}(?=\. (Every agent|Brand choice))", f"in cycle {code}", s)
            s = s.replace(name, code)
        return s

    def walk(x):
        if isinstance(x, dict):
            if 'cycle' in x and all(k in x for k in LABEL_KEYS):
                x = {k: v for k, v in x.items() if k not in LABEL_KEYS}
            return {k: walk(v) for k, v in x.items() if k != 'previous_label'}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return back(x) if isinstance(x, str) else x
    return walk(copy.deepcopy(body))
