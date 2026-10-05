"""Offline tests: no network, no credentials. Covers parsing helpers."""

import base64
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase

import server


def _sample_msg() -> bytes:
    outer = MIMEMultipart()
    outer["From"] = "Support <support@example.com>"
    outer["To"] = "you@mail.com"
    outer["Subject"] = "Login issue #42"
    outer["Message-ID"] = "<abc123@example.com>"
    outer["Date"] = "Mon, 05 Oct 2026 10:00:00 +0000"
    outer.attach(MIMEText("Hello, my login fails.", "plain", "utf-8"))
    outer.attach(MIMEText("<p>Hello</p>", "html", "utf-8"))
    att = MIMEBase("text", "plain")
    att.set_payload("log line 1")
    att.add_header("Content-Disposition", 'attachment; filename="debug.log"')
    outer.attach(att)
    return outer.as_bytes()


def test_decode_header():
    assert server._decode_header(None) == ""
    assert server._decode_header("plain") == "plain"


def test_message_text_and_attachments():
    msg = email.message_from_bytes(_sample_msg())
    plain, html = server._message_text(msg, 20000)
    assert "login fails" in plain
    assert html and "Hello" in html
    att = server._attachments_meta(msg)
    assert len(att) == 1 and att[0]["filename"] == "debug.log"


def test_envelope():
    msg = email.message_from_bytes(_sample_msg())
    env = server._envelope(b"123", msg)
    assert env["uid"] == "123"
    assert env["subject"] == "Login issue #42"
    assert "support@example.com" in env["from"]


def test_extract_helpers():
    raw = _sample_msg()
    fetch = [(b"1 (RFC822.HEADER {100}", raw), b")"]
    assert server._extract_header_bytes(fetch) == raw
    assert server._extract_full_bytes(fetch) == raw
    assert server._extract_header_bytes(None) is None
    assert server._extract_full_bytes([]) is None


def test_tools_registered():
    tools = [t.name for t in server.mcp._tool_manager.list_tools()]
    for name in [
        "check_connection", "list_folders", "folder_stats", "list_emails",
        "search_emails", "read_email", "download_attachment", "send_email",
        "reply_email", "mark_read", "delete_email",
    ]:
        assert name in tools, f"missing tool {name}"
