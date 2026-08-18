"""
The one place that generates a public share token — same scheme
soa_lite_requests.token already used inline in public_lite.py's
submit_lite_request (uuid4 hex: 32 lowercase hex chars, 122 bits of
randomness, non-sequential, unguessable). Shareable Full Analysis links
(soa_cycle_shares.token) call this instead of a second implementation,
so "same length/entropy" holds by construction rather than by two call
sites happening to agree.
"""
import uuid


def generate_public_token() -> str:
    return uuid.uuid4().hex
