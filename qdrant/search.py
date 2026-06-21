import sys
import logging
from pathlib import Path

from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding, SparseTextEmbedding

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("test_search")
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
TOP_K = 10


# ---------------------------------------------------------------------------
# Search + thread expansion
# ---------------------------------------------------------------------------

class HybridSearchTester:
    """
    Hybrid (dense + sparse, RRF-fused) search against knowledge_v1,
    with full thread expansion for every matched chunk's thread_id.
    """

    def __init__(self, qdrant_url: str, collection_name: str, top_k: int = TOP_K):
        self.qdrant_url      = qdrant_url
        self.collection_name = collection_name
        self.top_k           = top_k

        self.client       = None
        self.dense_model  = None
        self.sparse_model = None

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            self.client = QdrantClient(url=self.qdrant_url)
            self.client.get_collections()
        except Exception as e:
            logger.error("Could not connect to Qdrant at %s | error=%s", self.qdrant_url, e)
            raise ConnectionError(f"Qdrant unreachable at {self.qdrant_url}") from e

    def _load_models(self) -> None:
        logger.info("Loading dense model: %s", DENSE_MODEL_NAME)
        self.dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME)
        logger.info("Loading sparse model: %s", SPARSE_MODEL_NAME)
        self.sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[dict]:
        if self.client is None:
            self._connect()
        if self.dense_model is None:
            self._load_models()

        if not query or not query.strip():
            logger.warning("Empty query — skipping search")
            return []

        try:
            dense_vec  = list(self.dense_model.embed([query]))[0]
            sparse_vec = list(self.sparse_model.embed([query]))[0]
        except Exception as e:
            logger.error("Failed to embed query | error=%s", e)
            return []

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=dense_vec.tolist(),
                        using="dense",
                        limit=self.top_k * 2,
                    ),
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist(),
                        ),
                        using="sparse",
                        limit=self.top_k * 2,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=self.top_k,
                with_payload=True,
            )
        except Exception as e:
            logger.error("Qdrant query failed | error=%s", e)
            return []

        results = [
            {"score": point.score, "payload": point.payload}
            for point in response.points
        ]
        logger.info("Query=%r returned %d matches", query, len(results))
        return results

    # ------------------------------------------------------------------
    # Thread expansion
    # ------------------------------------------------------------------

    def expand_threads(self, results: list[dict]) -> dict[str, list[dict]]:
        """
        For every unique thread_id among the matched results, fetch ALL
        points in Qdrant sharing that thread_id, sorted chronologically.
        Returns {thread_id: [chunk_payload, ...]}.
        """
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
                        must=[
                            models.FieldCondition(
                                key="thread_id",
                                match=models.MatchValue(value=tid),
                            )
                        ]
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


# ---------------------------------------------------------------------------
# CLI display
# ---------------------------------------------------------------------------

def print_results(query: str, results: list[dict], threads: dict[str, list[dict]]) -> None:
    print(f"\n{'='*70}\nQUERY: {query}\n{'='*70}")

    if not results:
        print("No matches found.")
        return

    print(f"\nTop {len(results)} matched chunks:\n")
    for i, r in enumerate(results, start=1):
        p = r["payload"]
        print(f"[{i}] score={r['score']:.4f} | {p.get('date','')} | from={p.get('sender_email','')}")
        print(f"    subject-ish text: {p.get('text','')[:120]}...")

    print(f"\n{'-'*70}\nFull thread context for each matched email's conversation:\n")
    for tid, emails in threads.items():
        print(f"Thread: {tid}  ({len(emails)} email(s))")
        for e in emails:
            print(f"   - {e.get('date','')} | {e.get('sender_email','')} | {e.get('text','')[:100]}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "NOC from MoCA to operate cargo flight at VAOZ airport"

    tester = HybridSearchTester(
        qdrant_url="http://localhost:6333",
        collection_name="knowledge_v4",
    )

    results = tester.search(query)
    threads = tester.expand_threads(results)
    print_results(query, results, threads)