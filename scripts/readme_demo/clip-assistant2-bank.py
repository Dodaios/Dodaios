# ruff: noqa: S311 - made-up demo data, not cryptography
"""Writes a made-up bank export for the Assistant clip.

The file is Documents/bank-2026.csv in the demo instance's home folder.

    python scripts/readme_demo/clip-assistant2-bank.py <DEMO_HOME>

Run it after demo-instance.sh has started (each start wipes DEMO_HOME). The
numbers are made up and the same every time (a fixed seed).
"""

import csv
import datetime
import random
import sys
from pathlib import Path

home = Path(sys.argv[1])
random.seed(7)
shops = ["Greenleaf Market", "FreshCo", "Corner Shop", "Weekly market", "Organic store", "FreshCo"]
grocery_target = {1: 412, 2: 388, 3: 405, 4: 431, 5: 447, 6: 468, 7: 596, 8: 552, 9: 438, 10: 421}
rows = []
for m in range(1, 11):
    days = [
        datetime.date(2026, m, 1) + datetime.timedelta(days=i)
        for i in range(31)
        if (datetime.date(2026, m, 1) + datetime.timedelta(days=i)).month == m
    ]
    n = random.randint(9, 12)
    picks = sorted(random.sample(days, n))
    weights = [random.uniform(0.6, 1.4) for _ in picks]
    s = sum(weights)
    amounts = [round(grocery_target[m] * w / s, 2) for w in weights]
    amounts[-1] = round(grocery_target[m] + random.uniform(-9, 9) - sum(amounts[:-1]), 2)
    for d, a in zip(picks, amounts, strict=True):
        rows.append((d, random.choice(shops), "Groceries", -a))
    rows.append((datetime.date(2026, m, 1), "Rent", "Housing", -1180.00))
    rows.append(
        (datetime.date(2026, m, 3), "Electricity", "Utilities", -round(random.uniform(58, 74), 2))
    )
    rows.append((datetime.date(2026, m, 5), "Mobile plan", "Utilities", -19.99))
    rows.append((datetime.date(2026, m, 27), "Salary", "Income", 3840.00))
    for _ in range(random.randint(3, 6)):
        d = random.choice(days)
        rows.append(
            (
                d,
                random.choice(["Cafe Kranich", "Pizzeria Roma", "Thai Garden", "Burger Werk"]),
                "Eating out",
                -round(random.uniform(9, 46), 2),
            )
        )
    for _ in range(random.randint(1, 3)):
        d = random.choice(days)
        rows.append(
            (
                d,
                random.choice(["Transit pass", "Bike repair", "Train ticket"]),
                "Transport",
                -round(random.uniform(12, 64), 2),
            )
        )
rows.sort(key=lambda r: r[0])
out = home / "Documents" / "bank-2026.csv"
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Date", "Description", "Category", "Amount (EUR)"])
    for d, desc, cat, a in rows:
        w.writerow([d.isoformat(), desc, cat, f"{a:.2f}"])
print(out, len(rows))
