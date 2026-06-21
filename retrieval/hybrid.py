import logging
from pathlib import Path

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding, SparseTextEmbedding

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("hybrid_retriever")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "pipeline.log")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger

logger = _get_logger()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DENSE_MODEL_NAME  = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL_NAME = "Qdrant/bm25"
DEFAULT_TOP_K     = 10


# ---------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    Retrieval layer over a Qdrant collection supporting:
      - metadata_search(): pure payload filter, no embedding involved
      - dense_search():    dense-vector-only search, optional filters
      - sparse_search():   sparse-vector-only (BM25) search, optional filters
      - search():          hybrid dense+sparse search, RRF-fused, optional filters
      - expand_threads():  fetch all chunks sharing a thread_id for a set of results
    """

    def __init__(self, qdrant_url: str, collection_name: str):
        self.qdrant_url      = qdrant_url
        self.collection_name = collection_name

        self.client       = None
        self.dense_model  = None
        self.sparse_model = None

    # ------------------------------------------------------------------
    # Setup (lazy — only loads what's actually needed)
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        if self.client is not None:
            return
        try:
            self.client = QdrantClient(url=self.qdrant_url)
            self.client.get_collections()
        except Exception as e:
            logger.error("Could not connect to Qdrant at %s | error=%s", self.qdrant_url, e)
            raise ConnectionError(f"Qdrant unreachable at {self.qdrant_url}") from e

    def _load_dense_model(self) -> None:
        if self.dense_model is not None:
            return
        logger.info("Loading dense model: %s", DENSE_MODEL_NAME)
        self.dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME)

    def _load_sparse_model(self) -> None:
        if self.sparse_model is not None:
            return
        logger.info("Loading sparse model: %s", SPARSE_MODEL_NAME)
        self.sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)

    # ------------------------------------------------------------------
    # Filter building
    # ------------------------------------------------------------------

    def _build_filter(self, filters: dict | None) -> models.Filter | None:
        """
        Converts {"field_name": value_or_list} into a Qdrant Filter.
        - list value   -> MatchAny
        - scalar value -> MatchValue
        No field-name translation or guessing — caller must use exact payload keys.
        """
        if not filters:
            return None

        conditions = []
        for field_name, value in filters.items():
            if isinstance(value, list):
                conditions.append(
                    models.FieldCondition(key=field_name, match=models.MatchAny(any=value))
                )
            else:
                conditions.append(
                    models.FieldCondition(key=field_name, match=models.MatchValue(value=value))
                )

        return models.Filter(must=conditions)

    # ------------------------------------------------------------------
    # Metadata-only search — no embedding, pure payload filter
    # ------------------------------------------------------------------

    def metadata_search(self, filters: dict, limit: int = 50) -> list[dict]:
        if not filters:
            logger.warning("metadata_search called with no filters — refusing to return entire collection")
            return []

        self._connect()
        query_filter = self._build_filter(filters)

        try:
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception as e:
            logger.error("metadata_search failed | filters=%s error=%s", filters, e)
            return []

        results = [p.payload for p in points]
        logger.info("metadata_search filters=%s returned %d results", filters, len(results))
        return results

    # ------------------------------------------------------------------
    # Dense-only search
    # ------------------------------------------------------------------

    def dense_search(self, query: str, filters: dict | None = None, top_k: int = 10) -> list[dict]:
        if not query or not query.strip():
            logger.warning("dense_search called with empty query")
            return []

        self._connect()
        self._load_dense_model()

        try:
            dense_vec = list(self.dense_model.embed([query]))[0]
        except Exception as e:
            logger.error("Failed to embed query for dense_search | error=%s", e)
            return []

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=dense_vec.tolist(),
                using="dense",
                query_filter=self._build_filter(filters),
                limit=top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.error("dense_search query failed | error=%s", e)
            return []

        results = [{"score": p.score, "payload": p.payload} for p in response.points]
        logger.info("dense_search query=%r returned %d results", query, len(results))
        return results

    # ------------------------------------------------------------------
    # Sparse-only (BM25) search
    # ------------------------------------------------------------------

    def sparse_search(self, query: str, filters: dict | None = None, top_k: int = 10) -> list[dict]:
        if not query or not query.strip():
            logger.warning("sparse_search called with empty query")
            return []

        self._connect()
        self._load_sparse_model()

        try:
            sparse_vec = list(self.sparse_model.embed([query]))[0]
        except Exception as e:
            logger.error("Failed to embed query for sparse_search | error=%s", e)
            return []

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=models.SparseVector(
                    indices=sparse_vec.indices.tolist(),
                    values=sparse_vec.values.tolist(),
                ),
                using="sparse",
                query_filter=self._build_filter(filters),
                limit=top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.error("sparse_search query failed | error=%s", e)
            return []

        results = [{"score": p.score, "payload": p.payload} for p in response.points]
        logger.info("sparse_search query=%r returned %d results", query, len(results))
        return results

    # ------------------------------------------------------------------
    # Hybrid search — dense + sparse, RRF-fused server-side
    # ------------------------------------------------------------------

    def search(self, query: str, filters: dict | None = None, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        if not query or not query.strip():
            logger.warning("search called with empty query")
            return []

        self._connect()
        self._load_dense_model()
        self._load_sparse_model()

        try:
            dense_vec  = list(self.dense_model.embed([query]))[0]
            sparse_vec = list(self.sparse_model.embed([query]))[0]
        except Exception as e:
            logger.error("Failed to embed query for hybrid search | error=%s", e)
            return []

        query_filter = self._build_filter(filters)

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=dense_vec.tolist(),
                        using="dense",
                        filter=query_filter,
                        limit=top_k * 2,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist(),
                        ),
                        using="sparse",
                        filter=query_filter,
                        limit=top_k * 2,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.error("Hybrid search query failed | error=%s", e)
            return []

        results = [{"score": p.score, "payload": p.payload} for p in response.points]
        logger.info("search query=%r filters=%s returned %d results", query, filters, len(results))
        return results

    # ------------------------------------------------------------------
    # Thread expansion
    # ------------------------------------------------------------------

    def expand_threads(self, results: list[dict]) -> dict[str, list[dict]]:
        """
        For every unique thread_id among the given results, fetch ALL points
        in Qdrant sharing that thread_id, sorted chronologically.
        Returns {thread_id: [chunk_payload, ...]}.
        """
        self._connect()

        thread_ids = []
        for r in results:
            tid = r["payload"].get("thread_id", "")
            if tid and tid not in thread_ids:
                thread_ids.append(tid)

        threads = {}
        for tid in thread_ids:
            try:
                points, _ = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[models.FieldCondition(key="thread_id", match=models.MatchValue(value=tid))]
                    ),
                    limit=100,
                    with_payload=True,
                )
            except Exception as e:
                logger.error("Thread expansion failed | thread_id=%s error=%s", tid, e)
                continue

            emails = [p.payload for p in points]
            emails.sort(key=lambda e: e.get("date", ""))
            threads[tid] = emails

        return threads