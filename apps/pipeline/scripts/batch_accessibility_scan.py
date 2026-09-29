"""
Run the Agent Scan over a list of store URLs and write the Accessibility
pillar for each one to a CSV.

There was no entry point for this. run_scan() (scan/engine.py) is only
ever called by the worker, one lite request or cycle crawl at a time,
and both of those paths also create cycles, run the Visibility study and
send emails. This script calls run_scan() directly and nothing else — no
database, no LLM study, no rows written anywhere.

    python3 scripts/batch_accessibility_scan.py urls.csv --out results.csv
    python3 scripts/batch_accessibility_scan.py urls.csv --out -          # CSV to stdout
    railway run python3 scripts/batch_accessibility_scan.py urls.csv --out results.csv

The input is either a CSV with a `url` column (and optionally `name`), or
a plain list with one URL or domain per line. Blank lines and lines
starting with # are skipped. Two inputs that resolve to the same host are
scanned once: the fetcher's politeness state is per host, and two threads
crawling one store at once would defeat it.

The Accessibility pillar is agent_access + catalog_context +
protocol_feed. Its score is computed here the same way apps/api/app/
services/lite_pillars.py::build_pillars_payload computes it — earned over
applicable max, with 'na' and 'blocked' dimensions excluded from both —
kept in sync by hand, same convention as that module's own copies of
pipeline registries. accessibility_state says how much of the pillar that
number actually covers:

  full        all three dimensions were measured (or one was 'na')
  partial     at least one was 'blocked' — the score covers only the rest.
              The report withholds the composite in this case; read the
              number as a lower-confidence one, not a comparable one.
  unmeasured  nothing applicable was measured; the score is left blank.

Each row is written and flushed as soon as its scan finishes, so a batch
that is interrupted keeps everything it already finished. Progress goes
to stderr, so `--out -` leaves stdout as clean CSV (e.g. in Railway logs).

Environment is read exactly as the worker reads it: BOT_SIGNING_KEY
(unset means unsigned fetches), UA_POLICY, and OPEN_AI_API_KEY plus
LLM_DISCOVERY_FALLBACK for the last-resort discovery tier.
"""
import argparse
import csv
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scan import signing  # noqa: E402
from scan.engine import run_scan  # noqa: E402

log = logging.getLogger("batch_accessibility_scan")

ACCESSIBILITY_CODES = ("agent_access", "catalog_context", "protocol_feed")

FIELDS = [
    "name", "input_url", "host", "status", "degraded_reason", "error",
    "accessibility_score", "accessibility_state",
    *[f"{code}_{part}" for code in ACCESSIBILITY_CODES for part in ("score", "max", "coverage")],
    "site_type", "product_pages_fetched", "robots_ok",
    "agents_blocked", "agents_partial", "edge_vendor", "discovery_path",
    "cross_domain_redirect", "signing_enabled", "top_fix",
    "agent_access_evidence", "catalog_context_evidence", "protocol_feed_evidence",
    "started_at", "finished_at", "duration_s",
]


def read_targets(path: str) -> list:
    """[(name, url)] in file order. Accepts a CSV with a url column or a
    bare one-per-line list."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        lines = [line for line in f if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return []
    header = [h.strip().lower() for h in next(csv.reader([lines[0]]))]
    if "url" in header:
        rows = csv.DictReader(lines[1:], fieldnames=header)
        return [((r.get("name") or "").strip(), (r.get("url") or "").strip()) for r in rows if (r.get("url") or "").strip()]
    return [("", next(csv.reader([line]))[0].strip()) for line in lines]


def host_of(url: str) -> str:
    value = url if "://" in url else f"https://{url}"
    host = (urlparse(value).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def dedupe_by_host(targets: list) -> list:
    seen, kept = set(), []
    for name, url in targets:
        host = host_of(url)
        if host in seen:
            log.warning(f"skipping duplicate host {host!r} ({url})")
            continue
        seen.add(host)
        kept.append((name, url))
    return kept


def accessibility_pillar(dimensions: dict) -> tuple:
    """(score or None, state) — see the module docstring."""
    earned = applicable_max = 0.0
    any_blocked = False
    for code in ACCESSIBILITY_CODES:
        d = dimensions.get(code) or {}
        coverage = d.get("coverage") or "full"
        if coverage == "blocked":
            any_blocked = True
            continue
        if coverage == "na":
            continue
        earned += d.get("score") or 0.0
        applicable_max += d.get("max") or 0.0
    if not applicable_max:
        return None, "unmeasured"
    return round(earned / applicable_max * 100), "partial" if any_blocked else "full"


def top_fix(dimensions: dict):
    """fix_human of the measured accessibility dimension with the biggest
    gap — the same opportunity-size ranking the report's fixes list uses."""
    gaps = []
    for code in ACCESSIBILITY_CODES:
        d = dimensions.get(code) or {}
        if d.get("coverage") in ("na", "blocked") or not d.get("fix_human"):
            continue
        gaps.append(((d.get("max") or 0) - (d.get("score") or 0), code, d["fix_human"]))
    if not gaps:
        return None
    return max(gaps, key=lambda g: (g[0], g[1]))[2]


def agents_in_state(matrix: list, state: str) -> str:
    return "; ".join(
        a["agent"] for a in matrix or []
        if a.get("root") == state or a.get("product_pages") == state
    )


def to_row(name: str, url: str, result, duration_s: float) -> dict:
    dims = result.dimensions or {}
    score, state = accessibility_pillar(dims)
    trace = dims.get("discovery_trace") or {}
    block = dims.get("block_evidence") or {}
    row = {
        "name": name, "input_url": url, "host": host_of(url),
        "status": result.status, "degraded_reason": dims.get("degraded_reason"),
        "error": result.error,
        "accessibility_score": score, "accessibility_state": state,
        "site_type": dims.get("site_type"),
        "product_pages_fetched": trace.get("product_pages_fetched"),
        "robots_ok": trace.get("robots_ok"),
        "agents_blocked": agents_in_state(dims.get("agent_access_matrix"), "blocked"),
        "agents_partial": agents_in_state(dims.get("agent_access_matrix"), "partial"),
        "edge_vendor": block.get("dominant_vendor") or block.get("dns_vendor_hint"),
        "discovery_path": dims.get("discovery_path"),
        "cross_domain_redirect": result.cross_domain_redirect,
        "signing_enabled": dims.get("signing_enabled"),
        "top_fix": top_fix(dims),
        "started_at": result.started_at, "finished_at": result.finished_at,
        "duration_s": round(duration_s, 1),
    }
    for code in ACCESSIBILITY_CODES:
        d = dims.get(code) or {}
        row[f"{code}_score"] = d.get("score")
        row[f"{code}_max"] = d.get("max")
        row[f"{code}_coverage"] = d.get("coverage")
        row[f"{code}_evidence"] = " | ".join(d.get("evidence") or [])
    return row


def scan_one(name: str, url: str, api_key) -> dict:
    started = time.monotonic()
    result = run_scan(url, api_key=api_key)  # never raises (scan/engine.py)
    return to_row(name, url, result, time.monotonic() - started)


def main() -> int:
    parser = argparse.ArgumentParser(description="Accessibility-pillar scan over a list of store URLs.")
    parser.add_argument("input", help="CSV with a url column (optional name), or one URL per line")
    parser.add_argument("--out", required=True, help="output CSV path, or - for stdout")
    parser.add_argument("--workers", type=int, default=4, help="stores scanned in parallel (default 4)")
    parser.add_argument("--limit", type=int, help="scan only the first N stores")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    # The scan package logs every fetch at INFO; keep this script's
    # progress lines readable.
    logging.getLogger("scan").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    targets = dedupe_by_host(read_targets(args.input))
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        raise SystemExit(f"no URLs found in {args.input}")

    if not signing.is_signing_enabled():
        log.warning("BOT_SIGNING_KEY is not set — fetches go out unsigned; results may differ from production scans")
    api_key = os.environ.get("OPEN_AI_API_KEY")

    out = sys.stdout if args.out == "-" else open(args.out, "w", newline="", encoding="utf-8")
    try:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        out.flush()
        log.info(f"scanning {len(targets)} stores with {args.workers} workers")
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(scan_one, name, url, api_key): url for name, url in targets}
            for done, future in enumerate(as_completed(futures), 1):
                url = futures[future]
                try:
                    row = future.result()
                except Exception as e:
                    # run_scan never raises; this is the row-building
                    # code around it. One bad row must not end the batch.
                    log.exception(f"{url}: failed outside run_scan")
                    row = {"input_url": url, "host": host_of(url), "status": "failed", "error": f"{type(e).__name__}: {e}"}
                writer.writerow(row)
                out.flush()
                log.info(
                    f"[{done}/{len(targets)}] {url}: {row.get('status')} "
                    f"accessibility={row.get('accessibility_score')} ({row.get('accessibility_state')})"
                )
    finally:
        if out is not sys.stdout:
            out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
