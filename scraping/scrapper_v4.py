import os
import re
import json
import time
import logging
from pathlib import Path
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime, getaddresses

import imaplib
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("scraper")
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

IMAP_PORT          = 993
MAX_CONNECT_RETRIES = 3
RETRY_DELAY_SECONDS  = 5
PROGRESS_FILE        = Path("data/raw/.scrape_progress")

# Reply-chain quoting markers — lines from here onward are removed from body
REPLY_CHAIN_MARKERS = [
    r"^-{2,}\s*Original Message\s*-{2,}",
    r"^On .{5,100} wrote:$",
]

SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# IMAP fetching
# ---------------------------------------------------------------------------

class ImapFetcher:
    """Handles IMAP connection and raw message retrieval, with retry logic."""

    def __init__(self, host: str, email_addr: str, password: str, port: int = IMAP_PORT):
        self.host       = host
        self.email_addr = email_addr
        self.password   = password
        self.port       = port
        self.conn       = None

    def connect(self) -> None:
        last_error = None
        for attempt in range(1, MAX_CONNECT_RETRIES + 1):
            try:
                self.conn = imaplib.IMAP4_SSL(self.host, self.port)
                self.conn.login(self.email_addr, self.password)
                logger.info("IMAP connected | host=%s attempt=%d", self.host, attempt)
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    "IMAP connection attempt %d/%d failed | error=%s",
                    attempt, MAX_CONNECT_RETRIES, e,
                )
                if attempt < MAX_CONNECT_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

        logger.error("IMAP connection failed after %d attempts", MAX_CONNECT_RETRIES)
        raise ConnectionError(f"Could not connect to IMAP host {self.host}") from last_error

    def fetch_all_message_ids(self, mailbox: str = "INBOX") -> list[bytes]:
        self.conn.select(mailbox, readonly=True)
        status, data = self.conn.search(None, "ALL")
        if status != "OK":
            logger.error("IMAP search failed | status=%s", status)
            raise RuntimeError(f"IMAP SEARCH failed with status {status}")
        ids = data[0].split()
        logger.info("Found %d messages in mailbox '%s'", len(ids), mailbox)
        return ids

    def fetch_raw_message(self, msg_id: bytes) -> bytes | None:
        try:
            status, data = self.conn.fetch(msg_id, "(BODY.PEEK[])")
            if status != "OK" or not data or data[0] is None:
                logger.warning("Fetch failed for msg_id=%s | status=%s", msg_id, status)
                return None
            return data[0][1]
        except Exception as e:
            logger.warning("Exception fetching msg_id=%s | error=%s", msg_id, e)
            return None

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
                self.conn.logout()
        except Exception:
            pass  # best-effort cleanup, nothing to act on if it fails


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------

class MessageParser:
    """Parses a raw RFC822 message into our intermediate dict format."""

    def parse(self, raw_bytes: bytes) -> dict | None:
        try:
            msg = message_from_bytes(raw_bytes)
        except Exception as e:
            logger.warning("Could not parse raw message | error=%s", e)
            return None

        message_id = self._clean_id(msg.get("Message-ID", ""))
        if not message_id:
            logger.warning("Message has no Message-ID — skipping")
            return None

        subject    = self._decode_header_value(msg.get("Subject", ""))
        from_addrs = self._extract_addresses(msg.get("From", ""))
        to_addrs   = self._extract_addresses(msg.get("To", ""))
        date_iso   = self._parse_date(msg.get("Date", ""))
        references = self._parse_references(msg.get("References", ""))
        in_reply_to = self._clean_id(msg.get("In-Reply-To", ""))

        body = self._extract_body(msg)
        body = self._strip_reply_chain(body)

        return {
            "id":           message_id,
            "subject":      subject,
            "body":         body,
            "from":         from_addrs,
            "to":           to_addrs,
            "date":         date_iso,
            "_references":  references,    # internal use only — consumed by ThreadResolver
            "_in_reply_to": in_reply_to,    # internal use only
        }

    # ------------------------------------------------------------------
    # Header decoding
    # ------------------------------------------------------------------

    def _decode_header_value(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        try:
            parts = decode_header(raw_value)
            decoded = ""
            for text, encoding in parts:
                if isinstance(text, bytes):
                    decoded += text.decode(encoding or "utf-8", errors="replace")
                else:
                    decoded += text
            return decoded.strip()
        except Exception as e:
            logger.debug("Header decode failed | raw=%r error=%s", raw_value, e)
            return raw_value.strip()

    def _clean_id(self, raw_id: str) -> str:
        return raw_id.strip() if raw_id else ""

    def _parse_references(self, raw_refs: str) -> list[str]:
        if not raw_refs:
            return []
        # References header is whitespace-separated list of <id> tokens
        return re.findall(r"<[^<>]+>", raw_refs)

    def _extract_addresses(self, raw_value: str) -> list[str]:
        if not raw_value:
            return []
        try:
            pairs = getaddresses([raw_value])
            return [addr.lower().strip() for _, addr in pairs if addr]
        except Exception as e:
            logger.debug("Address parse failed | raw=%r error=%s", raw_value, e)
            return []

    def _parse_date(self, raw_date: str) -> str:
        if not raw_date:
            return ""
        try:
            dt = parsedate_to_datetime(raw_date)
            return dt.isoformat()
        except Exception as e:
            logger.debug("Date parse failed | raw=%r error=%s", raw_date, e)
            return ""

    # ------------------------------------------------------------------
    # Body extraction
    # ------------------------------------------------------------------

    def _extract_body(self, msg) -> str:
        plain_text = None
        html_text  = None

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition  = str(part.get("Content-Disposition", ""))
                if "attachment" in disposition:
                    continue
                try:
                    payload = part.get_payload(decode=True)
                    if payload is None:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                except Exception as e:
                    logger.debug("Failed to decode part | error=%s", e)
                    continue

                if content_type == "text/plain" and plain_text is None:
                    plain_text = text
                elif content_type == "text/html" and html_text is None:
                    html_text = text
        else:
            try:
                payload = msg.get_payload(decode=True)
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace") if payload else ""
                if msg.get_content_type() == "text/html":
                    html_text = text
                else:
                    plain_text = text
            except Exception as e:
                logger.debug("Failed to decode single-part body | error=%s", e)

        if plain_text is not None and plain_text.strip():
            return plain_text
        if html_text is not None:
            return self._html_to_text(html_text)
        return ""

    def _html_to_text(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            return soup.get_text(separator="\n")
        except Exception as e:
            logger.debug("HTML stripping failed | error=%s", e)
            return html

    def _strip_reply_chain(self, body: str) -> str:
        lines = body.split("\n")
        for i, line in enumerate(lines):
            for pattern in REPLY_CHAIN_MARKERS:
                if re.match(pattern, line.strip()):
                    return "\n".join(lines[:i]).strip()
        return body.strip()


# ---------------------------------------------------------------------------
# Thread resolution (3-tier, second pass over all parsed emails)
# ---------------------------------------------------------------------------

class ThreadResolver:
    """
    Assigns thread_id and reply_to using a 3-tier strategy:
      1. References header  -> root = first id in the chain
      2. In-Reply-To header -> inherit parent's resolved thread_id
      3. Subject normalization + participant overlap -> fallback grouping
    Tags every record with thread_match_method for provenance.
    """

    def resolve(self, emails: list[dict]) -> list[dict]:
        by_id = {e["id"]: e for e in emails}

        # --- Tier 1: References ---
        for e in emails:
            refs = e.get("_references", [])
            if refs:
                e["thread_id"] = refs[0]
                e["reply_to"]  = e.get("_in_reply_to", "") or refs[-1]
                e["thread_match_method"] = "references"

        # --- Tier 2: In-Reply-To (only for those still unresolved) ---
        for e in emails:
            if e.get("thread_id"):
                continue
            parent_id = e.get("_in_reply_to", "")
            if parent_id and parent_id in by_id:
                parent = by_id[parent_id]
                # Inherit parent's thread_id if parent already resolved (Tier 1),
                # otherwise fall back to the parent's own id as the root.
                e["thread_id"] = parent.get("thread_id") or parent_id
                e["reply_to"]  = parent_id
                e["thread_match_method"] = "in_reply_to"

        # --- Tier 3: subject + participant overlap fallback ---
        unresolved = [e for e in emails if not e.get("thread_id")]
        if unresolved:
            self._resolve_by_subject(unresolved, by_id)

        # --- Anything still unresolved: true original, self-referencing ---
        for e in emails:
            if not e.get("thread_id"):
                e["thread_id"] = e["id"]
                e["reply_to"]  = e.get("_in_reply_to", "")
                e["thread_match_method"] = "original"

        return emails

    def _normalize_subject(self, subject: str) -> str:
        prev = None
        s = subject.strip()
        while prev != s:
            prev = s
            s = SUBJECT_PREFIX_RE.sub("", s).strip()
        return s.lower()

    def _resolve_by_subject(self, unresolved: list[dict], by_id: dict) -> None:
        # Group unresolved emails by normalized subject
        groups: dict[str, list[dict]] = {}
        for e in unresolved:
            norm_subj = self._normalize_subject(e.get("subject", ""))
            if not norm_subj:
                continue
            groups.setdefault(norm_subj, []).append(e)

        for norm_subj, group in groups.items():
            if len(group) < 2:
                continue  # nothing to link — single email, stays unresolved -> becomes "original"

            # Check participant overlap pairwise; only merge emails that share
            # at least one sender/recipient address with another in the group
            linked = self._filter_by_participant_overlap(group)
            if len(linked) < 2:
                continue

            # Earliest email (by date) becomes the thread root
            linked.sort(key=lambda e: e.get("date") or "")
            root = linked[0]
            root_thread_id = root["id"]

            for e in linked:
                e["thread_id"] = root_thread_id
                if e is not root:
                    e["reply_to"] = e.get("_in_reply_to", "") or root_thread_id
                else:
                    e["reply_to"] = e.get("_in_reply_to", "")
                e["thread_match_method"] = "subject_fallback"

    def _filter_by_participant_overlap(self, group: list[dict]) -> list[dict]:
        """Keep only emails that share at least one participant address with
        at least one other email in the group."""
        participant_sets = []
        for e in group:
            participants = set(e.get("from", [])) | set(e.get("to", []))
            participant_sets.append(participants)

        keep = []
        for i, e in enumerate(group):
            has_overlap = any(
                participant_sets[i] & participant_sets[j]
                for j in range(len(group)) if j != i
            )
            if has_overlap:
                keep.append(e)
        return keep


# ---------------------------------------------------------------------------
# Progress tracking (resumable runs)
# ---------------------------------------------------------------------------

class ProgressTracker:
    def __init__(self, progress_file: Path):
        self.progress_file = progress_file

    def load_seen_ids(self) -> set[str]:
        if not self.progress_file.exists():
            return set()
        try:
            return set(self.progress_file.read_text(encoding="utf-8").splitlines())
        except Exception as e:
            logger.warning("Could not read progress file | error=%s", e)
            return set()

    def mark_seen(self, msg_id: str) -> None:
        try:
            self.progress_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.progress_file, "a", encoding="utf-8") as f:
                f.write(msg_id + "\n")
        except Exception as e:
            logger.warning("Could not update progress file | error=%s", e)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class EmailScraperPipeline:

    def __init__(self, output_path: Path, mailbox: str = "INBOX"):
        self.output_path = output_path
        self.mailbox      = mailbox
        self.parser       = MessageParser()
        self.resolver     = ThreadResolver()
        self.progress     = ProgressTracker(PROGRESS_FILE)

    def run(self) -> None:
        load_dotenv()
        host     = os.getenv("IMAP_HOST", "")
        addr     = os.getenv("EMAIL_ADDR", "")
        password = os.getenv("EMAIL_PASSWORD", "")

        if not all([host, addr, password]):
            logger.error("Missing IMAP credentials in .env (IMAP_HOST, EMAIL_ADDR, EMAIL_PASSWORD)")
            raise EnvironmentError("Missing required IMAP credentials")

        fetcher = ImapFetcher(host=host, email_addr=addr, password=password)

        parsed_emails: list[dict] = []
        fetch_failures = 0
        parse_failures = 0

        try:
            fetcher.connect()
            msg_ids = fetcher.fetch_all_message_ids(self.mailbox)

            seen_ids = self.progress.load_seen_ids()
            logger.info("Resuming run — %d messages already processed previously", len(seen_ids))

            for idx, msg_id in enumerate(msg_ids, start=1):
                raw = fetcher.fetch_raw_message(msg_id)
                if raw is None:
                    fetch_failures += 1
                    continue

                parsed = self.parser.parse(raw)
                if parsed is None:
                    parse_failures += 1
                    continue

                if parsed["id"] in seen_ids:
                    continue  # already processed in a prior run

                parsed_emails.append(parsed)
                self.progress.mark_seen(parsed["id"])

                if idx % 50 == 0:
                    logger.info("Progress: %d/%d messages fetched", idx, len(msg_ids))

        finally:
            fetcher.close()

        logger.info(
            "Fetch complete | fetched=%d fetch_failures=%d parse_failures=%d",
            len(parsed_emails), fetch_failures, parse_failures,
        )

        # Deduplicate by id (in case IMAP returns the same message twice)
        deduped = {}
        for e in parsed_emails:
            deduped[e["id"]] = e
        parsed_emails = list(deduped.values())

        resolved_emails = self.resolver.resolve(parsed_emails)

        self._write_output(resolved_emails)

    def _write_output(self, emails: list[dict]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        method_counts = {"references": 0, "in_reply_to": 0, "subject_fallback": 0, "original": 0}

        with open(self.output_path, "w", encoding="utf-8") as f:
            for e in emails:
                method_counts[e.get("thread_match_method", "original")] += 1
                record = {
                    "id":                  e["id"],
                    "subject":             e["subject"],
                    "body":                e["body"],
                    "from":                e["from"],
                    "to":                  e["to"],
                    "date":                e["date"],
                    "thread_id":           e["thread_id"],
                    "reply_to":            e["reply_to"],
                    "thread_match_method": e["thread_match_method"],
                }
                f.write(json.dumps(record) + "\n")

        logger.info(
            "Scraping complete | total=%d references=%d in_reply_to=%d "
            "subject_fallback=%d original=%d output=%s",
            len(emails),
            method_counts["references"], method_counts["in_reply_to"],
            method_counts["subject_fallback"], method_counts["original"],
            self.output_path,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = EmailScraperPipeline(
        output_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\raw\\emails_v4.jsonl"),
    )
    pipeline.run()