import json
import logging
import uuid
from pathlib import Path
from qdrant_client import QdrantClient, models
from fastembed import TextEmbedding, SparseTextEmbedding

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("qdrant_ingest")
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
DENSE_DIM         = 384

# Payload fields that get a keyword index for filtered/metadata search
KEYWORD_INDEX_FIELDS = [
    "request_id", "invoice_id", "receipt_id", "permission_number",
    "direction", "sender_email", "sender_company", "thread_id",
    "flight_numbers", "aircraft_registrations",
]


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class QdrantIngestionPipeline:
    """
    Creates (or reuses) a Qdrant collection with dense + sparse vector support,
    embeds chunks client-side via fastembed, and upserts them in batches.
    """

    def __init__(
        self,
        chunks_path: Path,
        qdrant_url: str,
        collection_name: str,
        batch_size: int = 64,
    ):
        self.chunks_path     = chunks_path
        self.qdrant_url      = qdrant_url
        self.collection_name = collection_name
        self.batch_size      = batch_size

        self.client = None
        self.dense_model  = None
        self.sparse_model = None

        self.stats = {
            "chunks_loaded":   0,
            "skipped_empty":   0,
            "points_upserted": 0,
            "batches_failed":  0,
        }

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info(
            "Starting Qdrant ingestion | collection=%s url=%s",
            self.collection_name, self.qdrant_url,
        )

        self._connect()
        self._ensure_collection()
        self._ensure_payload_indexes()

        chunks = self._load_chunks()
        self.stats["chunks_loaded"] = len(chunks)

        chunks = [c for c in chunks if c.get("text", "").strip()]
        self.stats["skipped_empty"] = self.stats["chunks_loaded"] - len(chunks)
        if self.stats["skipped_empty"]:
            logger.warning("Skipped %d chunks with empty text", self.stats["skipped_empty"])

        self._load_embedding_models()

        for batch_start in range(0, len(chunks), self.batch_size):
            batch = chunks[batch_start: batch_start + self.batch_size]
            self._process_batch(batch, batch_start)

        self._log_summary()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        try:
            self.client = QdrantClient(url=self.qdrant_url)
            self.client.get_collections()  # forces a real connection check
        except Exception as e:
            logger.error("Could not connect to Qdrant at %s | error=%s", self.qdrant_url, e)
            raise ConnectionError(f"Qdrant unreachable at {self.qdrant_url}") from e

    def _ensure_collection(self) -> None:
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name in existing:
            logger.info("Collection '%s' already exists — reusing", self.collection_name)
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config={
                "dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF),
            },
        )
        logger.info("Created collection '%s'", self.collection_name)

    def _ensure_payload_indexes(self) -> None:
        for field in KEYWORD_INDEX_FIELDS:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                # Index may already exist — not fatal, just log at debug level
                logger.debug("Payload index skip/exists | field=%s error=%s", field, e)

    def _load_embedding_models(self) -> None:
        logger.info("Loading dense model: %s", DENSE_MODEL_NAME)
        self.dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME)
        logger.info("Loading sparse model: %s", SPARSE_MODEL_NAME)
        self.sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_chunks(self) -> list[dict]:
        if not self.chunks_path.exists():
            logger.error("Chunks file not found: %s", self.chunks_path)
            raise FileNotFoundError(f"Missing input file: {self.chunks_path}")

        chunks = []
        with open(self.chunks_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("Malformed JSON | line=%d error=%s", line_num, e)
        return chunks

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------

    def _process_batch(self, batch: list[dict], batch_start: int) -> None:
        texts = [c["text"] for c in batch]

        try:
            dense_vectors  = list(self.dense_model.embed(texts))
            sparse_vectors = list(self.sparse_model.embed(texts))
        except Exception as e:
            logger.error(
                "Embedding failed for batch [%d:%d] | error=%s",
                batch_start, batch_start + len(batch), e,
            )
            self.stats["batches_failed"] += 1
            return

        points = []
        for chunk, dense_vec, sparse_vec in zip(batch, dense_vectors, sparse_vectors):
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "dense": dense_vec.tolist(),
                        "sparse": models.SparseVector(
                            indices=sparse_vec.indices.tolist(),
                            values=sparse_vec.values.tolist(),
                        ),
                    },
                    payload=chunk,
                )
            )

        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
            self.stats["points_upserted"] += len(points)
            logger.debug("Upserted batch [%d:%d]", batch_start, batch_start + len(batch))
        except Exception as e:
            logger.error(
                "Upsert failed for batch [%d:%d] | error=%s",
                batch_start, batch_start + len(batch), e,
            )
            self.stats["batches_failed"] += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _log_summary(self) -> None:
        logger.info(
            "Ingestion complete | chunks_loaded=%d skipped_empty=%d "
            "points_upserted=%d batches_failed=%d collection=%s",
            self.stats["chunks_loaded"],
            self.stats["skipped_empty"],
            self.stats["points_upserted"],
            self.stats["batches_failed"],
            self.collection_name,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = QdrantIngestionPipeline(
        chunks_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\processed\\chunks_v4.jsonl"),
        qdrant_url="http://localhost:6333",
        collection_name="knowledge_v4",
        batch_size=64,
    )
    pipeline.run()