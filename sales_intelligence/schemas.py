from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


CANONICAL = {
    "customer_id",
    "customer_name",
    "product_id",
    "product_name",
    "order_id",
    "transaction_date",
    "sales_quantity",
    "sales_amount",
    "purchase_amount",
    "cost",
    "discount",
    "unit_price",
    "category",
    "region",
    "text",
    "currency",
}


class Mapping(StrictModel):
    sheet: str = Field(max_length=100)
    columns: dict[str, str]
    grain: Literal["order", "line_item"]
    currency: str = Field(min_length=1, max_length=20)
    sales_definition: str = Field(min_length=15, max_length=1000)
    sales_basis: Literal["net_after_discount", "gross_before_discount"] = "net_after_discount"
    cost_basis: Literal["unavailable", "line_total", "per_unit"] = "unavailable"
    date_calendar: Literal["gregorian", "jalali"] = "gregorian"
    date_format: str = "%Y-%m-%d"
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_columns(self):
        if not self.confirmed:
            raise ValueError("A person must confirm column meanings and business definitions.")
        if set(self.columns) - CANONICAL:
            raise ValueError("Unknown canonical field.")
        if len(set(self.columns.values())) != len(self.columns):
            raise ValueError("One source column cannot represent two different fields.")
        if not {"transaction_date", "sales_amount"} <= self.columns.keys():
            raise ValueError("Map transaction_date and sales_amount.")
        if self.sales_basis == "gross_before_discount" and "discount" not in self.columns:
            raise ValueError("Gross sales require a mapped monetary discount column.")
        if self.cost_basis != "unavailable" and "cost" not in self.columns:
            raise ValueError("Map cost before enabling profitability.")
        if self.cost_basis == "per_unit" and "sales_quantity" not in self.columns:
            raise ValueError("Per-unit costs require quantity.")
        return self


class Relationship(StrictModel):
    sheet: str
    left_on: str
    right_on: str
    columns: list[str] = Field(min_length=1, max_length=30)
    cardinality: Literal["many_to_one", "one_to_one"] = "many_to_one"
    allow_unmatched: bool = False
    confirmed: bool = False


class Cleaning(StrictModel):
    numeric_nulls: Literal["preserve", "zero", "error"] = "preserve"
    invalid_values: Literal["error", "preserve_as_null"] = "error"
    duplicates: Literal["keep", "drop_exact"] = "keep"
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal[",", ".", "", "٬"] = ","
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_policy(self):
        if not self.confirmed:
            raise ValueError("Confirm the cleaning policy before any values change.")
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("Decimal and thousands separators must differ.")
        return self


class Filters(StrictModel):
    start: str | None = None
    end: str | None = None
    customer_id: str | None = Field(None, max_length=200)
    product_id: str | None = Field(None, max_length=200)
    limit: int = Field(20, ge=1, le=100)


class Chat(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    filters: Filters = Field(default_factory=Filters)
    use_llm: bool = False


class Forecast(StrictModel):
    horizon: int = Field(7, ge=1, le=30)
    missing_days: Literal["error", "zero_confirmed"] = "error"


class TextClassifier(StrictModel):
    purpose: Literal["sentiment", "complaint_classification"]
    label_column: str
    label_definition: str = Field(min_length=20, max_length=1000)
    permitted_labels: list[str] = Field(min_length=2, max_length=30)
    labeling_reviewed: bool = False


class Supervised(StrictModel):
    task: Literal["classification", "regression"]
    target: str
    features: list[str] = Field(min_length=1, max_length=30)
    target_definition: str = Field(min_length=20, max_length=1000)
    prediction_horizon: str = Field(min_length=3, max_length=200)
    leakage_reviewed: bool = False


class Simulation(StrictModel):
    price_change: float = Field(0, ge=-0.9, le=2)
    volume_change: float = Field(0, ge=-1, le=2)
    discount_change_points: float = Field(0, ge=-1, le=1)
    current_discount_rate: float = Field(0, ge=0, lt=1)
    assumptions_confirmed: bool = False


class Route(StrictModel):
    tool: Literal[
        "summary", "products", "customers", "trend", "rfm", "retention", "basket", "forecast", "unsupported"
    ]


class AdviceItem(StrictModel):
    action: Literal[
        "review_product_mix", "investigate_trend", "review_customer_followup", "verify_data_quality"
    ]
    evidence_ids: list[str] = Field(min_length=1, max_length=5)


class Advice(StrictModel):
    items: list[AdviceItem] = Field(default_factory=list, max_length=5)
