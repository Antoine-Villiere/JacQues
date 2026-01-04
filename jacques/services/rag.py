from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pickle
import threading

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from ..config import RAG_INDEX_DIR, Settings
from .. import db


@dataclass
class SearchResult:
    doc_id: int
    name: str
    score: float
    text: str


def build_index(conversation_id: int) -> None:
    index_path = _index_path(conversation_id)
    documents = db.get_document_texts(conversation_id)
    if not documents:
        if index_path.exists():
            index_path.unlink()
        _drop_cache(conversation_id)
        return

    filtered = [
        (row["id"], row["name"], row["text"])
        for row in documents
        if (row["text"] or "").strip()
    ]
    if not filtered:
        if index_path.exists():
            index_path.unlink()
        _drop_cache(conversation_id)
        return

    doc_ids = [doc_id for doc_id, _, _ in filtered]
    names = [name for _, name, _ in filtered]
    texts = [text for _, _, text in filtered]

    vectorizer = TfidfVectorizer(max_features=5000)
    try:
        matrix = vectorizer.fit_transform(texts)
    except ValueError:
        if index_path.exists():
            index_path.unlink()
        return

    payload = {
        "vectorizer": vectorizer,
        "matrix": matrix,
        "doc_ids": doc_ids,
        "names": names,
    }
    with index_path.open("wb") as handle:
        pickle.dump(payload, handle)
    _update_cache(conversation_id, payload, index_path)


def delete_index(conversation_id: int) -> None:
    index_path = _index_path(conversation_id)
    if index_path.exists():
        index_path.unlink()
    _drop_cache(conversation_id)

_INDEX_CACHE: dict[int, dict[str, object]] = {}
_CACHE_LOCK = threading.Lock()


def _load_index(conversation_id: int) -> dict | None:
    index_path = _index_path(conversation_id)
    if not index_path.exists():
        _drop_cache(conversation_id)
        return None
    mtime = index_path.stat().st_mtime
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(conversation_id)
        if cached and cached.get("mtime") == mtime:
            return cached.get("payload")  # type: ignore[return-value]
    with index_path.open("rb") as handle:
        payload = pickle.load(handle)
    _update_cache(conversation_id, payload, index_path)
    return payload

def search(query: str, settings: Settings, conversation_id: int) -> list[SearchResult]:
    payload = _load_index(conversation_id)
    if payload is None:
        return []

    vectorizer = payload["vectorizer"]
    matrix = payload["matrix"]
    doc_ids = payload["doc_ids"]
    names = payload["names"]

    query_vec = vectorizer.transform([query])
    scores = cosine_similarity(query_vec, matrix).flatten()
    if scores.size == 0:
        return []

    top_k = min(settings.rag_top_k, scores.size)
    ranked = scores.argsort()[::-1][:top_k]

    doc_map = {
        row["id"]: row["text"] for row in db.get_document_texts(conversation_id)
    }
    results: list[SearchResult] = []
    for idx in ranked:
        doc_id = int(doc_ids[idx])
        text = doc_map.get(doc_id, "")
        results.append(
            SearchResult(
                doc_id=doc_id,
                name=names[idx],
                score=float(scores[idx]),
                text=text,
            )
        )
    return results


def format_results(results: list[SearchResult], max_chars: int = 1200) -> str:
    chunks = []
    for result in results:
        clipped = result.text
        if len(clipped) > max_chars:
            clipped = clipped[:max_chars].rsplit(" ", 1)[0] + "..."
        chunks.append(f"[{result.name}] (score {result.score:.2f})\n{clipped}")
    return "\n\n".join(chunks).strip()


def _index_path(conversation_id: int) -> Path:
    return RAG_INDEX_DIR / f"rag_{conversation_id}.pkl"


def _update_cache(conversation_id: int, payload: dict, index_path: Path) -> None:
    with _CACHE_LOCK:
        _INDEX_CACHE[conversation_id] = {
            "mtime": index_path.stat().st_mtime,
            "payload": payload,
        }


def _drop_cache(conversation_id: int) -> None:
    with _CACHE_LOCK:
        _INDEX_CACHE.pop(conversation_id, None)
