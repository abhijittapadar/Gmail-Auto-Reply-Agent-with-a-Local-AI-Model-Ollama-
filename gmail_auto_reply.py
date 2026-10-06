#!/usr/bin/env python3
"""
Gmail API auto-reply bot powered by a LOCAL AI model (Ollama).

Flow: poll Gmail API for unread inbox mail -> filter -> local model writes reply
      -> send via Gmail API in the same thread -> label + mark read.

Setup:
    pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib requests
    ollama pull llama3.2
    place credentials.json (OAuth Desktop client) next to this script
    python gmail_auto_reply.py       # first run opens a browser to authorize
"""

import base64
import logging
import os
import re
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from email.utils import parseaddr

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ----------------------------- CONFIG ---------------------------------------
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]   # read + label + send
CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS", "credentials.json")
TOKEN_FILE = os.getenv("GMAIL_TOKEN", "token.json")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
MAX_REPLIES_PER_SENDER_PER_DAY = int(os.getenv("MAX_REPLIES_PER_SENDER_PER_DAY", "3"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"    # true = print only, don't send
ALLOWED_SENDERS = {s.strip().lower() for s in os.getenv("ALLOWED_SENDERS", "").split(",") if s.strip()}
# Optional: also allow whole domains, e.g. "yourcompany.com,clientcompany.com"
ALLOWED_DOMAINS = {d.strip().lower().lstrip("@") for d in os.getenv("ALLOWED_DOMAINS", "").split(",") if d.strip()}
LABEL_NAME = "AI-Replied"

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful email assistant replying on behalf of the mailbox owner. "
    "Write a concise, polite, professional reply to the email below. "
    "Do not invent facts, promises, prices or meeting times. "
    "If you can't answer, say the owner will follow up personally. "
    "Output ONLY the reply body, no subject line, no signature placeholder.",
)
SIGNATURE = os.getenv("SIGNATURE", "\n\n-- \nThis reply was drafted by an automated assistant.")
# -----------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gmail-autoreply")

_sent_log = defaultdict(deque)   # sender -> timestamps of replies (in-memory rate limit)


# ------------------------- Gmail auth & helpers ------------------------------
def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_or_create_label(service, name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for lb in labels:
        if lb["name"].lower() == name.lower():
            return lb["id"]
    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return created["id"]


def header(msg: dict, name: str) -> str:
    for h in msg["payload"].get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def extract_text(payload: dict) -> str:
    """Walk the MIME tree; prefer text/plain, fall back to stripped HTML."""
    plain, html = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime == "text/plain" and data:
            plain.append(_b64(data))
        elif mime == "text/html" and data:
            html.append(re.sub(r"<[^>]+>", " ", _b64(data)))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return "\n".join(plain) if plain else "\n".join(html)


def strip_quoted(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith(">"):
            continue
        if re.match(r"^On .+ wrote:$", line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()[:4000]


def should_reply(msg: dict, sender: str, my_address: str) -> tuple[bool, str]:
    if sender == my_address.lower():
        return False, "from self"
    if ALLOWED_SENDERS or ALLOWED_DOMAINS:
        domain = sender.rsplit("@", 1)[-1]
        if sender not in ALLOWED_SENDERS and domain not in ALLOWED_DOMAINS:
            return False, "sender/domain not in allowlist"
    if re.search(r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notifications?@)", sender):
        return False, "automated sender address"
    if header(msg, "Auto-Submitted").lower() not in ("", "no"):
        return False, "Auto-Submitted header"
    if header(msg, "Precedence").lower() in {"bulk", "list", "junk"}:
        return False, "bulk/list precedence"
    if header(msg, "List-Id") or header(msg, "List-Unsubscribe"):
        return False, "mailing list"
    if header(msg, "X-Auto-Response-Suppress"):
        return False, "auto-response suppressed"

    now = time.time()
    q = _sent_log[sender]
    while q and now - q[0] > 86400:
        q.popleft()
    if len(q) >= MAX_REPLIES_PER_SENDER_PER_DAY:
        return False, "daily reply limit reached for sender"
    return True, "ok"


# ------------------------- local AI ------------------------------------------
def generate_reply(sender: str, subject: str, body: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"From: {sender}\nSubject: {subject}\n\n{body}"},
        ],
        "options": {"temperature": 0.4},
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=300)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


# ------------------------- sending -------------------------------------------
def send_reply(service, original: dict, to_addr: str, subject: str, reply_body: str, my_address: str):
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["From"] = my_address
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["Auto-Submitted"] = "auto-replied"        # stops reply loops with other bots
    msg["X-Auto-Response-Suppress"] = "All"
    orig_id = header(original, "Message-ID") or header(original, "Message-Id")
    if orig_id:                                    # needed for correct threading
        msg["In-Reply-To"] = orig_id
        msg["References"] = f"{header(original, 'References')} {orig_id}".strip()
    msg.set_content(reply_body + SIGNATURE)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": original["threadId"]}
    ).execute()


# ------------------------- main loop -----------------------------------------
def process_inbox(service, my_address: str, label_id: str):
    query = f"is:unread in:inbox -label:{LABEL_NAME} -category:promotions -category:social -category:forums"
    resp = service.users().messages().list(userId="me", q=query, maxResults=20).execute()

    for ref in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        _, sender = parseaddr(header(msg, "From"))
        sender = sender.lower()
        subject = header(msg, "Subject") or "(no subject)"
        done = {"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]}

        ok, reason = should_reply(msg, sender, my_address)
        if not ok:
            log.info("Skip %s | %s (%s)", sender, subject, reason)
            # label so we don't re-check it every cycle; leave UNREAD for the human
            service.users().messages().modify(userId="me", id=ref["id"], body={"addLabelIds": [label_id]}).execute()
            continue

        body = strip_quoted(extract_text(msg["payload"]))
        if not body:
            log.info("Skip %s | empty body", sender)
            service.users().messages().modify(userId="me", id=ref["id"], body={"addLabelIds": [label_id]}).execute()
            continue

        try:
            reply = generate_reply(sender, subject, body)
        except Exception as e:
            log.error("AI generation failed: %s (retry next cycle)", e)
            continue

        if DRY_RUN:
            log.info("[DRY RUN] Would reply to %s:\n%s\n", sender, reply)
            continue   # not labeled, so dry-run will show it again next cycle

        try:
            send_reply(service, msg, sender, subject, reply, my_address)
            _sent_log[sender].append(time.time())
            service.users().messages().modify(userId="me", id=ref["id"], body=done).execute()
            log.info("Replied to %s | %s", sender, subject)
        except HttpError as e:
            log.error("Gmail send failed: %s (retry next cycle)", e)


def main():
    service = get_service()
    my_address = service.users().getProfile(userId="me").execute()["emailAddress"]
    label_id = get_or_create_label(service, LABEL_NAME)
    log.info("Authorized as %s | model=%s | dry_run=%s | poll=%ss", my_address, OLLAMA_MODEL, DRY_RUN, POLL_SECONDS)

    while True:
        try:
            process_inbox(service, my_address, label_id)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.error("Cycle error: %s", e)
        try:
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break


if __name__ == "__main__":
    main()