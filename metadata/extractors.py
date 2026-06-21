import re
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("metadata_extraction")
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

REQUEST_ID_RE   = re.compile(r"\b[A-Z]{2,4}RQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b")
FLIGHT_NUM_RE   = re.compile(r"\b([A-Z]{2})\s?(\d{3,4})\b")
AIRCRAFT_REG_RE = re.compile(r"\b([A-Z]\d[A-Z]-[A-Z]{2,4}|[A-Z]\d-[A-Z]{2,4})\b")

SIGNATURE_ANCHOR_RE = re.compile(
    r"(Thanks\s*&\s*Regards|Best\s+[Rr]egards|Regards\s*,?|Sincerely\s*,?)",
    re.IGNORECASE,
)

SYSTEM_SENDER_DOMAINS   = {"ionos.com", "mailer-daemon"}
SYSTEM_SUBJECT_PREFIXES = ("welcome to mail", "daily report mailbox", "spam report")

DESIGNATION_KEYWORDS = [
    "executive", "officer", "manager", "director", "engineer",
    "coordinator", "supervisor", "head", "senior", "junior",
    "operations", "assistant", "analyst", "controller",
]

KNOWN_COMPANIES = [
    "Mumbai International Airport Pvt Ltd",
    "Mumbai International Airport Ltd",
    "Mumbai International Airport",
    "Airport Operations Control Centre",
    "SMB Freight FZE",
    "SMB Freight",
    "SMB-F",
    "Department of Civil Aviation",
    "Adani Airports",
    "Adani Airport",
    "RAKDCA",
    "RAK DCA",
    "SalamAir",
    "Omega Air",
    "AOCC",
]
KNOWN_COMPANIES.sort(key=len, reverse=True)


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class MetadataExtractionPipeline:

    def __init__(self, input_path: Path, output_path: Path):
        self.input_path  = input_path
        self.output_path = output_path

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logger.info("Starting metadata extraction | input=%s", self.input_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        total = system = 0
        with open(self.input_path, encoding="utf-8") as infile, \
             open(self.output_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                try:
                    line = line.strip()
                    if not line:
                        continue
                    email    = json.loads(line)
                    metadata = self._extract(email)
                    outfile.write(json.dumps(metadata) + "\n")
                    total += 1
                    if metadata["is_system_email"]:
                        system += 1
                        logger.debug("System email | id=%s", email.get("id"))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSON line")
                    continue

        logger.info(
            "Metadata extraction complete | total=%d system=%d output=%s",
            total, system, self.output_path,
        )

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _is_system_email(self, email: dict) -> bool:
        sender  = (email.get("from") or [""])[0].lower()
        subject = (email.get("subject") or "").lower()
        domain  = sender.split("@")[-1] if "@" in sender else ""
        if domain in SYSTEM_SENDER_DOMAINS:
            return True
        if any(subject.startswith(p) for p in SYSTEM_SUBJECT_PREFIXES):
            return True
        return False

    def _extract(self, email: dict) -> dict:
        email_id = email.get("id", "")
        subject  = email.get("subject") or ""
        body     = email.get("body") or ""
        system   = self._is_system_email(email)

        if system:
            sender_name = sender_company = sender_designation = ""
            request_id = invoice_id = receipt_id = permission_number = ""
            flight_numbers = []
            aircraft_registrations = []
        else:
            sender_name, sender_company, sender_designation = self._extract_signature_fields(body)
            request_id             = self._extract_request_id(subject, body)
            invoice_id             = self._extract_invoice_id(subject, body)
            receipt_id             = self._extract_receipt_id(subject, body)
            permission_number      = self._extract_permission_number(body)
            flight_numbers         = self._extract_flight_numbers(subject, body)
            aircraft_registrations = self._extract_aircraft_registrations(subject, body)

        return {
            "email_id":               email_id,
            "subject":                subject,
            "sender_email":           (email.get("from") or [""])[0],
            "recipient_emails":       email.get("to") or [],
            "date":                   email.get("date", ""),
            "thread_id":              email.get("thread_id", ""),
            "reply_to":               email.get("reply_to", ""),
            "sender_name":            sender_name,
            "sender_company":         sender_company,
            "sender_designation":     sender_designation,
            "email_type":             "",   # Phase 2b
            "status":                 "",   # Phase 2b
            "request_id":             request_id,
            "invoice_id":             invoice_id,
            "receipt_id":             receipt_id,
            "permission_number":      permission_number,
            "flight_numbers":         flight_numbers,
            "aircraft_registrations": aircraft_registrations,
            "is_system_email":        system,
        }

    def _extract_signature_fields(self, body: str) -> tuple[str, str, str]:
        match = SIGNATURE_ANCHOR_RE.search(body)
        if not match:
            return "", "", ""

        anchor_and_after = body[match.start():]
        raw_lines    = anchor_and_after.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        content_lines = [l.strip() for l in raw_lines[1:] if l.strip()][:8]

        if not content_lines:
            return "", "", ""

        # sender_name: first line, 2-4 words, not all-caps, not a designation
        sender_name = ""
        name_candidate = content_lines[0]
        words = name_candidate.split()
        is_name = (
            2 <= len(words) <= 4
            and not name_candidate.isupper()
            and not any(kw in name_candidate.lower() for kw in DESIGNATION_KEYWORDS)
        )
        if is_name:
            sender_name = name_candidate

        sender_designation = ""
        sender_company     = ""
        for line in content_lines[1:]:
            if not sender_designation and any(kw in line.lower() for kw in DESIGNATION_KEYWORDS):
                if len(line.split()) <= 6:
                    sender_designation = line
            if not sender_company:
                for company in KNOWN_COMPANIES:
                    if company.lower() in line.lower():
                        sender_company = company
                        break
            if sender_designation and sender_company:
                break

        logger.debug(
            "Signature extracted | name=%r designation=%r company=%r",
            sender_name, sender_designation, sender_company,
        )
        return sender_name, sender_company, sender_designation

    def _extract_request_id(self, subject: str, body: str) -> str:
        for text in (subject, body):
            for m in REQUEST_ID_RE.finditer(text):
                if not m.group().startswith("AERQ"):
                    return m.group()
        return ""

    def _extract_invoice_id(self, subject: str, body: str) -> str:
        if "invoice" not in subject.lower() and "invoice" not in body.lower():
            return ""
        for text in (subject, body):
            m = re.search(r"\bAERQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b", text)
            if m:
                return m.group()
        return ""

    def _extract_receipt_id(self, subject: str, body: str) -> str:
        if "receipt" not in subject.lower() and "receipt" not in body.lower():
            return ""
        for text in (subject, body):
            m = re.search(r"\bAERQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b", text)
            if m:
                return m.group()
        return ""

    def _extract_permission_number(self, body: str) -> str:
        m = re.search(
            r"[Pp]ermission\s+(?:number|no\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
            body,
        )
        return m.group(1).strip() if m else ""

    def _extract_flight_numbers(self, subject: str, body: str) -> list[str]:
        found = set()
        for text in (subject, body):
            for m in FLIGHT_NUM_RE.finditer(text):
                found.add(m.group(1) + m.group(2))
        return sorted(found)

    def _extract_aircraft_registrations(self, subject: str, body: str) -> list[str]:
        found = set()
        for text in (subject, body):
            for m in AIRCRAFT_REG_RE.finditer(text):
                found.add(m.group())
        return sorted(found)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pipeline = MetadataExtractionPipeline(
        input_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\raw\\emails_v4.jsonl"),
        output_path=Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\metadata\\email_metadata_v4.jsonl"),
    )
    pipeline.run()