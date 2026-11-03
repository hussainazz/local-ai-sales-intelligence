"""Reproducible fictional transactions, never real customer records."""

from pathlib import Path

import numpy as np
import pandas as pd


def create_sample(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    rows = []
    products = ["P01", "P02", "P03", "P04", "P05"]
    prices = {"P01": 120, "P02": 75, "P03": 95, "P04": 180, "P05": 55}
    number = 0
    for date in pd.date_range("2025-01-01", periods=180):
        for _ in range(int(rng.integers(3, 7))):
            number += 1
            customer = f"C{int(rng.integers(1, 61)):03d}"
            selected = rng.choice(products, size=int(rng.integers(1, 4)), replace=False)
            for product in selected:
                quantity = int(rng.integers(1, 5))
                rows.append(
                    {
                        "order_id": f"O{number:05d}",
                        "customer_id": customer,
                        "product_id": str(product),
                        "transaction_date": date.date().isoformat(),
                        "sales_quantity": quantity,
                        "sales_amount": quantity * prices[product],
                        "cost": quantity * prices[product] * 0.6,
                        "discount": 0,
                        "feedback": rng.choice(["کیفیت خوب بود", "تحویل دیر رسید", "بسته‌بندی مناسب بود"]),
                        "risk_label": int(customer in {"C001", "C002", "C003", "C004", "C005"}),
                    }
                )
    sales = pd.DataFrame(rows)
    dimensions = pd.DataFrame({"product_key": products, "category_name": ["A", "A", "B", "B", "C"]})
    sales.to_csv(directory / "sales.csv", index=False)
    with pd.ExcelWriter(directory / "sales.xlsx", engine="openpyxl") as writer:
        sales.to_excel(writer, sheet_name="Sales", index=False)
        dimensions.to_excel(writer, sheet_name="Products", index=False)
    (directory / "company_policy.txt").write_text(
        "FICTIONAL DEMONSTRATION POLICY. Review customer consent before promotional follow-up. "
        "Product bundles require a stock check and manager approval. This is not an actual company policy.",
        encoding="utf-8",
    )
    return sales


if __name__ == "__main__":
    frame = create_sample(Path(__file__).resolve().parents[1] / "sample_data")
    print(
        f"Created {len(frame)} fictional line items. risk_label is synthetic for tests only, not a churn target."
    )
