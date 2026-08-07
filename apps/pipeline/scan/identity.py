"""
identity.py — the Agent Scan's declared crawler identity (W1). Single
source for the bot name, User-Agent string, and key-directory URL —
fetcher.py, scorer.py, signing.py, and the /bots page (apps/api/web/src/
lite/BotsPage.jsx, which mirrors these values as static copy since the
web app can't import Python) all trace back to the three constants here.

Audit-rename note: the scanner's original bot name is retired in favor
of ParleoAuditBot as of this stage (grep-killed repo-wide — see
tests/scan/test_identity.py) — a bot's reputation with site operators
and CDNs (Cloudflare's bot categorization, robots.txt allow/deny lists
written by hand) is built against ONE stable name over time, so the
rename happens once, here, rather than drifting across call sites.
"""
import os

BOT_NAME = "ParleoAuditBot"

# W1: NOT plain declared-bot shape (no browser-engine tokens) — this is
# the literal string the "audit bot" identity was specified with. It
# still identifies honestly: the "compatible; ParleoAuditBot/1.0; +URL"
# suffix is the standard declared-crawler convention (the same shape
# Googlebot/Bingbot use for their own "compatible" tokens) — the
# AppleWebKit/Gecko tokens ahead of it are compatibility tokens some
# origins gate rendering behavior on, not an attempt to pass as an
# undeclared human browser; "compatible; ParleoAuditBot/1.0" is never
# hidden or omitted.
# The +URL suffix's documentation lives on the bots host, alongside the
# key directory (KEY_DIRECTORY_URL below) — one host for everything a
# verifier or site operator needs. This URL is registered with
# Cloudflare Verified Bots; changing it again after registration means
# re-registering, so treat it as stable.
BOT_UA = (
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); "
    "compatible; ParleoAuditBot/1.0; +https://bots.parleo.io"
)

# W2/W3: where verifiers (and the /bots page) find our published public
# key(s) — the Signature-Agent header on every signed request points
# here (signing.py), and scripts/generate_key_directory.py writes the
# JWKS-style document THIS url is meant to serve.
KEY_DIRECTORY_URL = "https://bots.parleo.io/.well-known/http-message-signatures-directory"


# ─── W5: UA policy knob ────────────────────────────────────────────────
#
# UA_POLICY_DECLARED_ALWAYS (default): every page-fetch request sends
# BOT_UA, full stop — the honest, self-identifying crawler this whole
# module exists to define. This is the ONLY mode the public SoA Lite
# intake ever uses.
#
# UA_POLICY_BROWSER_WHEN_AUTHORIZED: reserved for a FUTURE, explicitly
# opt-in product surface — a client auditing their OWN site who wants
# to see what their storefront looks like to an undeclared, browser-
# presenting agent (a real, disclosed testing need: some sites serve
# different content to declared crawlers than to anything else). This
# mode is written down here as a policy DECISION, not a working code
# path yet: resolve_user_agent() below only ever returns something
# other than BOT_UA when a caller passes client_authorized_for_browser_ua
# =True, and nothing in the pipeline (run_scan, worker.py's public
# intake) does that today — there is no per-run authorization field on
# soa_lite_requests, and adding one is a deliberate future change, not
# a side effect of defining this constant. Until that field exists,
# this mode is unreachable from any real request path, by construction.
UA_POLICY_DECLARED_ALWAYS = "declared_always"
UA_POLICY_BROWSER_WHEN_AUTHORIZED = "browser_when_client_authorized"
UA_POLICY = os.environ.get("UA_POLICY", UA_POLICY_DECLARED_ALWAYS)

# Only meaningful if/when UA_POLICY_BROWSER_WHEN_AUTHORIZED is actually
# wired to a real per-run authorization signal (see above) — a generic,
# current desktop Chrome UA, not a fabricated or spoofed fingerprint.
# Never sent unless a caller explicitly proves authorization.
BROWSER_TEST_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def resolve_user_agent(client_authorized_for_browser_ua: bool = False) -> str:
    """
    W5: the ONE place a fetch's User-Agent value is decided. Defaults to
    BOT_UA regardless of client_authorized_for_browser_ua unless
    UA_POLICY is explicitly set to UA_POLICY_BROWSER_WHEN_AUTHORIZED AND
    the caller passes True — the public intake path never does either,
    so it always resolves to BOT_UA.
    """
    if UA_POLICY == UA_POLICY_BROWSER_WHEN_AUTHORIZED and client_authorized_for_browser_ua:
        return BROWSER_TEST_UA
    return BOT_UA
