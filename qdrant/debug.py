import os
import imaplib
from email import message_from_bytes
from dotenv import load_dotenv

load_dotenv()
host     = os.getenv("IMAP_HOST", "")
addr     = os.getenv("EMAIL_ADDR", "")
password = os.getenv("EMAIL_PASSWORD", "")

target_message_id = "<10d401dcf349$2e7bcde0$8b7369a0$@smb-freight.com>"

conn = imaplib.IMAP4_SSL(host, 993)
conn.login(addr, password)
conn.select("INBOX", readonly=True)

status, data = conn.search(None, "ALL")
ids = data[0].split()

found = False
for msg_id in ids:
    status, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
    if status != "OK" or not msg_data or msg_data[0] is None:
        continue
    raw = msg_data[0][1]
    msg = message_from_bytes(raw)
    if msg.get("Message-ID", "").strip() == target_message_id:
        found = True
        print("FOUND MESSAGE")
        print("is_multipart:", msg.is_multipart())
        print()
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                payload = part.get_payload(decode=True)
                size = len(payload) if payload else 0
                print(f"  part: content_type={content_type} disposition={disposition!r} payload_size={size}")
        else:
            payload = msg.get_payload(decode=True)
            print("single part payload size:", len(payload) if payload else 0)
        break

if not found:
    print("Message not found in mailbox (may have been moved/deleted since last scrape)")

conn.close()
conn.logout()