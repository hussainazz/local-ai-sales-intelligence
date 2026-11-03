import re

from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.pipeline import make_pipeline

from .preparation import load_clean
from .schemas import TextClassifier


def text_analysis(store, dataset_id):
    frame, data = load_clean(store, dataset_id)
    if "text" not in frame or frame.text.dropna().empty:
        return {"status": "skipped", "reason": "No nonempty mapped text column exists."}
    texts = frame.text.dropna().astype(str).map(lambda value: value[:4000]).tolist()
    texts = [re.sub(r"\s+", " ", text.replace("ي", "ی").replace("ك", "ک")) for text in texts]
    try:
        vectorizer = TfidfVectorizer(
            max_features=2000,
            max_df=1.0,
            min_df=1,
            stop_words=["the", "and", "is", "of", "to", "از", "به", "در", "و", "این", "که", "را"],
        )
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        return {"status": "skipped", "reason": "No usable text tokens remain."}
    terms = vectorizer.get_feature_names_out()
    weights = matrix.mean(axis=0).A1
    keywords = [
        {"term": terms[index], "weight": float(weights[index])} for index in weights.argsort()[-20:][::-1]
    ]
    topics = []
    if len(texts) >= 20 and matrix.shape[1] >= 10:
        model = NMF(n_components=min(4, matrix.shape[1] - 1), init="nndsvda", random_state=42, max_iter=300)
        model.fit(matrix)
        topics = [
            [terms[index] for index in component.argsort()[-8:][::-1]] for component in model.components_
        ]
    return {
        "dataset_version": data["version"],
        "status": "completed",
        "documents": len(texts),
        "keywords": keywords,
        "topics": topics,
        "sentiment": {
            "status": "not_estimated",
            "reason": "No evaluated Persian/domain-specific sentiment classifier has been supplied.",
        },
        "complaint_classification": {
            "status": "not_estimated",
            "reason": "Requires a defined complaint taxonomy and labeled evaluation set.",
        },
        "limitation": "TF-IDF keywords and NMF topics are exploratory. No sentiment or complaint labels are fabricated.",
    }


def evaluate_text_classifier(store, dataset_id, request: TextClassifier):
    """Train sentiment/complaint classification only from reviewed, existing labels."""
    if not request.labeling_reviewed:
        raise ValueError("A person must review the label taxonomy and its quality.")
    frame, data = load_clean(store, dataset_id)
    if "text" not in frame or request.label_column not in frame:
        raise ValueError("Map text and supply an existing sentiment/complaint label column.")
    labeled = frame.dropna(subset=["text", request.label_column, "transaction_date"]).copy()
    labeled["text"] = labeled.text.astype(str).str.strip()
    labeled[request.label_column] = labeled[request.label_column].astype(str)
    if len(set(request.permitted_labels)) != len(request.permitted_labels):
        raise ValueError("Label names must be unique.")
    if not set(labeled[request.label_column]) <= set(request.permitted_labels):
        raise ValueError("A label is outside the confirmed taxonomy.")
    conflicts = labeled.groupby("text")[request.label_column].nunique()
    if (conflicts > 1).any():
        raise ValueError("Identical text has conflicting labels. Review the labels first.")
    # De-duplicate the evaluation view only; the cleaned dataset is not changed.
    labeled = labeled.sort_values("transaction_date").drop_duplicates(subset=["text"], keep="first")
    if len(labeled) < 100:
        raise ValueError("Need at least 100 distinct, labeled texts with dates for evaluation.")
    cutoff = labeled.transaction_date.quantile(0.8)
    train = labeled.transaction_date < cutoff
    test = ~train
    if train.sum() < 50 or test.sum() < 20:
        raise ValueError("Too few distinct dates for text-classifier evaluation.")
    y = labeled[request.label_column]
    counts = y.loc[train].value_counts()
    if counts.min() < 10 or len(counts) < 2 or not set(y.loc[test]) <= set(counts.index):
        raise ValueError("Need two training labels with 10 examples each and no unseen holdout labels.")
    pipeline = make_pipeline(
        TfidfVectorizer(max_features=20000, ngram_range=(1, 2), sublinear_tf=True),
        LogisticRegression(class_weight="balanced", max_iter=1000),
    )
    pipeline.fit(labeled.loc[train, "text"], y.loc[train])
    predicted = pipeline.predict(labeled.loc[test, "text"])
    baseline = [counts.idxmax()] * int(test.sum())
    labels = sorted(counts.index)
    return {
        "purpose": request.purpose,
        "dataset_version": data["version"],
        "label_definition": request.label_definition,
        "train_rows": int(train.sum()),
        "test_rows": int(test.sum()),
        "evaluation_deduplicated_texts": True,
        "holdout_start": str(cutoff),
        "labels": labels,
        "f1_macro": float(f1_score(y.loc[test], predicted, average="macro", zero_division=0)),
        "baseline_f1_macro": float(f1_score(y.loc[test], baseline, average="macro", zero_division=0)),
        "precision_macro": float(precision_score(y.loc[test], predicted, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y.loc[test], predicted, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y.loc[test], predicted, labels=labels).tolist(),
        "limitation": "Evaluation only. Requires domain/language review before deployment; labels are never generated by this code.",
    }
