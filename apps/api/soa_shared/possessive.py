"""
A name's possessive, for copy built from a merchant's or a brand's name
("after Pampers' team sends the file"). One rule, used by every template that
writes "<name>'s": a name ending in s takes an apostrophe only ("Pampers'"),
any other takes 's ("P&G's", "Wiggle & Snug's"). Sync copies in apps/api,
apps/pipeline and packages/shared (tests/test_2l1_shared_copy.py).
"""


def possessive(name) -> str:
    """"Pampers" -> "Pampers'", "P&G" -> "P&G's"."""
    text = str(name or '').strip()
    return f"{text}'" if text.lower().endswith('s') else f"{text}'s"
