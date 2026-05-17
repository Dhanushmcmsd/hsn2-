"""Background singleton FAISS semantic index — tier-5 fallback only, never blocks requests."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from app.config import settings

log = structlog.get_logger()

_DEFAULT_INDEX_DIR = Path(os.getenv("FAISS_INDEX_DIR", "data/faiss"))


class FAISSService:
    """Process-lifetime FAISS index loaded once in a background thread at startup."""

    def __init__(self, index_path: str | None = None) -> None:
        self.ready: bool = False
        self.loading: bool = False
        self.failed: bool = False
        self.last_error: str | None = None
        self.load_started_at: datetime | None = None
        self.load_completed_at: datetime | None = None
        self.load_time_ms: float | None = None
        self.index_path: str = index_path or str(_DEFAULT_INDEX_DIR)
        self.index_size_bytes: int | None = None

        self._dataset: list[dict] = []
        self._model = None
        self._index = None
        self._warmup_lock = threading.Lock()
        self._state_lock = threading.Lock()

    def start_warmup(self) -> None:
        """Trigger background index build; returns immediately."""
        if os.getenv("FAISS_DISABLED") == "1":
            log.info("faiss.warmup_skipped", reason="FAISS_DISABLED")
            return
        with self._state_lock:
            if self.ready or self.loading or self.failed:
                return
            self.loading = True
            self.load_started_at = datetime.now(timezone.utc)
        log.info("faiss.warmup_start", index_path=self.index_path)
        thread = threading.Thread(target=self._load_worker, name="faiss-warmup", daemon=True)
        thread.start()

    def is_ready(self) -> bool:
        return self.ready

    def status_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "loading": self.loading,
            "failed": self.failed,
            "load_time_ms": self.load_time_ms,
            "index_size_bytes": self.index_size_bytes,
            "last_error": self.last_error,
            "index_path": self.index_path,
        }

    def search_text(self, query: str, k: int) -> list[dict] | None:
        """Encode *query* and run inner-product search. Returns None if not ready."""
        if not self.is_ready() or self._index is None or self._model is None:
            return None
        try:
            import numpy as np

            from app.services.matcher import (
                expand_fmcg_abbreviations,
                expand_tokens,
                tokenize,
            )

            text = expand_fmcg_abbreviations(query or "")
            tokens = tokenize(text)
            query_text = " ".join(expand_tokens(tokens)) if tokens else text.lower()
            query_vec = self._model.encode([query_text], normalize_embeddings=True).astype(np.float32)
            return self.search(query_vec, k)
        except Exception as exc:
            log.warning("faiss.search_text_failed", error=str(exc)[:200])
            return None

    def search(self, query_vector: Any, k: int) -> list[dict] | None:
        """Inner-product FAISS search. Returns None if index is not ready."""
        if not self.is_ready() or self._index is None:
            return None
        try:
            scores, indices = self._index.search(query_vector, k)
            results: list[dict] = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self._dataset):
                    continue
                item = self._dataset[idx]
                results.append({
                    **item,
                    "score": round(float(score), 4),
                    "method": "semantic",
                })
            log.debug("faiss.search_used", k=k, hits=len(results))
            return results
        except Exception as exc:
            log.warning("faiss.search_failed", error=str(exc)[:200])
            return None

    def _load_worker(self) -> None:
        with self._warmup_lock:
            if self.ready or self.failed:
                with self._state_lock:
                    self.loading = False
                return
            started = time.perf_counter()
            try:
                self._build_index()
                elapsed_ms = (time.perf_counter() - started) * 1000
                with self._state_lock:
                    self.ready = True
                    self.loading = False
                    self.load_completed_at = datetime.now(timezone.utc)
                    self.load_time_ms = round(elapsed_ms, 2)
                log.info(
                    "faiss.warmup_success",
                    load_time_ms=self.load_time_ms,
                    rows=len(self._dataset),
                    index_size_bytes=self.index_size_bytes,
                )
            except Exception as exc:
                err = str(exc)[:500]
                with self._state_lock:
                    self.failed = True
                    self.loading = False
                    self.last_error = err
                    self.load_completed_at = datetime.now(timezone.utc)
                    self.load_time_ms = round((time.perf_counter() - started) * 1000, 2)
                log.warning("faiss.warmup_failed", error=err, load_time_ms=self.load_time_ms)

    def _build_index(self) -> None:
        import numpy as np

        from app.services.dataset import get_dataset

        index_dir = Path(self.index_path)
        index_file = index_dir / "hsn.index"
        meta_file = index_dir / "hsn_meta.npy"

        self._dataset = get_dataset()
        if not self._dataset:
            raise RuntimeError("FAISS dataset is empty")

        if index_file.is_file() and meta_file.is_file():
            import faiss

            self._index = faiss.read_index(str(index_file))
            self.index_size_bytes = index_file.stat().st_size
            log.info("faiss.index_loaded_from_disk", path=str(index_file), rows=len(self._dataset))
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
            if self._index.ntotal != len(self._dataset):
                log.warning(
                    "faiss.index_row_mismatch",
                    index_ntotal=self._index.ntotal,
                    dataset_rows=len(self._dataset),
                )
            return

        from sentence_transformers import SentenceTransformer
        import faiss

        log.info("faiss.build_start", rows=len(self._dataset), model=settings.EMBEDDING_MODEL)
        self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        texts = [d["description"] for d in self._dataset]
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings.astype(np.float32))
        self._index = index

        try:
            index_dir.mkdir(parents=True, exist_ok=True)
            faiss.write_index(index, str(index_file))
            np.save(str(meta_file), np.arange(len(self._dataset), dtype=np.int32))
            self.index_size_bytes = index_file.stat().st_size
            log.info("faiss.index_persisted", path=str(index_file))
        except OSError as exc:
            log.warning("faiss.index_persist_skipped", error=str(exc)[:120])
            self.index_size_bytes = int(embeddings.nbytes)


_service: FAISSService | None = None
_service_lock = threading.Lock()


def get_faiss_service() -> FAISSService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = FAISSService()
    return _service


def faiss_skip_status() -> str:
    """Reason code for skipping FAISS on the current request path."""
    if os.getenv("FAISS_DISABLED") == "1":
        return "disabled"
    svc = get_faiss_service()
    if svc.failed:
        return "failed_skipped"
    if not svc.is_ready():
        if svc.loading:
            return "cold_skipped"
        return "cold_skipped"
    return "used"
