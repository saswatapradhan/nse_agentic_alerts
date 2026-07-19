from false_positive_filters import apply_filters

tests = [
    ("Closure of Trading Window", "trading window closed till", "RELIANCE", set()),
    ("Board Meeting Intimation", "board meeting scheduled to consider Q1 results", "TCS", set()),
    ("Acquisition of XYZ Ltd", "company acquires XYZ for Rs. 500 Cr", "INFY", set()),
    ("Resignation of Statutory Auditor", "auditor has resigned citing concerns", "ADANIENT", set()),
    ("Disclosure under Reg 29", "promoter acquired shares worth Rs. 2 Cr", "WIPRO", set()),
    ("Disclosure under Reg 29", "promoter acquired shares worth Rs. 15 Cr", "WIPRO", set()),
    ("Financial Results", "board approved unaudited results for quarter", "HDFC", set()),
]

for subject, body, symbol, wl in tests:
    result = apply_filters(subject, body, symbol, wl)
    print(f"{symbol:12} | skip={str(result.skip):5} | {result.reason}")