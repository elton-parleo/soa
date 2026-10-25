"""
2Q-1 (B1): builds tests/fixtures/retailer_coding/fl14_where_to_buy.json, the
FL14-shaped where-to-buy answers the retailer coding is tested on. No model
call, and nothing read from production.

    cd apps/pipeline && python3 tests/fixtures/build_where_to_buy_2q1.py

FL14-pampers-20261023 asked 10 where-to-buy questions of six agents: 60
answers. Its Retailer coverage read 49 of 60 on the model's coding (before
the 2O-4 rescore) and 36 of 60 on the rule selector's (after it), on the
same answers. These 60 are HAND-WRITTEN in the shapes the FL14 answers take,
in a mix chosen to give the printout's two figures; they are not FL14's
text, and the figure the test reports is this fixture's:

  prose   34  "You can buy Pampers Swaddlers Size 1 at Walmart, Target and
              Amazon." Two or more listed stores in a sentence with a buy
              word: the selector's store pass codes them, and so does 2Q-1's.
  list    15  a lead-in, then one store a line with a price after it
              ("**Target** - $28.49"), a bulk club in prose after the list.
              At most one line carries a buy word ("in stock"): the selector
              codes one store or none; 2Q-1 codes every one.
  gone     2  a listed store the answer says does not carry it ("Costco
              doesn't carry this size"): the selector codes it (its unit
              says "carry"), so it counts two; 2Q-1 codes it unavailable.
  one      5  one listed store, in prose.
  other    4  stores off the merchant's list only (Instacart, Kroger, CVS).

The merchant's retailer list is the fixture's: Walmart, Target, Amazon,
Costco, Sam's Club (supply's /retailers for Pampers is not in this repo).
Own site pampers.com, named in words in some answers ("the Pampers
website"), the 2N-1 brand row.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'retailer_coding', 'fl14_where_to_buy.json')

RETAILERS = ['walmart.com', 'target.com', 'amazon.com', 'costco.com', 'samsclub.com']
OWN = ['pampers.com']
AGENTS = ['chatgpt', 'gemini', 'perplexity', 'claude', 'google_ai_mode', 'copilot']
PRODUCTS = [('Swaddlers', 'Size 1', '96 ct', 27.97), ('Cruisers 360', 'Size 4', '104 ct', 44.99),
            ('Baby Dry', 'Size 3', '136 ct', 36.49), ('Pure Protection', 'Size 1', '82 ct', 29.97),
            ('Zzz Overnight', 'Size 4', '104 ct', 44.99), ('Swaddlers', 'Newborn', '84 ct', 26.97),
            ('Easy Ups', 'Size 5', '66 ct', 32.99), ('Cruisers', 'Size 6', '84 ct', 39.97),
            ('Swaddlers 360', 'Size 2', '84 ct', 29.49), ('Baby Dry', 'Size 7', '88 ct', 41.99)]

PROSE = [
    "You can buy Pampers {line} {size} at Walmart, Target and Amazon. Prices run about ${p:.2f} for the {count} box.",
    "Pampers {line} {size} is sold at Amazon and Walmart, and you can order it on the Pampers website too.",
    "Most shoppers buy Pampers {line} {size} at Target or Costco; Walmart carries it as well.",
    "You'll find Pampers {line} {size} available at Walmart, Amazon and Sam's Club, usually around ${p:.2f}.",
]
LIST = [
    "Here are the best places to buy Pampers {line} {size}:\n\n1. **Walmart**: ${p:.2f}, in stock\n"
    "2. **Target** - ${t:.2f}\n3. **Amazon** — ${a:.2f} with Subscribe & Save\n\n"
    "Costco also has a bulk box for ${c:.2f}.",
    "Pampers {line} {size} ({count}):\n- Amazon: ${a:.2f}\n- Target: ${t:.2f}\n- Walmart: ${p:.2f}",
    "Where to get Pampers {line} {size}\n\n| Store | Price |\n|---|---|\n| Walmart | ${p:.2f} |\n"
    "| Sam's Club | ${c:.2f} |\n| Amazon | ${a:.2f} |",
]
GONE = "Pampers {line} {size} is sold at Walmart for ${p:.2f}. Costco doesn't carry this size."
ONE = "Your best bet for Pampers {line} {size} is Walmart, where the {count} box runs ${p:.2f}."
OTHER = "For Pampers {line} {size}, Instacart delivers from Kroger, and CVS keeps the {count} box near the front."

SHAPES = ['prose'] * 34 + ['list'] * 15 + ['gone'] * 2 + ['one'] * 5 + ['other'] * 4


def answer(shape, i, line, size, count, p):
    t, a, c = p + 0.52, p - 0.98, p * 1.6
    fill = dict(line=line, size=size, count=count, p=p, t=t, a=a, c=c)
    if shape == 'prose':
        return PROSE[i % len(PROSE)].format(**fill)
    if shape == 'list':
        return LIST[i % len(LIST)].format(**fill)
    return {'gone': GONE, 'one': ONE, 'other': OTHER}[shape].format(**fill)


def build():
    # the shapes spread over the 60 (question, agent) pairs, every seventh, so no question is one shape
    order = [(q, a) for q in range(10) for a in range(6)]
    placed = [order[(k * 7) % 60] for k in range(60)]
    answers = []
    for k, ((q, a), shape) in enumerate(zip(placed, SHAPES)):
        line, size, count, p = PRODUCTS[q]
        answers.append({'run': f'run-{15200 + q * 6 + a}', 'query_code': f'PAM_{230 + q}', 'agent': AGENTS[a],
                        'question': f'Where can I buy Pampers {line} {size}?', 'shape': shape,
                        'answer': answer(shape, k, line, size, count, p)})
    answers.sort(key=lambda r: r['run'])
    return {'_note': 'Hand-written in FL14\'s shapes: see tests/fixtures/build_where_to_buy_2q1.py. Not FL14\'s text.',
            'cycle_code': 'FL14-pampers-20261023', 'brand': 'Pampers', 'retailers': RETAILERS, 'own_domains': OWN,
            'answers': answers}


if __name__ == '__main__':
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(build(), fh, indent=1, sort_keys=True)
        fh.write('\n')
    print(OUT)
