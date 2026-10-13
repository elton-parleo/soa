"""
Per-surface accuracy for one cycle, split by surface and never pooled (2B §4).

    python3 scripts/surface_accuracy.py --cycle <code>

Prints, for api / grounded_api / consumer_ui in turn, each platform's
accuracy (exact / scored), its partial and stale rates, its unverifiable
count and its coverage (results, walls, failures). There is no total
across surfaces, on purpose: see soa_shared/surface_accuracy.py.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from soa_shared import surface_accuracy  # noqa: E402
from soa_shared.database import engine  # noqa: E402
from scripts.rescore_cycle import cycle_id  # noqa: E402


def _pct(value):
    return '—' if value is None else f"{value * 100:.1f}%"


def render(entries) -> str:
    lines = []
    for entry in entries:
        cov = entry['coverage']
        lines.append(f"{entry['surface']} ({entry['label']}): accuracy {_pct(entry['accuracy'])} "
                     f"over {entry['scored']} scored; partial {_pct(entry['partial_rate'])}; "
                     f"unverifiable {entry['unverifiable']}; results {cov['results']}/{cov['runs']} "
                     f"(no AI answer {cov['no_ai_answer']}, sign-in wall {cov['sign_in_wall']}, "
                     f"blocked {cov['blocked']}, failed {cov['failed']})")
        for p in entry['platforms']:
            lines.append(f"    {p['platform']:<16} [{p['collector']}] accuracy {_pct(p['accuracy'])} "
                         f"over {p['scored']}; counts {p['counts']}")
    return '\n'.join(lines) or '(nothing scored)'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--cycle', required=True)
    args = parser.parse_args(argv)
    with engine.connect() as conn:
        entries = surface_accuracy.for_cycle(conn, cycle_id(conn, args.cycle))
    print(render(entries))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
