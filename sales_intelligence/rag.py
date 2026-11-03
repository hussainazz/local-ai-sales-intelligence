import hashlib
import io
import json
from pathlib import Path

import faiss
import numpy as np
from docx import Document
from pypdf import PdfReader

from .ingestion import atomic_json, check_archive


def extract_text(filename, body):
    extension = Path(filename.replace("\\", "/")).suffix.lower()
    if not body or len(body) > 10 * 1024 * 1024:
        raise ValueError("Documents must be nonempty and at most 10 MB.")
    if extension in {".txt", ".md"}:
        text = body.decode("utf-8-sig")
    elif extension == ".pdf":
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("Encrypted PDFs and PDFs exceeding 100 pages are not supported.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif extension == ".docx":
        check_archive(body, maximum_uncompressed=30_000_000)
        document = Document(io.BytesIO(body))
        text = "\n".join(
            [p.text for p in document.paragraphs]
            + [" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows]
        )
    else:
        raise ValueError("Supported documents: UTF-8 TXT/MD, text-based PDF, DOCX. OCR is not included.")
    if not text.strip() or len(text) > 500_000:
        raise ValueError("No extractable text or document exceeds 500,000 characters.")
    return text


def add_document(store, dataset_id, filename, body, model):
    directory = store.directory(dataset_id) / "documents"
    directory.mkdir(exist_ok=True)
    text = extract_text(filename, body)
    model_digest = model.verify_downloaded(model.settings.embedding_model)
    content_hash = hashlib.sha256(body).hexdigest()
    identity = hashlib.sha256((content_hash + model_digest + "chunk-v1-800-100").encode()).hexdigest()
    manifest = directory / f"{identity}.json"
    if manifest.exists():
        return {
            "document_id": identity,
            "cached": True,
            "chunks": len(json.loads(manifest.read_text())["chunks"]),
        }
    chunks = [
        text[index : index + 800] for index in range(0, len(text), 700) if text[index : index + 800].strip()
    ]
    vectors = np.array(model.embed(chunks), dtype="float32")
    if vectors.ndim != 2 or len(vectors) != len(chunks) or not np.isfinite(vectors).all():
        raise ValueError("Invalid embedding vectors.")
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(directory / f"{identity}.faiss"))
    (directory / f"{identity}{Path(filename).suffix.lower()}").write_bytes(body)
    atomic_json(
        manifest,
        {
            "id": identity,
            "source": Path(filename.replace("\\", "/")).name[:200],
            "content_hash": content_hash,
            "embedding_digest": model_digest,
            "chunks": chunks,
        },
    )
    store.audit(
        dataset_id, "document_indexed", {"id": identity, "content_hash": content_hash, "chunks": len(chunks)}
    )
    return {"document_id": identity, "cached": False, "chunks": len(chunks)}


def retrieve(store, dataset_id, question, model, limit=4):
    directory = store.directory(dataset_id) / "documents"
    if not directory.exists() or not list(directory.glob("*.json")):
        return []
    digest = model.verify_downloaded(model.settings.embedding_model)
    vector = np.array(model.embed([question]), dtype="float32")
    faiss.normalize_L2(vector)
    matches = []
    for path in directory.glob("*.json"):
        manifest = json.loads(path.read_text())
        if manifest["embedding_digest"] != digest:
            continue
        index = faiss.read_index(str(path.with_suffix(".faiss")))
        if vector.shape[1] != index.d:
            continue
        scores, indices = index.search(vector, min(limit, index.ntotal))
        for score, number in zip(scores[0], indices[0]):
            if number >= 0:
                matches.append(
                    {
                        "source_id": f"{manifest['id']}:{number}",
                        "source": manifest["source"],
                        "chunk": int(number),
                        "similarity": float(score),
                        "text": manifest["chunks"][number],
                        "type": "organizational_document",
                    }
                )
    return sorted(matches, key=lambda item: item["similarity"], reverse=True)[:limit]


def evaluate_retrieval(cases, search):
    if not cases:
        raise ValueError("Supply questions with human-labeled relevant source IDs.")
    scores = []
    for case in cases:
        relevant = set(case["relevant_source_ids"])
        found = {result["source_id"] for result in search(case["question"])}
        scores.append(
            {
                "question": case["question"],
                "precision": len(found & relevant) / max(len(found), 1),
                "recall": len(found & relevant) / max(len(relevant), 1),
            }
        )
    return scores
