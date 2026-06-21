import logging
from pathlib import Path

from sentence_transformers import CrossEncoder

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("reranker")
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

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_model = None  # lazy-loaded module-level singleton — avoids reloading on every call


def _get_model() -> CrossEncoder:
    global _model
    if _model is None:
        logger.info("Loading cross-encoder model: %s", MODEL_NAME)
        _model = CrossEncoder(MODEL_NAME)
    return _model


# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------

def rerank(query: str, results: list[dict], top_k: int = 5) -> list[dict]:
    """
    Re-scores hybrid/dense/sparse search results with a cross-encoder.

    Input/output shape matches HybridRetriever.search():
        [{"score": float, "payload": {...}}, ...]

    The original RRF/vector score is replaced with the cross-encoder score.
    On failure, logs the error and returns the original results unranked
    (truncated to top_k) rather than crashing the caller.
    """
    if not results:
        return []

    if not query or not query.strip():
        logger.warning("rerank called with empty query — returning original order")
        return results[:top_k]

    try:
        model = _get_model()
        pairs = [(query, r["payload"].get("text", "")) for r in results]
        scores = model.predict(pairs)
    except Exception as e:
        logger.error("Reranking failed | error=%s — returning original order", e)
        return results[:top_k]

    reranked = [
        {"score": float(score), "payload": r["payload"]}
        for r, score in zip(results, scores)
    ]
    reranked.sort(key=lambda r: r["score"], reverse=True)

    logger.info("Reranked %d candidates | returning top %d", len(results), top_k)
    return reranked[:top_k]