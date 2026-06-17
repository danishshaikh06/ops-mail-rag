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
# Regex patterns
# ---------------------------------------------------------------------------

# Request IDs: LPRQ-08-03-2025-48431, AERQ-10-03-2025-48489, etc.
REQUEST_ID_RE = re.compile(r"\b[A-Z]{2,4}RQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b")

# Flight numbers: OV3897, OV 3897, JAG1316
FLIGHT_NUMBER_RE = re.compile(r"\b([A-Z]{2})\s?(\d{3,4})\b")

# Aircraft registrations:
#   A4O-OCA (Oman Air format: letter + digit + letter - 3 letters)
#   P4-JAG  (Aruba format: letter + digit - 3 letters)
AIRCRAFT_REG_RE = re.compile(r"\b([A-Z]\d[A-Z]-[A-Z]{2,4}|[A-Z]\d-[A-Z]{2,4})\b")

# Signature anchor — same as cleaning.py so we find the block consistently
SIGNATURE_ANCHOR_RE = re.compile(
    r"(Thanks\s*&\s*Regards|Best\s+[Rr]egards|Regards\s*,?|Sincerely\s*,?)",
    re.IGNORECASE,
)

# System email detection (mirrors cleaning.py)
SYSTEM_SENDER_DOMAINS = {"ionos.com", "mailer-daemon"}
SYSTEM_SUBJECT_PREFIXES = ("welcome to mail", "daily report mailbox", "spam report")

# Known designations to identify the designation line in signatures
DESIGNATION_KEYWORDS = [
    "executive", "officer", "manager", "director", "engineer",
    "coordinator", "supervisor", "head", "senior", "junior",
    "operations", "assistant", "analyst", "controller",
]

# Known companies — longest first to prefer specific matches
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
# System email detection
# ---------------------------------------------------------------------------

def is_system_email(email: dict) -> bool:
    sender = (email.get("from") or [""])[0].lower()
    subject = (email.get("subject") or "").lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    if domain in SYSTEM_SENDER_DOMAINS:
        return True
    if any(subject.startswith(p) for p in SYSTEM_SUBJECT_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# ID extractors — search subject first, fall back to body
# ---------------------------------------------------------------------------

def extract_request_id(subject: str, body: str) -> str:
    """Extract first request ID (LPRQ, SRRQ, etc.) excluding AERQ (invoice/receipt IDs)."""
    for text in (subject, body):
        for m in REQUEST_ID_RE.finditer(text):
            if not m.group().startswith("AERQ"):
                return m.group()
    return ""


def extract_invoice_id(subject: str, body: str) -> str:
    """Extract AERQ-* ID from invoice emails."""
    subject_lower = subject.lower()
    if "invoice" not in subject_lower and "invoice" not in body.lower():
        return ""
    for text in (subject, body):
        m = re.search(r"\bAERQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b", text)
        if m:
            return m.group()
    return ""


def extract_receipt_id(subject: str, body: str) -> str:
    """Extract AERQ-* ID from payment receipt emails."""
    subject_lower = subject.lower()
    if "receipt" not in subject_lower and "receipt" not in body.lower():
        return ""
    for text in (subject, body):
        m = re.search(r"\bAERQ-\d{2}-\d{2}-\d{4}-\d{4,6}\b", text)
        if m:
            return m.group()
    return ""


def extract_permission_number(body: str) -> str:
    """
    Extract permission number mentioned explicitly in body.
    Pattern seen: 'Permission number must be mentioned under item 18'
    Actual number referenced in a separate line/context — extract the LPRQ ID
    that appears near the word 'permission number'.
    """
    match = re.search(
        r"[Pp]ermission\s+(?:number|no\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
        body,
    )
    if match:
        return match.group(1).strip()
    return ""


def extract_flight_numbers(subject: str, body: str) -> list[str]:
    """Extract unique flight numbers like OV3897 from subject and body."""
    found = set()
    for text in (subject, body):
        for m in FLIGHT_NUMBER_RE.finditer(text):
            # Normalise: remove space between prefix and number
            found.add(m.group(1) + m.group(2))
    return sorted(found)


def extract_aircraft_registrations(subject: str, body: str) -> list[str]:
    """Extract unique aircraft registrations like A4O-OCA, P4-JAG."""
    found = set()
    for text in (subject, body):
        for m in AIRCRAFT_REG_RE.finditer(text):
            found.add(m.group())
    return sorted(found)


# ---------------------------------------------------------------------------
# Signature extraction — name, company, designation
# ---------------------------------------------------------------------------

def extract_signature_fields(body: str) -> tuple[str, str, str]:
    """
    Extract sender_name, sender_company, sender_designation from body signature.

    Strategy:
    - Find signature anchor (Regards / Thanks & Regards / etc.)
    - Take up to 8 non-empty lines after anchor
    - Line 0 → candidate for sender_name (2-4 words, mixed case)
    - Remaining lines → scan for designation keywords and known companies
    """
    match = SIGNATURE_ANCHOR_RE.search(body)
    if not match:
        return "", "", ""

    anchor_and_after = body[match.start():]
    raw_lines = anchor_and_after.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Skip the anchor line, collect next 8 non-empty lines
    content_lines = [l.strip() for l in raw_lines[1:] if l.strip()][:8]

    if not content_lines:
        return "", "", ""

    # --- sender_name: first line, 2-4 words, not all-caps, not a designation ---
    sender_name = ""
    name_candidate = content_lines[0]
    words = name_candidate.split()
    is_reasonable_name = (
        2 <= len(words) <= 4
        and not name_candidate.isupper()
        and not any(kw in name_candidate.lower() for kw in DESIGNATION_KEYWORDS)
    )
    if is_reasonable_name:
        sender_name = name_candidate

    # --- sender_designation and sender_company: scan remaining lines ---
    sender_designation = ""
    sender_company = ""

    for line in content_lines[1:]:
        # Designation: short line containing a known designation keyword
        if not sender_designation and any(kw in line.lower() for kw in DESIGNATION_KEYWORDS):
            if len(line.split()) <= 6:  # designation lines are short
                sender_designation = line

        # Company: match against known companies list
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


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_metadata(email: dict) -> dict:
    email_id = email.get("id", "")
    subject  = email.get("subject") or ""
    body     = email.get("body") or ""
    system   = is_system_email(email)

    if system:
        sender_name = sender_company = sender_designation = ""
        request_id = invoice_id = receipt_id = permission_number = ""
        flight_numbers = []
        aircraft_registrations = []
    else:
        sender_name, sender_company, sender_designation = extract_signature_fields(body)
        request_id        = extract_request_id(subject, body)
        invoice_id        = extract_invoice_id(subject, body)
        receipt_id        = extract_receipt_id(subject, body)
        permission_number = extract_permission_number(body)
        flight_numbers    = extract_flight_numbers(subject, body)
        aircraft_registrations = extract_aircraft_registrations(subject, body)

    return {
        "email_id":              email_id,
        "subject":               subject,
        "sender_email":          (email.get("from") or [""])[0],
        "recipient_emails":      email.get("to") or [],
        "date":                  email.get("date", ""),
        "thread_id":             email.get("thread_id", ""),
        "reply_to":              email.get("reply_to", ""),
        "sender_name":           sender_name,
        "sender_company":        sender_company,
        "sender_designation":    sender_designation,
        "email_type":            "",   # Phase 2b
        "status":                "",   # Phase 2b
        "request_id":            request_id,
        "invoice_id":            invoice_id,
        "receipt_id":            receipt_id,
        "permission_number":     permission_number,
        "flight_numbers":        flight_numbers,
        "aircraft_registrations": aircraft_registrations,
        "is_system_email":       system,
    }


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def extract_all(input_path: Path, output_path: Path) -> None:
    logger.info("Starting metadata extraction | input=%s", input_path)
    total = 0
    system = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path, encoding="utf-8") as infile, \
         open(output_path, "w", encoding="utf-8") as outfile:
        for line in infile:
            line = line.strip()
            if not line:
                continue
            email = json.loads(line)
            metadata = extract_metadata(email)
            outfile.write(json.dumps(metadata) + "\n")

            total += 1
            if metadata["is_system_email"]:
                system += 1
                logger.debug("System email | id=%s", email.get("id"))

    logger.info(
        "Metadata extraction complete | total=%d system=%d output=%s",
        total, system, output_path,
    )


if __name__ == "__main__":
    input_path  = Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\raw\\emails.jsonl")
    output_path = Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\metadata\\email_metadata.jsonl")
    extract_all(input_path, output_path)