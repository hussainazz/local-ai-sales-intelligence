"""Small, measured models. No fabricated labels or random time splits."""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    silhouette_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .analytics import filtered, records, rfm
from .ingestion import atomic_json
from .preparation import load_clean
from .schemas import Filters, Forecast, Supervised


def forecast(store, dataset_id, request: Forecast, filters=None):
    frame, data = load_clean(store, dataset_id)
    frame = filtered(frame, filters or Filters())
    if frame[["transaction_date", "_net_sales"]].isna().any().any():
        raise ValueError("Forecasting requires complete dates and net sales in the selected data.")
    daily = frame.groupby(frame.transaction_date.dt.normalize())._net_sales.sum().sort_index()
    full = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    if len(full) != len(daily):
        if request.missing_days == "error":
            raise ValueError(
                "Dates are missing. Confirm zero sales for missing days or provide complete history."
            )
        daily = daily.reindex(full, fill_value=0)
    if len(daily) < 90:
        raise ValueError("Daily forecasting needs at least 90 observed or explicitly zero-filled days.")
    table = pd.DataFrame({"y": daily})
    for lag in [1, 7, 14, 28]:
        table[f"lag_{lag}"] = daily.shift(lag)
    table["mean_7"] = daily.shift(1).rolling(7).mean()
    table["weekday"] = daily.index.day_of_week
    table = table.dropna()
    x, y = table.drop(columns="y"), table.y
    errors, baseline_errors, folds = [], [], []
    # Evaluate recursively for the requested horizon, not with future actual lag values.
    test_size = min(request.horizon, max(1, (len(table) - 25) // 3))
    split = TimeSeriesSplit(n_splits=3, test_size=test_size)

    def rollout(model, history, horizon, baseline=False):
        history = list(history)
        predicted = []
        last_date = daily.index[0] + pd.Timedelta(days=len(history) - 1)
        for step in range(horizon):
            row = {f"lag_{lag}": history[-lag] for lag in [1, 7, 14, 28]}
            row["mean_7"] = float(np.mean(history[-7:]))
            row["weekday"] = (last_date + pd.Timedelta(days=step + 1)).day_of_week
            value = (
                history[-7] if baseline else float(model.predict(pd.DataFrame([row], columns=x.columns))[0])
            )
            predicted.append(value)
            history.append(value)
        return np.array(predicted)

    for train_index, test_index in split.split(x):
        model = RandomForestRegressor(n_estimators=60, max_depth=5, random_state=42, n_jobs=1)
        model.fit(x.iloc[train_index], y.iloc[train_index])
        start = daily.index.get_loc(table.index[test_index[0]])
        predicted = rollout(model, daily.iloc[:start], len(test_index))
        baseline = rollout(model, daily.iloc[:start], len(test_index), baseline=True)
        actual = y.iloc[test_index].to_numpy()
        errors.extend((actual - predicted).tolist())
        baseline_errors.extend((actual - baseline).tolist())
        folds.append(
            {
                "train_end": str(table.index[train_index[-1]].date()),
                "test_start": str(table.index[test_index[0]].date()),
                "horizon": len(test_index),
                "model_mae": float(mean_absolute_error(actual, predicted)),
                "baseline_mae": float(mean_absolute_error(actual, baseline)),
            }
        )
    model.fit(x, y)
    model_mae = float(np.mean(np.abs(errors)))
    baseline_mae = float(np.mean(np.abs(baseline_errors)))
    use_baseline = baseline_mae <= model_mae
    predictions = rollout(model, daily, request.horizon, baseline=use_baseline)
    residuals = baseline_errors if use_baseline else errors
    radius = float(np.quantile(np.abs(residuals), 0.8))
    dates = pd.date_range(daily.index.max() + pd.Timedelta(days=1), periods=request.horizon)
    result = {
        "dataset_id": dataset_id,
        "dataset_version": data["version"],
        "currency": data["meta"]["mapping"]["currency"],
        "model": "seasonal_naive_7" if use_baseline else "random_forest_lags",
        "model_mae": model_mae,
        "baseline_mae": baseline_mae,
        "folds": folds,
        "forecast": [
            {
                "date": day.date().isoformat(),
                "prediction": float(value),
                "lower": float(value - radius),
                "upper": float(value + radius),
            }
            for day, value in zip(dates, predictions)
        ],
        "interval_note": "Exploratory band using pooled 80th-percentile absolute backtest errors. Not calibrated by horizon and not a coverage guarantee.",
        "validation": "Expanding-window recursive time-series backtests; features use only past values.",
        "missing_days_policy": request.missing_days,
    }
    atomic_json(
        store.cache_path(
            dataset_id,
            "forecast",
            {**request.model_dump(), "filters": (filters or Filters()).model_dump()},
            version=data["version"],
        ),
        result,
    )
    return result


def supervised(store, dataset_id, request: Supervised):
    if not request.leakage_reviewed:
        raise ValueError(
            "A person must review feature availability at prediction time and the target definition."
        )
    frame, data = load_clean(store, dataset_id)
    forbidden = {"_row_id", "order_id", "customer_id", "product_id", "transaction_date", request.target}
    if set(request.features) & forbidden or len(set(request.features)) != len(request.features):
        raise ValueError("Features cannot contain identifiers, time, duplicate columns or the target.")
    if {request.target, *request.features} - set(frame.columns):
        raise ValueError("The target or requested features do not exist.")
    frame = frame.dropna(subset=[request.target, "transaction_date"]).sort_values("transaction_date")
    if len(frame) < 100:
        raise ValueError("At least 100 labeled, dated rows are required.")
    x = frame[request.features].apply(pd.to_numeric, errors="coerce")
    y = frame[request.target]
    cutoff = frame.transaction_date.quantile(0.8)
    train = frame.transaction_date < cutoff
    test = ~train
    if train.sum() < 50 or test.sum() < 20:
        raise ValueError("Insufficient distinct dates for a chronological holdout.")
    if x.loc[train].isna().all().any():
        raise ValueError("A feature is entirely missing or nonnumeric in the training period.")
    if request.task == "classification":
        y = y.astype(str)
        counts = y.loc[train].value_counts()
        if len(counts) < 2 or counts.min() < 10 or not set(y.loc[test]) <= set(counts.index):
            raise ValueError(
                "Need at least two training classes with 10 examples each and no unseen test labels."
            )
        model = make_pipeline(
            SimpleImputer(), StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000)
        )
        baseline = DummyClassifier(strategy="most_frequent")
    else:
        y = pd.to_numeric(y, errors="raise")
        if y.nunique() < 2:
            raise ValueError("A regression target must vary.")
        model = make_pipeline(SimpleImputer(), StandardScaler(), Ridge())
        baseline = DummyRegressor(strategy="mean")
    model.fit(x.loc[train], y.loc[train])
    baseline.fit(x.loc[train].fillna(0), y.loc[train])
    predicted = model.predict(x.loc[test])
    basic = baseline.predict(x.loc[test].fillna(0))
    if request.task == "classification":
        metrics = {
            "precision_macro": float(
                precision_score(y.loc[test], predicted, average="macro", zero_division=0)
            ),
            "recall_macro": float(recall_score(y.loc[test], predicted, average="macro", zero_division=0)),
            "f1_macro": float(f1_score(y.loc[test], predicted, average="macro", zero_division=0)),
            "baseline_f1_macro": float(f1_score(y.loc[test], basic, average="macro", zero_division=0)),
            "labels": model.classes_.tolist(),
            "confusion_matrix": confusion_matrix(y.loc[test], predicted, labels=model.classes_).tolist(),
        }
        if len(model.classes_) == 2 and y.loc[test].nunique() == 2:
            metrics["roc_auc"] = float(
                roc_auc_score(y.loc[test] == model.classes_[1], model.predict_proba(x.loc[test])[:, 1])
            )
    else:
        metrics = {
            "mae": float(mean_absolute_error(y.loc[test], predicted)),
            "rmse": float(np.sqrt(mean_squared_error(y.loc[test], predicted))),
            "r2": float(r2_score(y.loc[test], predicted)),
            "baseline_mae": float(mean_absolute_error(y.loc[test], basic)),
        }
    result = {
        "dataset_version": data["version"],
        "configuration": request.model_dump(),
        "metrics": metrics,
        "train_rows": int(train.sum()),
        "test_rows": int(test.sum()),
        "holdout_start": str(cutoff),
        "limitations": [
            "Chronological holdout only; business-level label and feature leakage still requires human review.",
            "Models are evaluated per request and not promoted to production automatically.",
        ],
    }
    atomic_json(
        store.cache_path(dataset_id, "supervised", request.model_dump(), version=data["version"]), result
    )
    return result


def cluster(store, dataset_id):
    frame, data = load_clean(store, dataset_id)
    result = rfm(frame)
    table = pd.DataFrame(result["customers"])
    features = table[["recency_days", "frequency", "monetary"]]
    if len(table) < 20 or len(features.drop_duplicates()) < 3:
        raise ValueError("Clustering needs at least 20 customers and three distinct RFM profiles.")
    scaled = StandardScaler().fit_transform(features)
    candidates = []
    for count in range(2, min(6, len(features.drop_duplicates()) - 1) + 1):
        model = KMeans(n_clusters=count, n_init=10, random_state=42)
        labels = model.fit_predict(scaled)
        score = float(silhouette_score(scaled, labels, sample_size=min(2000, len(table)), random_state=42))
        candidates.append((score, count, labels))
    score, count, labels = max(candidates, key=lambda item: item[0])
    table["cluster"] = labels
    return {
        "dataset_version": data["version"],
        "clusters": count,
        "silhouette": score,
        "customers": records(table),
        "profiles": records(table.groupby("cluster")[features.columns].mean().reset_index()),
        "interpretation": "Cluster numbers are arbitrary. Profiles describe observed RFM averages, not verified customer personas.",
    }
