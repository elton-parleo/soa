"""
2V-3 Q2-Q4: what Petco's first cycle (FL17-petco-20261029) showed in the lines.

Q2  A line may not give the record or a page a size, count, price or program
    the record does not hold. FL17's four lines gave Petco's record the 40 lb
    an agent said (the record is 31.1 lb) and the 6 lb an agent said (Tidy
    Cats, no 6 lb in the record). The brief quoted the first with an ellipsis;
    the fixture fills it with the product's name. Each line passed the check
    before 2V-3 (asserted against the facts below) and drops now.
Q3  A read's date is its day in the workspace's timezone: an Oct 29 PDT read
    is "Oct 29", never the UTC "Oct 30".
Q4  A product row with no variant label is named by its question, never its
    key; a literal "<brand>", an empty name or a subject key is never written;
    "... but Petco is the store" reads "... but the record is Petco's".
No model is called: check() and the facts builders are pure.
"""
import pytest

from soa_shared import local_time
from soa_shared import narratives as n

# ── Q3 ─────────────────────────────────────────────────────────────────────

def test_a_read_date_is_the_workspace_s_day():
    stamp = '2026-10-30T02:15:00+00:00'      # Oct 29, 19:15 PDT
    assert n._day(stamp, 'America/Los_Angeles') == 'Oct 29'
    assert n._day(stamp, 'UTC') == 'Oct 30'
    assert n._day('2026-10-29') == 'Oct 29'  # a bare date reads as it is
    row = {'retailer_domain': 'petco.com', 'price': '28.99', 'observed_at': stamp}
    assert n._reference_fact(row, zone='America/Los_Angeles')['date'] == 'Oct 29'


def test_the_console_and_the_lines_share_one_day_rule():
    from app.services import console_days
    console_days.use_zone('America/Los_Angeles')
    stamp = '2026-10-30T02:15:00+00:00'
    assert console_days.short_day(stamp) == local_time.short_day(stamp, 'America/Los_Angeles') == 'Oct 29'
