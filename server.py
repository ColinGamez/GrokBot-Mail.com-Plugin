"""Mail.com MCP server for GrokBot (IMAP + SMTP wrapper).

mail.com exposes no public REST API, so this wraps the standard
mailbox protocols GrokBot can use as tools:

  IMAP: imap.mail.com:993 (SSL)
  SMTP: smtp.mail.com:587 (STARTTLS) or :465 (SSL)

Setup in mail.com first:
  Email -> Settings -> POP3 & IMAP -> Enable access via POP3 and IMAP

Transports:
  stdio (default, for GrokBot cloud `npx`/`uvx`-style stdio servers)
  streamable-http (self-host, then add as Custom connector URL)

Env:
  MAILCOM_EMAIL, MAILCOM_PASSWORD (required)
  IMAP_HOST=imap.mail.com, IMAP_PORT=993
  SMTP_HOST=smtp.mail.com, SMTP_PORT=587, SMTP_STARTTLS=true
  MCP_TRANSPORT=stdio|streamable-http, MCP_HOST=127.0.0.1, MCP_PORT=8000
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import smtplib
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv

    load_dotenv()  # local `mcp dev` convenience; GrokBot uses env vars instead
except ImportError:
    pass

try:  # mcp>=2.x renamed FastMCP -> MCPServer
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("mailcom")
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("mailcom")



def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _cfg() -> dict:
    email_addr = _env("MAILCOM_EMAIL")
    password = _env("MAILCOM_PASSWORD")
    if not email_addr or not password:
        raise RuntimeError(
            "MAILCOM_EMAIL and MAILCOM_PASSWORD env vars are required. "
            "Set them on the GrokBot custom server entry (env vars, not chat)."
        )
    return {
        "email": email_addr,
        "password": password,
        "imap_host": _env("IMAP_HOST", "imap.mail.com"),
        "imap_port": int(_env("IMAP_PORT", "993")),
        "smtp_host": _env("SMTP_HOST", "smtp.mail.com"),
        "smtp_port": int(_env("SMTP_PORT", "587")),
        "smtp_starttls": _env("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes"),
    }


def _imap() -> imaplib.IMAP4_SSL:
    c = _cfg()
    conn = imaplib.IMAP4_SSL(c["imap_host"], c["imap_port"])
    conn.login(c["email"], c["password"])
    return conn


def _decode_header(value) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    out = []
    for text, charset in parts:
        if isinstance(text, bytes):
            out.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _message_text(msg: Message, max_chars: int) -> tuple[str, str | None]:
    """Return (plain_text_truncated, html_truncated_or_None)."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            ctype = part.get_content_type()
            try:
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
            if ctype == "text/plain":
                plain_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)
        except Exception:
            pass
    plain = "\n".join(plain_parts)[:max_chars]
    html = ("\n".join(html_parts)[:max_chars]) if html_parts else None
    return plain, html


def _attachments_meta(msg: Message) -> list[dict]:
    att: list[dict] = []
    if not msg.is_multipart():
        return att
    for part in msg.walk():
        disp = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if "attachment" in disp or filename:
            payload = part.get_payload(decode=True) or b""
            att.append(
                {
                    "filename": _decode_header(filename or "unnamed"),
                    "content_type": part.get_content_type(),
                    "size_bytes": len(payload),
                }
            )
    return att


def _extract_header_bytes(fetch_data) -> bytes | None:
    """Pull the RFC822.HEADER bytes out of an IMAP FETCH response robustly."""
    if not fetch_data:
        return None
    for item in fetch_data:
        if isinstance(item, tuple):
            for part in item:
                if isinstance(part, bytes) and (b"Subject:" in part or b"From:" in part or b"Message-ID:" in part):
                    return part
        elif isinstance(item, bytes) and (b"Subject:" in item or b"From:" in item):
            return item
    # fallback: largest bytes payload (not the FETCH preamble)
    best: bytes | None = None
    for item in fetch_data:
        if isinstance(item, tuple):
            for part in item:
                if isinstance(part, bytes) and len(part) > 10:
                    if best is None or len(part) > len(best):
                        best = part
    return best


def _extract_full_bytes(fetch_data) -> bytes | None:
    if not fetch_data:
        return None
    best: bytes | None = None
    for item in fetch_data:
        if isinstance(item, tuple):
            for part in item:
                if isinstance(part, bytes) and len(part) > 10:
                    if best is None or len(part) > len(best):
                        best = part  # full RFC822 is the largest bytes chunk,
                        # not the FETCH preamble like b'1 (RFC822 {1234}'
    return best


def _envelope(uid: bytes | str, msg: Message) -> dict:
    return {
        "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
        "from": _decode_header(msg.get("From")),
        "to": _decode_header(msg.get("To")),
        "cc": _decode_header(msg.get("Cc")),
        "date": msg.get("Date", ""),
        "subject": _decode_header(msg.get("Subject")),
        "message_id": msg.get("Message-ID", ""),
    }


@mcp.tool()
def check_connection() -> str:
    """Test IMAP login to imap.mail.com. Returns OK or an error."""
    c = _cfg()
    conn = _imap()
    try:
        status, _ = conn.noop()
        return f"OK: logged in as {c['email']} on {c['imap_host']} (noop={status})"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def list_folders() -> list[str]:
    """List all IMAP mailboxes/folders."""
    conn = _imap()
    try:
        _, data = conn.list()
        folders: list[str] = []
        for line in data or []:
            text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            # '... "/" "INBOX"' -> take last quoted token
            if '"' in text:
                folders.append(text.split('"')[-2])
            else:
                folders.append(text.split()[-1])
        return folders
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _search_uids(
    conn: imaplib.IMAP4_SSL,
    folder: str,
    subject: str = "",
    from_addr: str = "",
    to_addr: str = "",
    text: str = "",
    since: str = "",
    before: str = "",
    unread_only: bool = False,
) -> list[bytes]:
    conn.select(folder, readonly=True)
    criteria: list[str] = []
    if unread_only:
        criteria.append("UNSEEN")
    if subject:
        criteria += ["SUBJECT", f'"{subject}"']
    if from_addr:
        criteria += ["FROM", f'"{from_addr}"']
    if to_addr:
        criteria += ["TO", f'"{to_addr}"']
    if text:
        criteria += ["TEXT", f'"{text}"']
    if since:
        criteria += ["SINCE", since]  # e.g. 01-Oct-2026
    if before:
        criteria += ["BEFORE", before]
    if not criteria:
        criteria = ["ALL"]
    _, data = conn.uid("SEARCH", None, *criteria)
    raw = data[0] if data else b""
    return raw.split() if raw else []


@mcp.tool()
def list_emails(folder: str = "INBOX", limit: int = 20, unread_only: bool = False) -> list[dict]:
    """List recent emails (envelope only). Use read_email for the body.

    Args:
        folder: IMAP folder, e.g. INBOX
        limit: max messages, newest last (1-100)
        unread_only: only UNSEEN messages
    """
    limit = max(1, min(limit, 100))
    conn = _imap()
    try:
        uids = _search_uids(conn, folder, unread_only=unread_only)
        tail = uids[-limit:]
        out: list[dict] = []
        for uid in tail:
            _, data = conn.uid("FETCH", uid, "(RFC822.HEADER)")
            raw = _extract_header_bytes(data)
            if not raw:
                continue
            out.append(_envelope(uid, email.message_from_bytes(raw)))
        return list(reversed(out))  # newest first
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def search_emails(
    subject: str = "",
    from_addr: str = "",
    to_addr: str = "",
    text: str = "",
    folder: str = "INBOX",
    since: str = "",
    before: str = "",
    unread_only: bool = False,
    limit: int = 20,
) -> list[dict]:
    """Search mail by sender/subject/body/date. Dates: DD-Mon-YYYY.

    Args:
        subject: match in Subject
        from_addr: match sender
        to_addr: match recipient
        text: match anywhere in body
        folder: IMAP folder
        since: e.g. 01-Oct-2026
        before: e.g. 06-Oct-2026
        unread_only: only UNSEEN
        limit: max results (1-100)
    """
    limit = max(1, min(limit, 100))
    conn = _imap()
    try:
        uids = _search_uids(conn, folder, subject, from_addr, to_addr, text, since, before, unread_only)
        out: list[dict] = []
        for uid in uids[-limit:]:
            _, data = conn.uid("FETCH", uid, "(RFC822.HEADER)")
            raw = _extract_header_bytes(data)
            if not raw:
                continue
            out.append(_envelope(uid, email.message_from_bytes(raw)))
        return list(reversed(out))
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _read_email_impl(uid: str, folder: str = "INBOX", max_body_chars: int = 20000) -> dict:
    """Shared impl so reply_email doesn't call a tool wrapper."""
    max_body_chars = max(500, min(max_body_chars, 100000))
    conn = _imap()
    try:
        conn.select(folder, readonly=True)
        _, data = conn.uid("FETCH", uid.encode(), "(RFC822)")
        raw = _extract_full_bytes(data)
        if not raw:
            return {"error": f"UID {uid} not found in {folder}"}
        msg = email.message_from_bytes(raw)
        env = _envelope(uid, msg)
        plain, _ = _message_text(msg, max_body_chars)
        env["body_text"] = plain
        env["attachments"] = _attachments_meta(msg)
        env["folder"] = folder
        return env
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def read_email(uid: str, folder: str = "INBOX", max_body_chars: int = 20000) -> dict:
    """Read one full email by UID (get UID from list_emails/search_emails).

    Args:
        uid: IMAP UID string
        folder: folder containing the message
        max_body_chars: truncate bodies to this length
    """
    return _read_email_impl(uid, folder, max_body_chars)


def _smtp_send(msg: MIMEMultipart, recipients: list[str] | None = None) -> str:
    """Send via SMTP_SSL (:465) or STARTTLS (:587). Uses explicit envelope
    recipients so BCC works (send_message alone would leak/drop BCC)."""
    c = _cfg()
    envelope = recipients or [c["email"]]
    if c["smtp_port"] == 465 or not c["smtp_starttls"]:
        with smtplib.SMTP_SSL(c["smtp_host"], c["smtp_port"]) as s:
            s.login(c["email"], c["password"])
            s.sendmail(c["email"], envelope, msg.as_string())
    else:
        with smtplib.SMTP(c["smtp_host"], c["smtp_port"]) as s:
            s.starttls()
            s.login(c["email"], c["password"])
            s.sendmail(c["email"], envelope, msg.as_string())
    return f"sent via {c['smtp_host']}:{c['smtp_port']}"


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body_text: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Send a new email from your mail.com address.

    Args:
        to: comma-separated recipients
        subject: subject line
        body_text: plain-text body
        cc: optional comma-separated CC
        bcc: optional comma-separated BCC
    """
    c = _cfg()
    msg = MIMEMultipart()
    msg["From"] = c["email"]
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    recipients = [a.strip() for a in f"{to},{cc},{bcc}".split(",") if a.strip()]
    # explicit envelope so BCC works
    _smtp_send(msg, recipients)
    return f"OK: message to {to} via {c['smtp_host']}"


@mcp.tool()
def reply_email(uid: str, body_text: str, folder: str = "INBOX", reply_all: bool = False) -> str:
    """Reply to an email, preserving threading headers.

    Args:
        uid: UID of the message to reply to
        body_text: reply body (plain text)
        folder: folder containing the original
        reply_all: include original To/Cc
    """
    original = _read_email_impl(uid, folder)
    if "error" in original:
        return original["error"]
    c = _cfg()
    msg = MIMEMultipart()
    msg["From"] = c["email"]
    msg["To"] = original["from"]
    if reply_all:
        extra = ", ".join(x for x in [original.get("to"), original.get("cc")] if x)
        if extra:
            msg["Cc"] = extra
    subj = original.get("subject", "")
    msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    if original.get("message_id"):
        msg["In-Reply-To"] = original["message_id"]
        msg["References"] = original["message_id"]
    quoted = original.get("body_text", "")[:4000]
    full = f"{body_text}\n\n--- On {original.get('date', '')}, {original.get('from', '')} wrote: ---\n{quoted}"
    msg.attach(MIMEText(full, "plain", "utf-8"))
    _smtp_send(msg)
    return f"OK: reply sent to {original['from']} (re UID {uid})"


@mcp.tool()
def mark_read(uid: str, folder: str = "INBOX", read: bool = True) -> str:
    """Mark a message read (default) or unread.

    Args:
        uid: message UID
        folder: containing folder
        read: True=\\Seen, False=remove \\Seen
    """
    conn = _imap()
    try:
        conn.select(folder)
        flag, mode = ("\\Seen", "+FLAGS") if read else ("\\Seen", "-FLAGS")
        conn.uid("STORE", uid.encode(), mode, f"({flag})")
        return f"OK: UID {uid} marked {'read' if read else 'unread'} in {folder}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def delete_email(uid: str, folder: str = "INBOX") -> str:
    """Move-free delete: flags \\Deleted + expunges. Use carefully.

    Args:
        uid: message UID
        folder: containing folder
    """
    conn = _imap()
    try:
        conn.select(folder)
        conn.uid("STORE", uid.encode(), "+FLAGS", "(\\Deleted)")
        conn.expunge()
        return f"OK: UID {uid} deleted from {folder}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def folder_stats(folder: str = "INBOX") -> dict:
    """Message + unseen counts for a folder. Cheap triage dashboard call.

    Args:
        folder: IMAP folder
    """
    conn = _imap()
    try:
        typ, data = conn.status(folder, "(MESSAGES UNSEEN)")
        text = data[0].decode(errors="replace") if data else ""
        import re

        def num(name: str) -> int:
            m = re.search(rf"{name}\s+(\d+)", text)
            return int(m.group(1)) if m else 0

        return {"folder": folder, "messages": num("MESSAGES"), "unseen": num("UNSEEN")}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


@mcp.tool()
def download_attachment(uid: str, index: int = 0, folder: str = "INBOX", max_bytes: int = 2000000) -> dict:
    """Download one attachment as base64 (capped). Index matches read_email order.

    Args:
        uid: message UID
        index: 0-based attachment index from read_email
        folder: containing folder
        max_bytes: cap decoded bytes (default 2MB)
    """
    import base64

    data = _read_email_impl(uid, folder, max_body_chars=500)
    if "error" in data:
        return data
    conn = _imap()
    try:
        conn.select(folder, readonly=True)
        _, fdata = conn.uid("FETCH", uid.encode(), "(RFC822)")
        raw = _extract_full_bytes(fdata)
        if not raw:
            return {"error": f"UID {uid} not found in {folder}"}
        msg = email.message_from_bytes(raw)
        files: list[tuple[str, str, bytes]] = []
        if msg.is_multipart():
            for part in msg.walk():
                disp = (part.get("Content-Disposition") or "").lower()
                filename = part.get_filename()
                if "attachment" in disp or filename:
                    payload = part.get_payload(decode=True) or b""
                    files.append((_decode_header(filename or "unnamed"), part.get_content_type(), payload))
        if index < 0 or index >= len(files):
            return {"error": f"attachment {index} not found (message has {len(files)})"}
        name, ctype, payload = files[index]
        truncated = len(payload) > max_bytes
        payload = payload[:max_bytes]
        return {
            "filename": name,
            "content_type": ctype,
            "size_bytes": len(payload),
            "truncated": truncated,
            "content_base64": base64.b64encode(payload).decode(),
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


if __name__ == "__main__":
    transport = _env("MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("streamable-http", "http", "shttp"):
        mcp.run(
            transport="streamable-http",
            host=_env("MCP_HOST", "127.0.0.1"),
            port=int(_env("MCP_PORT", "8000")),
        )
    else:
        mcp.run(transport="stdio")
