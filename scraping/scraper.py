"""
Production IMAP Email Scraper
─────────────────────────────
Scrapes emails and saves to JSONL. Resumable across runs.

Output schema per record:
    id        – stable Message-ID (deduplication)
    subject   – decoded subject line
    body      – plain text, HTML-stripped, reply-chain removed
    from      – sender address
    to        – recipient(s)
    date      – ISO 8601 timestamp
    thread_id – root Message-ID of the conversation
    reply_to  – direct parent Message-ID (empty = original email)

Setup:
    pip install python-dotenv beautifulsoup4
    cp .env.example .env  →  fill in credentials
    python email_scraper.py
"""

import email.message
import imaplib
import json
import logging
import os
import re
import socket
import time
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

IMAP_HOST     = os.environ["IMAP_HOST"]
IMAP_PORT     = int(os.getenv("IMAP_PORT", 993))
EMAIL_ADDR    = os.environ["EMAIL_ADDR"]
PASSWORD      = os.environ["EMAIL_PASSWORD"]
MAILBOX       = os.getenv("MAILBOX", "INBOX")
OUTPUT_FILE   = Path(os.getenv("OUTPUT_FILE", "emails.jsonl"))
PROGRESS_FILE = OUTPUT_FILE.with_suffix(".progress")
RETRY_LIMIT   = 3
RETRY_DELAY   = 5   # seconds between retries
SOCKET_TIMEOUT = 30  # seconds — kills stalled connections

# ── Reply-chain strip pattern ─────────────────────────────────────────────────
REPLY_RE = re.compile(
    r"(-{3,}.*?original message.*?-{3,}|on .{10,80} wrote:|from:.*?sent:.*?to:.*?subject:)",
    re.IGNORECASE | re.DOTALL,
)

# ─────────────────────────────────────────────────────────────────────────────

def decode_str(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(
        p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, c in decode_header(value)
    ).strip()


def parse_date(value: str | None) -> str:
    try:
        return parsedate_to_datetime(value).isoformat() if value else ""
    except Exception:
        return value or ""


def parse_addresses(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr for _, addr in (parseaddr(a.strip()) for a in value.split(",")) if addr]


def extract_body(msg: email.message.Message) -> str:
    plain = html = ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get("Content-Disposition", "").lower().startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        ct = part.get_content_type()
        if ct == "text/plain" and not plain:
            plain = text
        elif ct == "text/html" and not html:
            html = text

    body = plain or (BeautifulSoup(html, "html.parser").get_text("\n") if html else "")
    return REPLY_RE.split(body)[0].strip()


def resolve_thread(msg: email.message.Message, msg_id: str) -> tuple[str, str]:
    reply_to   = decode_str(msg.get("In-Reply-To")).strip()
    references = decode_str(msg.get("References")).split()
    thread_id  = references[0].strip() if references else (reply_to or msg_id)
    return thread_id, reply_to


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def connect() -> imaplib.IMAP4_SSL:
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            # Socket-level timeout so stalled connections fail fast
            socket.setdefaulttimeout(SOCKET_TIMEOUT)
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            mail.login(EMAIL_ADDR, PASSWORD)
            mail.select(MAILBOX, readonly=True)
            log.info("Connected to %s/%s", IMAP_HOST, MAILBOX)
            return mail
        except Exception as exc:
            log.warning("Connect attempt %d/%d: %s", attempt, RETRY_LIMIT, exc)
            if attempt < RETRY_LIMIT:
                time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Could not connect after {RETRY_LIMIT} attempts")


def fetch_msg(mail: imaplib.IMAP4_SSL, eid: bytes) -> tuple[imaplib.IMAP4_SSL, email.message.Message | None]:
    """
    Fetch using BODY.PEEK[] — does not mark emails as read,
    skips downloading large attachments, significantly faster than RFC822.
    Returns updated mail handle + parsed message (or None on failure).
    """
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            _, data = mail.fetch(eid, "(BODY.PEEK[])")
            return mail, email.message_from_bytes(data[0][1])
        except Exception as exc:
            log.warning("Fetch %s attempt %d/%d: %s", eid.decode(), attempt, RETRY_LIMIT, exc)
            if attempt < RETRY_LIMIT:
                time.sleep(RETRY_DELAY)
                try:
                    mail = connect()
                except RuntimeError:
                    pass
    return mail, None


# ── Progress tracking ─────────────────────────────────────────────────────────

def load_progress() -> set[str]:
    return set(PROGRESS_FILE.read_text().splitlines()) if PROGRESS_FILE.exists() else set()


def save_progress(seen: set[str]) -> None:
    PROGRESS_FILE.write_text("\n".join(seen))


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape() -> None:
    seen = load_progress()
    log.info("Resuming — %d already scraped", len(seen))

    mail = connect()
    _, data = mail.search(None, "ALL")
    all_ids = data[0].split()
    pending = [e for e in all_ids if e.decode() not in seen]
    log.info("%d total  |  %d pending", len(all_ids), len(pending))

    scraped = 0
    out = OUTPUT_FILE.open("a", encoding="utf-8")

    try:
        for eid in pending:
            mail, msg = fetch_msg(mail, eid)
            if msg is None:
                log.error("Skipping %s — fetch failed", eid.decode())
                continue

            msg_id             = decode_str(msg.get("Message-ID")).strip() or eid.decode()
            thread_id, reply_to = resolve_thread(msg, msg_id)

            record = {
                "id":        msg_id,
                "subject":   decode_str(msg.get("Subject")),
                "body":      extract_body(msg),
                "from":      parse_addresses(msg.get("From")),
                "to":        parse_addresses(msg.get("To")),
                "date":      parse_date(msg.get("Date")),
                "thread_id": thread_id,
                "reply_to":  reply_to,
            }

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            seen.add(eid.decode())
            scraped += 1

            if scraped % 50 == 0:
                save_progress(seen)
                log.info("  %d / %d", scraped, len(pending))

    finally:
        out.close()
        save_progress(seen)
        try:
            mail.logout()
        except Exception:
            pass

    log.info("Done — %d new records → %s", scraped, OUTPUT_FILE)


if __name__ == "__main__":
    scrape()