import re
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cleaning")
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
# Patterns — compiled once at module level
# ---------------------------------------------------------------------------

GREETING_RE = re.compile(r"^Dear\s+.{1,60}?\s*,?\s*$", re.MULTILINE)

SIGNATURE_ANCHOR_RE = re.compile(
    r"(Thanks\s*&\s*Regards|Best\s+[Rr]egards|Regards\s*,?|Sincerely\s*,?).*",
    re.DOTALL | re.IGNORECASE,
)

CONFIDENTIALITY_RE = re.compile(
    r"This\s+E[\-\s]?Mail\s+and\s+any\s+files\s+transmitted.*",
    re.DOTALL | re.IGNORECASE,
)

PRINT_REMINDER_RE = re.compile(
    r"We\s+have\s+a\s+responsibility\s+to\s+the\s+environment.*",
    re.DOTALL | re.IGNORECASE,
)

CID_RE             = re.compile(r"\[cid:[^\]]+\]", re.IGNORECASE)
OUTLOOK_FOOTER_RE  = re.compile(r"Get\s+Outlook\s+for\s+\w+.*", re.DOTALL | re.IGNORECASE)
SENT_FROM_RE       = re.compile(r"Sent\s+from\s+my\s+\w[\w\s]{0,20}", re.IGNORECASE)
SOCIAL_MEDIA_RE    = re.compile(r"^.*(linkedin|twitter|facebook|instagram|youtube).*$", re.MULTILINE | re.IGNORECASE)
MARKETING_RE       = re.compile(r"Asia.s\s+Youngest\s+Aircraft\s+Fleet.*", re.DOTALL | re.IGNORECASE)
ENCODING_RE        = re.compile(r"Â\xa0|Â |Â")
FEEDBACK_RE        = re.compile(
    r"(To\s+serve\s+you\s+better|please\s+complete\s+this\s+survey|click\s+here\s+for\s+valuable\s+feedback|provide\s+your\s+valuable\s+feedback).*",
    re.DOTALL | re.IGNORECASE,
)
URL_RE             = re.compile(r"https?://\S+")

SYSTEM_SENDER_DOMAINS  = {"ionos.com", "mailer-daemon"}
SYSTEM_SUBJECT_PREFIXES = ("welcome to mail", "daily report mailbox", "spam report")


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class EmailCleaningPipeline:

    def __init__(self, input_path: Path, output_path: Path):
        self.input_path  = input_path
        self.output_path = output_path

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info("Starting cleaning pipeline | input=%s", self.input_path)

        emails = self._load(self.input_path)
        before = len(emails)

        emails = self._deduplicate(emails)
        after  = len(emails)
        if before != after:
            logger.info("Deduplication removed %d records", before - after)

        total = system = empty = 0
        with open(self.output_path, "w", encoding="utf-8") as outfile:
            for email in emails:
                cleaned = self._process(email)
                outfile.write(json.dumps(cleaned) + "\n")
                total += 1
                if cleaned["is_system_email"]:
                    system += 1
                    logger.debug("System email | id=%s", email.get("id"))
                elif not cleaned["body_clean"]:
                    empty += 1
                    logger.debug("Empty after clean | id=%s", email.get("id"))

        logger.info(
            "Cleaning complete | total=%d system=%d empty=%d output=%s",
            total, system, empty, self.output_path,
        )

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _load(self, path: Path) -> list[dict]:
        emails = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    line = line.strip()
                    if line:
                        emails.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSON line")
                    continue
        return emails

    def _deduplicate(self, emails: list[dict]) -> list[dict]:
        seen   = set()
        unique = []
        for email in emails:
            eid = email.get("id")
            if eid not in seen:
                seen.add(eid)
                unique.append(email)
        return unique

    def _process(self, email: dict) -> dict:
        result = dict(email)
        result = self._normalize_addresses(result)
        if self._is_system_email(email):
            result["body_clean"]     = ""
            result["is_system_email"] = True
        else:
            result["body_clean"]     = self._clean_body(email.get("body") or "")
            result["is_system_email"] = False
        return result

    def _normalize_addresses(self, email: dict) -> dict:
        """Lowercase and strip all email addresses."""
        email["from"] = [addr.lower().strip() for addr in (email.get("from") or [])]
        email["to"]   = [addr.lower().strip() for addr in (email.get("to")   or [])]
        return email

    def _is_system_email(self, email: dict) -> bool:
        sender  = (email.get("from") or [""])[0].lower()
        subject = (email.get("subject") or "").lower()
        domain  = sender.split("@")[-1] if "@" in sender else ""
        if domain in SYSTEM_SENDER_DOMAINS:
            return True
        if any(subject.startswith(p) for p in SYSTEM_SUBJECT_PREFIXES):
            return True
        return False

    def _clean_body(self, body: str) -> str:
        body = ENCODING_RE.sub(" ", body)
        body = CID_RE.sub("", body)
        body = CONFIDENTIALITY_RE.sub("", body)
        body = PRINT_REMINDER_RE.sub("", body)
        body = FEEDBACK_RE.sub("", body)
        body = MARKETING_RE.sub("", body)
        body = SOCIAL_MEDIA_RE.sub("", body)
        body = OUTLOOK_FOOTER_RE.sub("", body)
        body = SENT_FROM_RE.sub("", body)
        body = URL_RE.sub("", body)
        body = GREETING_RE.sub("", body)
        body = SIGNATURE_ANCHOR_RE.sub("", body)
        body = self._normalize_whitespace(body)
        return body

    def _normalize_whitespace(self, text: str) -> str:
        text  = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line.strip() for line in text.split("\n")]
        cleaned, prev_blank = [], False
        for line in lines:
            is_blank = line == ""
            if is_blank and prev_blank:
                continue
            cleaned.append(line)
            prev_blank = is_blank
        return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = EmailCleaningPipeline(
        input_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\raw\\emails_v4.jsonl"),
        output_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\cleaned\\cleaned_emails_v4.jsonl"),
    )
    pipeline.run()