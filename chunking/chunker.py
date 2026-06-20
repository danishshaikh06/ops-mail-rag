import json
import logging
import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("chunker")
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
# Pipeline class
# ---------------------------------------------------------------------------

class EmailChunker:
    """
    Joins cleaned email bodies with extracted metadata and produces
    one chunk per email ("1 email = 1 chunk" strategy).
    """

    def __init__(self, cleaned_path: Path, metadata_path: Path, output_path: Path):
        self.cleaned_path  = cleaned_path
        self.metadata_path = metadata_path
        self.output_path   = output_path

        # Run counters — surfaced in the final summary log
        self.stats = {
            "cleaned_loaded":   0,
            "metadata_loaded":  0,
            "skipped_system":   0,
            "skipped_orphaned": 0,
            "skipped_malformed": 0,
            "chunks_written":   0,
        }

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info(
            "Starting chunking | cleaned=%s metadata=%s",
            self.cleaned_path, self.metadata_path,
        )

        self._validate_inputs_exist()

        cleaned_by_id  = self._load_jsonl_keyed(self.cleaned_path, key_field="id")
        metadata_by_id = self._load_jsonl_keyed(self.metadata_path, key_field="email_id")

        self.stats["cleaned_loaded"]  = len(cleaned_by_id)
        self.stats["metadata_loaded"] = len(metadata_by_id)

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_path, "w", encoding="utf-8") as outfile:
            for email_id, cleaned_record in cleaned_by_id.items():
                try:
                    chunk = self._build_chunk(email_id, cleaned_record, metadata_by_id)
                except _SkipRecord as skip:
                    logger.debug("Skipped | id=%s reason=%s", email_id, skip)
                    continue

                if chunk is None:
                    continue

                outfile.write(json.dumps(chunk) + "\n")
                self.stats["chunks_written"] += 1

        self._log_summary()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_inputs_exist(self) -> None:
        missing = [p for p in (self.cleaned_path, self.metadata_path) if not p.exists()]
        if missing:
            paths = ", ".join(str(p) for p in missing)
            logger.error("Missing required input file(s): %s", paths)
            raise FileNotFoundError(f"Chunking aborted — missing input file(s): {paths}")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_jsonl_keyed(self, path: Path, key_field: str) -> dict:
        """Load a JSONL file into a dict keyed by key_field. Skips malformed lines."""
        records = {}
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Malformed JSON | file=%s line=%d error=%s", path, line_num, e
                    )
                    self.stats["skipped_malformed"] += 1
                    continue

                key = record.get(key_field)
                if not key:
                    logger.warning(
                        "Record missing key field '%s' | file=%s line=%d",
                        key_field, path, line_num,
                    )
                    self.stats["skipped_malformed"] += 1
                    continue

                records[key] = record
        return records

    # ------------------------------------------------------------------
    # Chunk construction
    # ------------------------------------------------------------------

    def _build_chunk(self, email_id: str, cleaned_record: dict, metadata_by_id: dict) -> dict | None:
        if cleaned_record.get("is_system_email"):
            self.stats["skipped_system"] += 1
            raise _SkipRecord("system_email")

        metadata_record = metadata_by_id.get(email_id)
        if metadata_record is None:
            logger.warning("Orphaned record — no metadata found | id=%s", email_id)
            self.stats["skipped_orphaned"] += 1
            raise _SkipRecord("orphaned_no_metadata")

        body_clean = cleaned_record.get("body_clean", "") or ""
        if not body_clean.strip():
            # Non-system email with empty cleaned body — nothing to embed
            logger.debug("Empty body_clean after cleaning | id=%s", email_id)
            self.stats["skipped_orphaned"] += 0  # not orphaned, just empty — separate counter not requested
            raise _SkipRecord("empty_body")

        subject  = metadata_record.get("subject", "") or cleaned_record.get("subject", "")
        sender   = metadata_record.get("sender_email", "")
        date     = metadata_record.get("date", "")

        embedding_text = self._build_embedding_text(subject, sender, date, body_clean)

        return {
            "chunk_id":               self._generate_chunk_id(email_id),
            "email_id":               email_id,
            "thread_id":              metadata_record.get("thread_id", ""),
            "request_id":             metadata_record.get("request_id", ""),
            "invoice_id":             metadata_record.get("invoice_id", ""),
            "receipt_id":             metadata_record.get("receipt_id", ""),
            "permission_number":      metadata_record.get("permission_number", ""),
            "text":                   embedding_text,
            "direction":              self._infer_direction(sender),
            "sender_email":           sender,
            "recipient_emails":       metadata_record.get("recipient_emails", []),
            "sender_name":            metadata_record.get("sender_name", ""),
            "sender_company":         metadata_record.get("sender_company", ""),
            "sender_designation":     metadata_record.get("sender_designation", ""),
            "date":                   date,
            "flight_numbers":         metadata_record.get("flight_numbers", []),
            "aircraft_registrations": metadata_record.get("aircraft_registrations", []),
        }

    def _build_embedding_text(self, subject: str, sender: str, date: str, body_clean: str) -> str:
        return (
            f"Subject: {subject}\n"
            f"From: {sender}\n"
            f"Date: {date}\n"
            f"Body: {body_clean}"
        )

    def _generate_chunk_id(self, email_id: str) -> str:
        return hashlib.sha256(email_id.encode("utf-8")).hexdigest()

    def _infer_direction(self, sender_email: str) -> str:
        return "outbound" if "smb-freight.com" in sender_email.lower() else "inbound"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _log_summary(self) -> None:
        logger.info(
            "Chunking complete | cleaned_loaded=%d metadata_loaded=%d "
            "chunks_written=%d skipped_system=%d skipped_orphaned=%d skipped_malformed=%d "
            "output=%s",
            self.stats["cleaned_loaded"],
            self.stats["metadata_loaded"],
            self.stats["chunks_written"],
            self.stats["skipped_system"],
            self.stats["skipped_orphaned"],
            self.stats["skipped_malformed"],
            self.output_path,
        )


class _SkipRecord(Exception):
    """Internal control-flow signal — not a real error, just 'don't chunk this one'."""
    pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    chunker = EmailChunker(
        cleaned_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\cleaned\\cleaned_emails_v2.jsonl"),
        metadata_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\metadata\\email_metadata.jsonl"),
        output_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\processed\\chunks.jsonl"),
    )
    chunker.run()