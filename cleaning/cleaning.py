import re
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logger setup — stream + file handlers, shared log file for the pipeline
# ---------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cleaning")
    if logger.handlers:
        return logger  # already configured, avoid duplicate handlers on re-import

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stream handler — INFO and above to console
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    # File handler — DEBUG and above to logs/pipeline.log
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
# Patterns — ordered by specificity, compiled once at module level
# ---------------------------------------------------------------------------

# Greeting: "Dear X," or "Dear X ," on its own line (with optional trailing space)
GREETING_RE = re.compile(r"^Dear\s+.{1,60}?\s*,?\s*$", re.MULTILINE)

# Signature anchor: the closing salutation line that starts the signature block
# Everything from this line to end of string is stripped
SIGNATURE_ANCHOR_RE = re.compile(
    r"(Thanks\s*&\s*Regards|Best\s+[Rr]egards|Regards\s*,|Sincerely\s*,?).*",
    re.DOTALL | re.IGNORECASE,
)

# RAK DCA / generic confidentiality block — anchored on its known opening phrase
CONFIDENTIALITY_RE = re.compile(
    r"This\s+E[\-\s]?Mail\s+and\s+any\s+files\s+transmitted.*",
    re.DOTALL | re.IGNORECASE,
)

# "think before we print" trailer (appears after confidentiality block on RAK emails)
PRINT_REMINDER_RE = re.compile(
    r"We\s+have\s+a\s+responsibility\s+to\s+the\s+environment.*",
    re.DOTALL | re.IGNORECASE,
)

# CID image references: [cid:xxxx]
CID_RE = re.compile(r"\[cid:[^\]]+\]", re.IGNORECASE)

# "Get Outlook for iOS / Android" footer variants
OUTLOOK_FOOTER_RE = re.compile(r"Get\s+Outlook\s+for\s+\w+.*", re.DOTALL | re.IGNORECASE)

# "Sent from my iPhone / iPad / Android" one-liner
SENT_FROM_RE = re.compile(r"Sent\s+from\s+my\s+\w[\w\s]{0,20}", re.IGNORECASE)

# Social media link blocks — lines that are just platform names or profile URLs
SOCIAL_MEDIA_RE = re.compile(
    r"^.*(linkedin|twitter|facebook|instagram|youtube).*$",
    re.MULTILINE | re.IGNORECASE,
)

# Marketing taglines (aviation specific seen in data)
MARKETING_RE = re.compile(
    r"Asia.s\s+Youngest\s+Aircraft\s+Fleet.*",
    re.DOTALL | re.IGNORECASE,
)

# Encoding artifact: Â followed by optional non-breaking space (from \xc2\xa0 mis-decode)
ENCODING_ARTIFACT_RE = re.compile(r"Â\xa0|Â |Â")

# Feedback / survey nudge lines common in RAK DCA emails
FEEDBACK_RE = re.compile(
    r"(To\s+serve\s+you\s+better|please\s+complete\s+this\s+survey|click\s+here\s+for\s+valuable\s+feedback|provide\s+your\s+valuable\s+feedback).*",
    re.DOTALL | re.IGNORECASE,
)

# Hyperlinks left as plain text after HTML stripping: http(s)://...
URL_RE = re.compile(r"https?://\S+")


# ---------------------------------------------------------------------------
# System email detection
# ---------------------------------------------------------------------------

SYSTEM_SENDER_DOMAINS = {"ionos.com", "mailer-daemon"}
SYSTEM_SUBJECT_PREFIXES = ("welcome to mail", "daily report mailbox", "spam report")


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
# Core cleaning steps — each takes a string, returns a string
# ---------------------------------------------------------------------------

def remove_greeting(text: str) -> str:
    return GREETING_RE.sub("", text)


def remove_signature(text: str) -> str:
    return SIGNATURE_ANCHOR_RE.sub("", text)


def remove_confidentiality(text: str) -> str:
    text = CONFIDENTIALITY_RE.sub("", text)
    text = PRINT_REMINDER_RE.sub("", text)
    return text


def remove_feedback_lines(text: str) -> str:
    return FEEDBACK_RE.sub("", text)


def remove_cid_refs(text: str) -> str:
    return CID_RE.sub("", text)


def remove_footers(text: str) -> str:
    text = OUTLOOK_FOOTER_RE.sub("", text)
    text = SENT_FROM_RE.sub("", text)
    return text


def remove_social_media(text: str) -> str:
    return SOCIAL_MEDIA_RE.sub("", text)


def remove_marketing(text: str) -> str:
    return MARKETING_RE.sub("", text)


def remove_urls(text: str) -> str:
    return URL_RE.sub("", text)


def fix_encoding(text: str) -> str:
    return ENCODING_ARTIFACT_RE.sub(" ", text)


def normalize_whitespace(text: str) -> str:
    # Collapse \r, strip leading/trailing per line, collapse consecutive blank lines
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    cleaned = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Main clean function
# ---------------------------------------------------------------------------

def clean_body(body: str) -> str:
    body = fix_encoding(body)
    body = remove_cid_refs(body)
    body = remove_confidentiality(body)
    body = remove_feedback_lines(body)
    body = remove_marketing(body)
    body = remove_social_media(body)
    body = remove_footers(body)
    body = remove_urls(body)
    body = remove_greeting(body)
    body = remove_signature(body)   # must come after greeting so anchor is reliable
    body = normalize_whitespace(body)
    return body


def clean_email(email: dict) -> dict:
    result = dict(email)  # shallow copy, preserve all original fields
    if is_system_email(email):
        result["body_clean"] = ""
        result["is_system_email"] = True
    else:
        result["body_clean"] = clean_body(email.get("body") or "")
        result["is_system_email"] = False
    return result


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def clean_all(input_path: Path, output_path: Path) -> None:
    logger.info("Starting cleaning pipeline | input=%s", input_path)
    total = 0
    system = 0
    empty_after_clean = 0

    with open(input_path, encoding="utf-8") as infile, open(output_path, "w", encoding="utf-8") as outfile:
        for line in infile:
            line = line.strip()
            if not line:
                continue
            email = json.loads(line)
            cleaned = clean_email(email)
            outfile.write(json.dumps(cleaned) + "\n")

            total += 1
            if cleaned["is_system_email"]:
                system += 1
                logger.debug("System email skipped | id=%s", email.get("id"))
            elif not cleaned["body_clean"]:
                empty_after_clean += 1
                logger.debug("Empty body after clean | id=%s", email.get("id"))

    logger.info(
        "Cleaning complete | total=%d system=%d empty_after_clean=%d output=%s",
        total, system, empty_after_clean, output_path,
    )

if __name__ == "__main__":
    input_path = Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\raw\\emails.jsonl")
    output_path = Path("C:\\Users\\Omen\\Downloads\\RAG PIPELINE\\data\\cleaned\\cleaned_emails.jsonl")
    clean_all(input_path, output_path)